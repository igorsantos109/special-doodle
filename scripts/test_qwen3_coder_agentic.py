#!/usr/bin/env python3
"""Teste agêntico de programação — Qwen3-Coder-30B-A3B (porta 8084, ctx max 32768).

Padrão da suíte maple-pro (tests/test_maple_pro_*.py do repo):
  T1 chat pt-BR
  T2 geração de código (extração + compile())
  T3 tool calling (JSON, --jinja)
  T4 restraint (sem tools)
  T5 agulha no palheiro em contexto máximo (~32K tokens, streaming, TTFT + tok/s)
  T6 overflow (prompt > 32768 → erro limpo, sem hang)
  T7 concorrência (3 requests paralelos)
  T8 loop agêntico 2 turnos (tool call -> injeção de resultado -> resposta final;
     tool_call extra no turno 2 registado como diagnóstico de fiabilidade)

Uso:  python3 scripts/test_qwen3_coder_agentic.py [--base http://127.0.0.1:8084]
Saída: tabela no stdout + JSON em /tmp/kilo/qwen3_coder_agentic_<ts>.json
"""

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

DEFAULT_BASE = "http://127.0.0.1:8084"
MAX_CTX = 32768
TIMEOUT = 300

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Obter o tempo atual de uma cidade",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "Avaliar uma expressão aritmética",
            "parameters": {
                "type": "object",
                "properties": {"expression": {"type": "string"}},
                "required": ["expression"],
            },
        },
    },
]


def post_chat(base, model, messages, max_tokens=1024, tools=None, timeout=TIMEOUT):
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    req = urllib.request.Request(
        base.rstrip("/") + "/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"http_error": e.code, "body": e.read().decode()[:500], "seconds": time.time() - t0,
                "content": "", "tool_calls": [], "finish_reason": None}
    dt = time.time() - t0
    choice = (body.get("choices") or [{}])[0]
    usage = body.get("usage") or {}
    return {
        "content": (choice.get("message") or {}).get("content") or "",
        "tool_calls": (choice.get("message") or {}).get("tool_calls") or [],
        "finish_reason": choice.get("finish_reason"),
        "seconds": dt,
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
    }


def post_chat_stream(base, model, messages, max_tokens=1024, timeout=TIMEOUT):
    """Streaming SSE: mede TTFT (prefill) e tok/s de decode."""
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "stream": True,
    }
    req = urllib.request.Request(
        base.rstrip("/") + "/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.time()
    ttft = None
    content = ""
    tokens = 0
    finish = None
    usage = {}
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw in resp:
                line = raw.decode().strip()
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                piece = delta.get("content") or ""
                if piece:
                    if ttft is None:
                        ttft = time.time() - t0
                    content += piece
                    tokens += 1
                finish = (chunk.get("choices") or [{}])[0].get("finish_reason") or finish
                if chunk.get("usage"):
                    usage = chunk["usage"]
    except urllib.error.HTTPError as e:
        return {"http_error": e.code, "body": e.read().decode()[:500], "seconds": time.time() - t0,
                "content": "", "finish_reason": None, "ttft_s": None, "total_s": None,
                "decode_tps": None, "prompt_tokens": None, "completion_tokens": None}
    total = time.time() - t0
    decode = (total - ttft) if ttft is not None else total
    return {
        "content": content,
        "finish_reason": finish,
        "ttft_s": round(ttft, 2) if ttft is not None else None,
        "total_s": round(total, 2),
        "decode_tps": round(tokens / decode, 2) if decode > 0 and tokens else None,
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens") or tokens,
    }


def count_tokens(base, text):
    """POST /tokenize — este build usa o campo `content` (não `prompt`)."""
    req = urllib.request.Request(
        base.rstrip("/") + "/tokenize",
        data=json.dumps({"content": text, "add_special": False}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            toks = json.loads(r.read().decode()).get("tokens") or []
        return len(toks) if toks else max(1, len(text) // 4)
    except Exception:
        return max(1, len(text) // 4)


def extract_function(text):
    m = re.search(r"```python\s*(.*?)```", text, re.S)
    src = m.group(1) if m else text
    fn = re.search(r"(?:^|\n)(def \w+.*?)(?=\n(?:def |class |\Z))", src, re.S)
    return fn.group(1) if fn else src


def build_needle_prompt(base, target_tokens=31000):
    """Prompt com ~target_tokens tokens (medidos por /tokenize), agulha no módulo do meio."""
    lines = []
    for i in range(200):
        lines.append(f"def utilitario_{i:03d}(x, y={i}):")
        lines.append(f"    return (x + {i}) * {i % 7 + 1}")
    block = "# BLOCO\n" + "\n".join(lines) + "\n"
    tok_por_modulo = count_tokens(base, block)
    if tok_por_modulo < 100:
        tok_por_modulo = 2500  # guarda contra resposta vazia do /tokenize
    n_modulos = min(max(2, -(-target_tokens // tok_por_modulo)), 200)
    prompt, real = _rebuild(base, block, n_modulos)
    # ajuste fino: sobe/desce 1 módulo até ficar no alvo (e abaixo do teto de ctx)
    for _ in range(6):
        if real > MAX_CTX - 1024 and n_modulos > 2:
            n_modulos -= 1
        elif real < target_tokens * 0.92 and real + tok_por_modulo < MAX_CTX - 1024 and n_modulos < 200:
            n_modulos += 1
        else:
            break
        prompt, real = _rebuild(base, block, n_modulos)
    return prompt, real


def _rebuild(base, block, n_modulos):
    idx_agulha = n_modulos // 2
    blocks = []
    for n in range(n_modulos):
        chunks = [f"# === modulo {n:02d} ===\n" + block]
        if n == idx_agulha:
            chunks.append("# CONFIG_CRITICAL: NEEDLE_QWEN3CODER_7391 = 'groucho'\n")
        blocks.append("\n".join(chunks))
    prefix = (
        f"O código-fonte abaixo tem {n_modulos} módulos numerados. Responda em JSON com "
        "apenas duas chaves:\n"
        '1. "agulha": o valor de NEEDLE_QWEN3CODER_7391;\n'
        '2. "modulo_07": o valor de retorno de utilitario_007(1, y=7) (função do bloco).\n'
        "Código:\n"
    )
    prompt = prefix + "\n".join(blocks)
    return prompt, count_tokens(base, prompt)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--skip-overflow", action="store_true")
    ap.add_argument("--only", default="", help="só os testes indicados, ex.: T5_agulha_32k,T8_loop_agentico")
    args = ap.parse_args()
    base = args.base
    only = {t.strip() for t in args.only.split(",") if t.strip()}
    def run(tname):
        return not only or tname in only

    # 0) health + modelo
    t0 = time.time()
    while time.time() - t0 < 900:
        try:
            with urllib.request.urlopen(base + "/health", timeout=5) as r:
                if r.status == 200:
                    break
        except Exception:
            time.sleep(5)
    else:
        print("FALHA: /health nunca respondeu em 900 s", file=sys.stderr)
        sys.exit(1)
    with urllib.request.urlopen(base + "/v1/models", timeout=10) as r:
        models = json.loads(r.read().decode())
    model = ((models.get("data") or [{}])[0]).get("id", "qwen3-coder-30b-a3b")
    print(f"model: {model}\n")

    results = {}

    # T1 chat
    if run("T1_chat"):
        r = post_chat(base, model, [{"role": "user", "content": "Em duas frases: qual a diferença entre MoE e Transformer denso?"}])
        results["T1_chat"] = {"ok": len(r.get("content", "")) > 20, "finish": r.get("finish_reason"),
                              "seg": round(r.get("seconds", 0), 1), "amostra": r.get("content", "")[:120]}

    # T2 código
    if run("T2_codigo"):
        r = post_chat(base, model, [{"role": "user", "content": (
            "Escreva em Python a função `parse_log_line(line)` que recebe uma linha de log "
            "no formato '2026-11-09T12:00:00Z INFO mensagem' e devolve um dict com as chaves "
            "'timestamp', 'level' e 'message'. Só o código num bloco ```python`."
        )}])
        fn = extract_function(r.get("content", ""))
        try:
            compile(fn, "<t2>", "exec")
            ok = "parse_log_line" in fn
        except SyntaxError as e:
            ok, compile_err = False, str(e)
        results["T2_codigo"] = {"ok": ok, "finish": r.get("finish_reason"),
                                "seg": round(r.get("seconds", 0), 1), "compilou": ok}

    # T3 tool calling
    if run("T3_tools"):
        r = post_chat(base, model, [
            {"role": "system", "content": "Você tem ferramentas. Use-as quando necessário."},
            {"role": "user", "content": "Qual é a temperatura em Lisboa e quanto é 127 * 3?"},
        ], tools=TOOLS)
        calls = r.get("tool_calls") or []
        names = [c.get("function", {}).get("name") for c in calls]
        args_ok = True
        for c in calls:
            try:
                json.loads(c.get("function", {}).get("arguments") or "{}")
            except json.JSONDecodeError:
                args_ok = False
        results["T3_tools"] = {"ok": "get_weather" in names and "calculate" in names and args_ok,
                               "calls": names, "args_json_valido": args_ok,
                               "finish": r.get("finish_reason"), "seg": round(r.get("seconds", 0), 1)}

    # T4 restraint
    if run("T4_restraint"):
        r = post_chat(base, model, [{"role": "user", "content": "Responda em uma frase: por que MoE economiza FLOPs?"}])
        results["T4_restraint"] = {"ok": not r.get("tool_calls") and len(r.get("content", "")) > 10,
                                   "finish": r.get("finish_reason"), "seg": round(r.get("seconds", 0), 1)}

    # T5 agulha 32K (streaming)
    if run("T5_agulha_32k"):
        prompt, tok_reais = build_needle_prompt(base)
        r = post_chat_stream(base, model, [{"role": "user", "content": prompt}], max_tokens=512, timeout=900)
        agulha_ok = "groucho" in r.get("content", "")
        try:
            js = json.loads(re.search(r"\{.*\}", r.get("content", ""), re.S).group(0))
            parsed_ok = js.get("agulha") == "groucho"
        except Exception:
            parsed_ok = agulha_ok
        results["T5_agulha_32k"] = {"ok": parsed_ok, "finish": r.get("finish_reason"),
                                    "prompt_tokens": r.get("prompt_tokens") or tok_reais,
                                    "ttft_s": r.get("ttft_s"), "decode_tps": r.get("decode_tps"),
                                    "total_s": r.get("total_s"), "http_error": r.get("http_error"),
                                    "erro": (r.get("body") or "")[:200],
                                    "amostra": r.get("content", "")[:150]}

    # T6 overflow
    if run("T6_overflow") and not args.skip_overflow:
        r = post_chat(base, model, [{"role": "user", "content": "x " * 40000}], max_tokens=64, timeout=180)
        limpo = ("http_error" in r) or r.get("finish_reason") in ("length", "stop") or "context" in json.dumps(r).lower()
        results["T6_overflow"] = {"ok": limpo, "http_error": r.get("http_error"),
                                  "finish": r.get("finish_reason"), "seg": round(r.get("seconds", 0), 1)}

    # T7 concorrência
    if run("T7_concorrencia"):
        def t7(_):
            rr = post_chat(base, model, [{"role": "user", "content": "Responda: ok"}], max_tokens=16, timeout=120)
            return rr.get("content") or rr.get("http_error")
        with ThreadPoolExecutor(3) as ex:
            outs = list(ex.map(t7, range(3)))
        results["T7_concorrencia"] = {"ok": sum(1 for o in outs if isinstance(o, str) and o) == 3, "out": outs}

    # T8 loop agêntico 2 turnos
    if run("T8_loop_agentico"):
        msgs = [
            {"role": "system", "content": "Você tem ferramentas. Use-as quando necessário."},
            {"role": "user", "content": "Qual é o tempo em São Paulo?"},
        ]
        r1 = post_chat(base, model, msgs, tools=TOOLS)
        calls = r1.get("tool_calls") or []
        if calls:
            call = calls[0]
            msgs.append({"role": "assistant", "content": r1.get("content") or "", "tool_calls": [call]})
            args_c = json.loads(call.get("function", {}).get("arguments") or "{}")
            msgs.append({"role": "tool", "tool_call_id": call.get("id", "call_0"),
                         "content": json.dumps({"city": args_c.get("city", "?"), "temp_c": 19, "cond": "parcial"})})
            r2 = post_chat(base, model, msgs, tools=TOOLS)
            # ok = resposta final correta; tool_call extra no turno 2 é registado
            # como diagnóstico de fiabilidade do loop (medido 2/3 limpo a temp 0.2)
            t8_ok = "19" in r2.get("content", "")
        else:
            t8_ok = False
            r2 = {}
        results["T8_loop_agentico"] = {"ok": t8_ok, "tool_chamado": calls and calls[0].get("function", {}).get("name"),
                                       "tool_calls_turno2": [c.get("function", {}).get("name") for c in (r2.get("tool_calls") or [])],
                                       "finish_turno2": r2.get("finish_reason"),
                                       "resposta_final": (r2.get("content") or "")[:120]}

    # Resumo
    print(f"{'Teste':22s} {'OK':4s} {'detalhe'}")
    print("-" * 72)
    passed = 0
    for k, v in results.items():
        mark = "ok" if v.get("ok") else "FALHOU"
        passed += 1 if v.get("ok") else 0
        detail = {kk: vv for kk, vv in v.items() if kk not in ("ok", "amostra", "out", "resposta_final", "compilou")}
        print(f"{k:22s} {mark:6s} {detail}")
    print("-" * 72)
    print(f"{passed}/{len(results)} passaram")

    out = f"/tmp/kilo/qwen3_coder_agentic_{int(time.time())}.json"
    with open(out, "w") as f:
        json.dump({"base": base, "model": model, "ts": time.time(), "results": results}, f, indent=2, default=str)
    print("JSON:", out)


if __name__ == "__main__":
    main()
