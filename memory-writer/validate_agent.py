#!/usr/bin/env python3
"""Validação de integração do agente real contra o Strata no PC-SALA.

Dois testes (requisito #4 do plano):
  1. Geração de código  — prompt de coding, mede prefill+decode+tempo total
  2. Escrita de memória  — chama o writer LLM (4 regras) e valida o JSON

Roda do PC local apontando para o túnel (127.0.0.1:18081 → PC-SALA:8081).

Uso:
  python3 validate_agent.py --endpoint http://127.0.0.1:18081/v1/chat/completions \
      --model qwen3.8-flash-next-gyro-gyro-s
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request

CODE_PROMPT = (
    "Escreva em Python uma função `sliding_window_median(arr, k)` que retorna a "
    "mediana de cada janela deslizante de tamanho k em arr. Use uma solução "
    "eficiente (dois heaps ou sortedlist). Só o código, sem explicação."
)

MEMORY_PROMPT = (
    "Usuário: Oi, sou a Marina, sou product manager e trabalho remota de Lisboa. "
    "Prefiro que as respostas tenham um resumo no topo e depois os detalhes. "
    "Não me mande emojis, por favor.\n"
    "Assistente: Entendido, Marina!\n"
    "Usuário: Perfeito, obrigado."
)

MEMORY_SYSTEM = """\
You are a memory extraction engine. Extract explicit user facts and preferences.
1. Extract ONLY facts EXPLICITLY stated. Do not infer or invent.
2. Each memory = concise, self-contained statement (no unresolved pronouns).
3. Ignore greetings, small talk, transient emotions, one-off opinions.
4. Respond with ONLY a JSON object, no markdown: {"memories": ["...","..."]}
Write statements in the conversation's language.
"""


def call(endpoint: str, model: str, messages: list[dict], max_tokens: int,
         temperature: float = 0.0, no_think: bool = False) -> dict:
    body = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if no_think:
        body["thinking_budget_tokens"] = 0
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=600) as r:
        data = json.loads(r.read().decode())
    elapsed = time.monotonic() - t0
    msg = data["choices"][0]["message"]
    return {
        "content": msg.get("content") or "",
        "reasoning": (msg.get("reasoning_content") or "")[:200],
        "finish": data["choices"][0].get("finish_reason"),
        "usage": data.get("usage"),
        "timings": data.get("timings") or {},
        "elapsed_s": round(elapsed, 2),
    }


def test_code(endpoint: str, model: str) -> dict:
    print("\n" + "=" * 70 + "\nTESTE 1 — GERAÇÃO DE CÓDIGO (no-think)\n" + "=" * 70)
    res = call(endpoint, model,
               [{"role": "user", "content": CODE_PROMPT}], max_tokens=1600, no_think=True)
    t = res["timings"]
    body = res["content"].strip()
    print(f"tempo total: {res['elapsed_s']} s | finish: {res['finish']}")
    print(f"prompt: {t.get('prompt_per_second')} tok/s | "
          f"decode: {t.get('predicted_per_second')} tok/s | "
          f"usage: {res['usage']}")
    print(f"\n--- código ({len(body)} chars) ---\n{body[:1200]}")
    ok = "def sliding_window_median" in body and ("heapq" in body or "bisect" in body
                                                  or "SortedList" in body or "insort" in body)
    print(f"\nverificação: função presente + estrutura eficiente = {ok}")
    res["ok"] = ok
    return res


def test_memory(endpoint: str, model: str) -> dict:
    print("\n" + "=" * 70 + "\nTESTE 2 — ESCRITA DE MEMÓRIA (4 regras)\n" + "=" * 70)
    user_msg = (
        "CONVERSATION:\n<<<\n" + MEMORY_PROMPT + "\n>>>\n"
        "Task: extract memories from the CONVERSATION above. You are NOT the "
        "assistant in it - do not answer it. Output ONLY the JSON object."
    )
    res = call(endpoint, model,
               [{"role": "system", "content": MEMORY_SYSTEM},
                {"role": "user", "content": user_msg}],
               max_tokens=400, temperature=0.3, no_think=True)
    t = res["timings"]
    raw = res["content"].strip()
    print(f"tempo total: {res['elapsed_s']} s | finish: {res['finish']}")
    print(f"prompt: {t.get('prompt_per_second')} tok/s | "
          f"decode: {t.get('predicted_per_second')} tok/s")
    print(f"\n--- JSON bruto ---\n{raw[:600]}")
    try:
        obj = json.loads(raw) if raw.startswith("{") else json.loads(
            raw[raw.find("{"):raw.rfind("}") + 1])
        mems = obj.get("memories", [])
    except json.JSONDecodeError:
        mems = None
    ok = isinstance(mems, list) and len(mems) >= 2 and all(isinstance(m, str) for m in mems)
    import re
    noise = [w for w in ("obrigado", "perfeito", "oi")
             if re.search(rf"(?<![\wÀ-ÿ]){w}(?![\wÀ-ÿ])", " ".join(mems).lower(), re.I)] if ok else []
    print(f"\nmemórias extraídas ({len(mems) if ok else 0}):")
    for m in (mems or []):
        print(f"  • {m}")
    print(f"ruído detectado: {noise or 'nenhum'}")
    res["memories"] = mems
    res["ok"] = ok
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", default="http://127.0.0.1:18081/v1/chat/completions")
    ap.add_argument("--model", default="qwen3.8-flash-next-gyro-gyro-s")
    args = ap.parse_args()

    code = test_code(args.endpoint, args.model)
    mem = test_memory(args.endpoint, args.model)

    print("\n" + "=" * 70 + "\nRESUMO\n" + "=" * 70)
    print(f"  Geração de código: {'✅' if code['ok'] else '❌'}  {code['elapsed_s']} s")
    print(f"  Escrita de memória: {'✅' if mem['ok'] else '❌'}  {mem['elapsed_s']} s")
    all_ok = code["ok"] and mem["ok"]
    print(f"  RESULTADO: {'INTEGRAÇÃO OK' if all_ok else 'HÁ FALHAS'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
