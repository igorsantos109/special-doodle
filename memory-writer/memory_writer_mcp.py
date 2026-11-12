#!/usr/bin/env python3
"""Memory Writer MCP server (Model Context Protocol, stdio, JSON-RPC 2.0).

Arquitetura (design "memory writer como função de extração"):
  - O agente de chat NÃO extrai memórias por conta própria.
  - Ele chama a tool `memory_extract_and_store` com o texto da conversa.
  - Este server chama o LLM WRITER (endpoint configurável via env) com o
    System Prompt de extração (4 regras), recebe o JSON {"memories": [...]}
    e grava no SQLite.

Tools expostas:
  memory_extract_and_store  {project, conversation, category?}
                            -> chama o writer LLM, parseia o JSON e grava
  memory_write              {project, content, category?, tags?}
                            -> grava uma memória direta (sem LLM)
  memory_read               {project, category?, limit?}
                            -> lista memórias recentes
  memory_search             {project, query}
                            -> busca por texto (LIKE)
  memory_delete             {memory_id}
                            -> apaga por id

Env:
  MEMORY_DB             (padrão ~/.local/share/pc-sala-agent/memory.db)
  MEMORY_WRITER_ENDPOINT  (padrão http://127.0.0.1:8081/v1/chat/completions)
  MEMORY_WRITER_MODEL     (padrão qwen3.8-flash-next-gyro-gyro-s)
  MEMORY_WRITER_TEMPERATURE (padrão 0.6)
  MEMORY_WRITER_MAX_TOKENS  (padrão 1024)

Somente stdlib; sem dependências externas.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request

DB_PATH = os.environ.get(
    "MEMORY_DB",
    os.path.expanduser("~/.local/share/pc-sala-agent/memory.db"),
)
WRITER_ENDPOINT = os.environ.get(
    "MEMORY_WRITER_ENDPOINT",
    "http://127.0.0.1:8081/v1/chat/completions",
)
WRITER_MODEL = os.environ.get("MEMORY_WRITER_MODEL", "qwen3.8-flash-next-gyro-gyro-s")
WRITER_TEMPERATURE = float(os.environ.get("MEMORY_WRITER_TEMPERATURE", "0.3"))
WRITER_MAX_TOKENS = int(os.environ.get("MEMORY_WRITER_MAX_TOKENS", "1024"))
WRITER_TIMEOUT_S = float(os.environ.get("MEMORY_WRITER_TIMEOUT_S", "600"))

# ---------------------------------------------------------------------------
# System Prompt do writer — as 4 regras fundamentais
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """\
You are a memory extraction engine. You read a conversation and extract
explicit user facts and preferences into a long-term memory store.

Rules (strict):
1. Extract ONLY facts and preferences EXPLICITLY stated by the user.
   Do not infer or invent information. If the user says "I am vegetarian",
   the memory is "The user is vegetarian" - never "the user dislikes meat".
2. Write each memory as a concise, self-contained statement. Memories are
   read later without the original conversation, so no unresolved pronouns,
   no "the user said", no references to "above" or "earlier".
3. Ignore greetings, small talk, transient emotions and one-off opinions.
   Keep only durable facts about the user (identity, preferences, constraints,
   decisions, project facts).
4. Respond with ONLY a JSON object, no markdown fences, no explanation, in
   this exact shape: {"memories": ["statement 1", "statement 2"]}
   If there is nothing worth remembering, return {"memories": []}.

Write the memory statements in the same language as the conversation.
"""


# ---------------------------------------------------------------------------
# Banco de dados
# ---------------------------------------------------------------------------
def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.execute(
        """CREATE TABLE IF NOT EXISTS memories (
               id INTEGER PRIMARY KEY,
               project TEXT NOT NULL,
               category TEXT NOT NULL DEFAULT 'fact',
               content TEXT NOT NULL,
               tags TEXT NOT NULL DEFAULT '',
               source TEXT NOT NULL DEFAULT 'writer',
               created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"""
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_memories_project "
        "ON memories(project, created_at DESC)"
    )
    return c


def store(project: str, items: list[dict], source: str = "writer") -> list[dict]:
    c = _conn()
    saved = []
    for m in items:
        content = str(m.get("content", "")).strip()
        if not content:
            continue
        cur = c.execute(
            "INSERT INTO memories (project, category, content, tags, source) "
            "VALUES (?,?,?,?,?)",
            (
                project,
                str(m.get("category", "fact")),
                content,
                str(m.get("tags", "")),
                source,
            ),
        )
        saved.append({"id": cur.lastrowid, "content": content})
    c.commit()
    c.close()
    return saved


def read(project: str, category: str = "", limit: int = 20) -> list[dict]:
    c = _conn()
    q = "SELECT id, category, content, tags, source, created_at FROM memories WHERE project=?"
    args: list = [project]
    if category:
        q += " AND category=?"
        args.append(category)
    q += " ORDER BY created_at DESC, id DESC LIMIT ?"
    args.append(max(1, min(int(limit), 200)))
    rows = c.execute(q, args).fetchall()
    c.close()
    return [
        {
            "id": r[0],
            "category": r[1],
            "content": r[2],
            "tags": r[3],
            "source": r[4],
            "created_at": r[5],
        }
        for r in rows
    ]


def search(project: str, query: str, limit: int = 20) -> list[dict]:
    c = _conn()
    q = (
        "SELECT id, category, content, tags, source, created_at FROM memories "
        "WHERE project=? AND (content LIKE ? OR tags LIKE ?) "
        "ORDER BY created_at DESC, id DESC LIMIT ?"
    )
    like = f"%{query}%"
    rows = c.execute(q, (project, like, like, max(1, min(int(limit), 200)))).fetchall()
    c.close()
    return [
        {
            "id": r[0],
            "category": r[1],
            "content": r[2],
            "tags": r[3],
            "source": r[4],
            "created_at": r[5],
        }
        for r in rows
    ]


def delete(memory_id: int) -> bool:
    c = _conn()
    cur = c.execute("DELETE FROM memories WHERE id=?", (int(memory_id),))
    c.commit()
    n = cur.rowcount
    c.close()
    return n > 0


# ---------------------------------------------------------------------------
# Chamada ao LLM writer (extração)
# ---------------------------------------------------------------------------
def _extract_json(text: str) -> dict:
    """Tira o JSON do texto, tolerando fences ``` e texto residual."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1]
        if "```" in t:
            t = t.rsplit("```", 1)[0]
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end > start:
        return json.loads(t[start : end + 1])
    raise ValueError(f"sem JSON válido na resposta: {text[:200]!r}")


def call_writer(conversation: str) -> dict:
    """Chama o writer LLM e devolve {"memories": [...], "raw": ..., "timings": ...}."""
    user_msg = (
        "CONVERSATION:\n<<<\n" + conversation + "\n>>>\n"
        "Task: extract memories from the CONVERSATION above. You are NOT the "
        "assistant in it - do not answer it. Output ONLY the JSON object."
    )
    body = {
        "model": WRITER_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        "temperature": WRITER_TEMPERATURE,
        "max_tokens": WRITER_MAX_TOKENS,
    }
    req = urllib.request.Request(
        WRITER_ENDPOINT,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=WRITER_TIMEOUT_S) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    elapsed = time.monotonic() - t0
    msg = data["choices"][0]["message"]
    content = msg.get("content") or ""
    parsed = _extract_json(content)
    memories = parsed.get("memories", [])
    if not isinstance(memories, list):
        raise ValueError(f"'memories' não é lista: {type(memories)}")
    memories = [str(m).strip() for m in memories if str(m).strip()]
    timings = data.get("timings") or {}
    return {
        "memories": memories,
        "raw": content,
        "reasoning": msg.get("reasoning_content"),
        "timings": {
            "elapsed_s": round(elapsed, 2),
            "prompt_tokens": (data.get("usage") or {}).get("prompt_tokens"),
            "completion_tokens": (data.get("usage") or {}).get("completion_tokens"),
            "prompt_tok_s": timings.get("prompt_per_second"),
            "decode_tok_s": timings.get("predicted_per_second"),
        },
    }


def extract_and_store(project: str, conversation: str, category: str = "fact") -> dict:
    result = call_writer(conversation)
    items = [{"category": category, "content": m} for m in result["memories"]]
    saved = store(project, items, source=f"writer:{WRITER_MODEL}")
    result["stored"] = saved
    result["db"] = DB_PATH
    return result


# ---------------------------------------------------------------------------
# MCP protocol (stdio, JSON-RPC 2.0 newline-delimited)
# ---------------------------------------------------------------------------
TOOLS = [
    {
        "name": "memory_extract_and_store",
        "description": (
            "Extrai fatos e preferências explícitos de uma conversa usando o "
            "writer LLM (4 regras: sem inferência, frases autossuficientes, "
            "sem small talk, saída JSON) e grava no banco de memória."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Nome do projeto"},
                "conversation": {
                    "type": "string",
                    "description": "Transcrição da conversa (mensagens do usuário)",
                },
                "category": {
                    "type": "string",
                    "description": "Categoria (default: fact). Ex.: preferencia, decisao, identidade",
                },
            },
            "required": ["project", "conversation"],
        },
    },
    {
        "name": "memory_write",
        "description": "Grava uma memória direta no banco, sem passar pelo writer LLM.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "content": {"type": "string"},
                "category": {"type": "string"},
                "tags": {"type": "string"},
            },
            "required": ["project", "content"],
        },
    },
    {
        "name": "memory_read",
        "description": "Lista memórias recentes de um projeto.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "category": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["project"],
        },
    },
    {
        "name": "memory_search",
        "description": "Busca memórias por texto (contém) em conteúdo e tags.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "query": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["project", "query"],
        },
    },
    {
        "name": "memory_delete",
        "description": "Apaga uma memória pelo id.",
        "inputSchema": {
            "type": "object",
            "properties": {"memory_id": {"type": "integer"}},
            "required": ["memory_id"],
        },
    },
]


def handle(msg: dict) -> dict | None:
    method = msg.get("method")
    mid = msg.get("id")
    params = msg.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": mid,
            "result": {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "memory-writer", "version": "1.0.0"},
            },
        }
    if method in ("notifications/initialized",):
        return None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            if name == "memory_extract_and_store":
                r = extract_and_store(
                    args["project"], args["conversation"], args.get("category", "fact")
                )
                text = (
                    f"Extraídas {len(r['memories'])} memórias, {len(r['stored'])} gravadas "
                    f"em {r['db']} (writer {WRITER_MODEL}, {r['timings']['elapsed_s']} s):\n"
                    + "\n".join(f"  [{s['id']}] {s['content']}" for s in r["stored"])
                    + f"\nTiming: prompt={r['timings']['prompt_tok_s']} tok/s, "
                    f"decode={r['timings']['decode_tok_s']} tok/s"
                )
            elif name == "memory_write":
                s = store(
                    args["project"],
                    [
                        {
                            "category": args.get("category", "fact"),
                            "content": args["content"],
                            "tags": args.get("tags", ""),
                        }
                    ],
                    source="direct",
                )
                text = f"Memória {s[0]['id']} gravada: {s[0]['content']}"
            elif name == "memory_read":
                rows = read(args["project"], args.get("category", ""), args.get("limit", 20))
                text = json.dumps(rows, ensure_ascii=False)
            elif name == "memory_search":
                rows = search(args["project"], args["query"], args.get("limit", 20))
                text = json.dumps(rows, ensure_ascii=False)
            elif name == "memory_delete":
                ok = delete(args["memory_id"])
                text = f"Memória {args['memory_id']} apagada." if ok else "id não encontrado."
            else:
                raise ValueError(f"tool desconhecida: {name}")
            return {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {"content": [{"type": "text", "text": text}], "isError": False},
            }
        except Exception as e:  # noqa: BLE001 - devolve como resultado, não quebra a chat
            return {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {
                    "content": [{"type": "text", "text": f"error: {e}"}],
                    "isError": True,
                },
            }
    if mid is not None:
        return {
            "jsonrpc": "2.0",
            "id": mid,
            "error": {"code": -32601, "message": f"method not found: {method}"},
        }
    return None


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            resp = handle(msg)
        except json.JSONDecodeError as e:
            resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"parse error: {e}"},
            }
        except Exception as e:  # noqa: BLE001
            resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32603, "message": f"internal error: {e}"},
            }
        if resp is not None:
            print(json.dumps(resp, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
