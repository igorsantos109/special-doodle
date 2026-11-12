#!/usr/bin/env python3
"""Harness de testes do Memory Writer (validação das 4 regras).

Testa um endpoint writer qualquer (OpenAI-compatible) com o System Prompt
oficial e valida:
  Regra 1 - sem inferência/invenção (memórias devem conter só o que foi dito)
  Regra 2 - frases autossuficientes (sem pronomes soltos "ele/ela/isso")
  Regra 3 - sem small talk/ruído (nada de "Oi!", "tchau", emoções passageiras)
  Regra 4 - saída é JSON puro com chave "memories" (lista de strings)

Uso:
  python3 run_memory_tests.py --endpoint http://127.0.0.1:8081/v1/chat/completions \
      --model qwen3.8-flash-next-gyro-gyro-s

Sem argumentos, roda contra os endpoints padrão locais.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request

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

# Caso de teste: mistura fatos duradouros + small talk + opinião passageira
# que NÃO deve virar memória.
TEST_CONVERSATION = """\
Usuário: Oi! Bom dia!
Usuário: Sou o Alex, trabalho como arquiteto de software em Berlim.
Usuário: Hoje acordei cansado, não gosto de segunda-feira.
Usuário: Odeio quando o código não tem testes.
Usuário: Prefiro sempre modo escuro no editor.
Usuário: Ah, e sou vegetariano.
Assistente: Olá Alex! Entendido, vou lembrar disso.
Usuário: Obrigado, até mais!
"""

# Fatos esperados (presentes na conversa, autossuficientes)
EXPECTED_FACTS = [
    "Alex",
    "arquiteto de software",
    "Berlim",
    "vegetariano",
    "modo escuro",
    "testes",
]

# Ruído que NÃO deve aparecer (regra 3)
FORBIDDEN_WORDS = ["cansado", "segunda-feira", "bom dia", "até mais", "obrigado"]

# Pronomes soltos (regra 2) — regex simples em pt/en
PRONOUN_RE = re.compile(
    r"\b(ele|ela|esse|essa|isso|este|esta|his|her|their|this|that)\b",
    re.IGNORECASE,
)


def extract_json(text: str) -> dict:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1]
        if "```" in t:
            t = t.rsplit("```", 1)[0]
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    s, e = t.find("{"), t.rfind("}")
    if s != -1 and e > s:
        return json.loads(t[s : e + 1])
    raise ValueError(f"sem JSON: {text[:200]!r}")


def call(endpoint: str, model: str, conversation: str, temperature: float = 0.6,
         max_tokens: int = 1024, timeout: float = 600) -> dict:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": conversation},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode())
    elapsed = time.monotonic() - t0
    msg = data["choices"][0]["message"]
    content = msg.get("content") or ""
    parsed = extract_json(content)  # Regra 4: JSON parseável
    timings = data.get("timings") or {}
    return {
        "memories": parsed.get("memories", []),
        "raw": content,
        "elapsed_s": round(elapsed, 1),
        "usage": data.get("usage"),
        "timings": timings,
        "finish_reason": data["choices"][0].get("finish_reason"),
        "reasoning_len": len(msg.get("reasoning_content") or ""),
    }


def check_rules(memories: list[str]) -> dict:
    joined = " ".join(memories).lower()
    # Regra 1: todos os fatos esperados presentes (pelo menos 4 dos 6)
    found = [f for f in EXPECTED_FACTS if f.lower() in joined]
    rule1 = len(found) >= 4
    # Regra 2: nenhum pronome solto
    pronouns = PRONOUN_RE.findall(" ".join(memories))
    rule2 = len(pronouns) == 0
    # Regra 3: nenhum ruído
    noise = [w for w in FORBIDDEN_WORDS if w in joined]
    rule3 = len(noise) == 0
    # Regra 4: já garantida pelo parse (se chegou aqui, era JSON válido)
    rule4 = isinstance(memories, list) and all(isinstance(m, str) for m in memories)
    return {
        "rule1_no_inference": {"ok": rule1, "facts_found": found, "of": EXPECTED_FACTS},
        "rule2_self_contained": {"ok": rule2, "pronouns_found": pronouns},
        "rule3_no_noise": {"ok": rule3, "noise_found": noise},
        "rule4_json": {"ok": rule4, "n_memories": len(memories)},
        "memories": memories,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", default=None, help="URL /v1/chat/completions")
    ap.add_argument("--model", default=None)
    ap.add_argument("--temperature", type=float, default=0.6)
    ap.add_argument("--all", action="store_true", help="testa os endpoints padrão locais")
    args = ap.parse_args()

    targets = []
    if args.all or (not args.endpoint):
        targets = [
            ("http://127.0.0.1:8081/v1/chat/completions", "qwen3.8-flash-next-gyro-gyro-s", "gyro-s-8081"),
            ("http://127.0.0.1:8103/v1/chat/completions", "qwen3-1.7b", "qwen3-1.7b-8103"),
            ("http://127.0.0.1:8104/v1/chat/completions", "lfm2.5-1.2b", "lfm2.5-8104"),
        ]
    else:
        targets = [(args.endpoint, args.model or "?", "custom")]

    overall_ok = True
    for endpoint, model, label in targets:
        print(f"\n{'=' * 70}\nTESTANDO: {label}  ({endpoint})\n{'=' * 70}")
        try:
            res = call(endpoint, model, TEST_CONVERSATION, args.temperature)
        except Exception as e:  # noqa: BLE001
            print(f"  FALHA na chamada: {e}")
            overall_ok = False
            continue
        checks = check_rules(res["memories"])
        t = res["timings"]
        print(f"  tempo total: {res['elapsed_s']} s | "
              f"prompt {t.get('prompt_per_second')} tok/s | "
              f"decode {t.get('predicted_per_second')} tok/s | "
              f"completion {t.get('predicted_n')} tok | "
              f"reasoning {res['reasoning_len']} chars | finish={res['finish_reason']}")
        print(f"  JSON bruto (primeiros 300): {res['raw'][:300]!r}")
        for m in res["memories"]:
            print(f"    • {m}")
        for rule, r in checks.items():
            if rule == "memories":
                continue
            status = "✅" if r["ok"] else "❌"
            extra = {k: v for k, v in r.items() if k not in ("ok",)}
            print(f"  {status} {rule}: {extra}")
            if not r["ok"]:
                overall_ok = False

    print(f"\n{'=' * 70}\nRESULTADO GERAL: {'TODOS OK' if overall_ok else 'HÁ FALHAS'}\n{'=' * 70}")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
