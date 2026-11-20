#!/usr/bin/env python3
"""Bench de contexto longo — Maple-Pro (agulha no palheiro em N tokens).

Mede, por tamanho de prompt: tokens reais (/tokenize), TTFT (prefill), tok/s de
decode, finish_reason e se a agulha foi recuperada. Streaming (SSE).

Uso:
  python3 scripts/bench_maple_ctx.py --base http://127.0.0.1:8194 --targets 65536,131072,262144
"""

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request

NEEDLE = "NEEDLE_MAPLE_CTX_4417"
NEEDLE_VAL = "abacaxi-roxo"


def post(base, path, payload, timeout=3600):
    req = urllib.request.Request(
        base.rstrip("/") + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def count_tokens(base, text):
    try:
        return len(post(base, "/tokenize", {"content": text, "add_special": False}, timeout=300).get("tokens") or [])
    except Exception:
        return len(text) // 4


def build_prompt(base, target_tokens):
    """Bloco Python repetitivo; agulha a ~50% e pergunta no fim."""
    lines = []
    for i in range(120):
        lines.append(f"def calc_{i:03d}(a, b={i}):")
        lines.append(f"    return (a * {i % 9 + 1}) + b - {i}")
    block = "# BLOCO MODULO\n" + "\n".join(lines) + "\n"
    tok_bloco = max(1, count_tokens(base, block))
    n_mod = max(2, -(-target_tokens // tok_bloco))
    meio = n_mod // 2
    parts = []
    for n in range(n_mod):
        parts.append(f"# === modulo {n:05d} ===\n" + block)
        if n == meio:
            parts.append(f"# CONFIG_CRITICO: {NEEDLE} = \"{NEEDLE_VAL}\"\n")
    cabeca = (
        f"O texto abaixo contém {n_mod} módulos de código Python. No meio existe uma "
        f"linha de configuração com a chave {NEEDLE}.\n"
        "Responda APENAS com o valor associado a essa chave, sem explicações.\n\n"
    )
    prompt = cabeca + "".join(parts)
    real = count_tokens(base, prompt)
    # ajuste fino (passo de 1 módulo)
    for _ in range(8):
        if real < target_tokens * 0.97 and real + tok_bloco < 262144 - 2048:
            n_mod += 1
        elif real > target_tokens * 1.01 and n_mod > 3:
            n_mod -= 1
        else:
            break
        meio = n_mod // 2
        parts = []
        for n in range(n_mod):
            parts.append(f"# === modulo {n:05d} ===\n" + block)
            if n == meio:
                parts.append(f"# CONFIG_CRITICO: {NEEDLE} = \"{NEEDLE_VAL}\"\n")
        cabeca = (
            f"O texto abaixo contém {n_mod} módulos de código Python. No meio existe uma "
            f"linha de configuração com a chave {NEEDLE}.\n"
            "Responda APENAS com o valor associado a essa chave, sem explicações.\n\n"
        )
        prompt = cabeca + "".join(parts)
        real = count_tokens(base, prompt)
    return prompt, real


def run_stream(base, model, prompt, max_tokens=64):
    payload = {"model": model, "messages": [{"role": "user", "content": prompt}],
               "temperature": 0.2, "max_tokens": max_tokens, "stream": True}
    req = urllib.request.Request(
        base.rstrip("/") + "/v1/chat/completions", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.time()
    ttft, content, toks, finish, usage = None, "", 0, None, {}
    try:
        with urllib.request.urlopen(req, timeout=3600) as r:
            for raw in r:
                line = raw.decode().strip()
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    break
                try:
                    ch = json.loads(data)
                except json.JSONDecodeError:
                    continue
                d = (ch.get("choices") or [{}])[0]
                delta = d.get("delta") or {}
                # deepseek reasoning pode usar reasoning_content em vez de content
                rc = delta.get("reasoning_content") or ""
                ct = delta.get("content") or ""
                piece = rc + ct  # concatena ambos para capturar resposta completa
                if piece:
                    if ttft is None:
                        ttft = time.time() - t0
                    content += piece
                    toks += len(piece) // 5  # aprox tokens ≈ chars/5
                finish = d.get("finish_reason") or finish
                if ch.get("usage"):
                    usage = ch["usage"]
    except urllib.error.HTTPError as e:
        return {"http_error": e.code, "body": e.read().decode()[:300], "seconds": round(time.time() - t0, 1)}
    total = time.time() - t0
    dec = total - (ttft or 0)
    return {"content": content.strip(), "finish": finish,
            "prompt_tokens": usage.get("prompt_tokens"),
            "ttft_s": round(ttft, 1) if ttft else None,
            "decode_tps": round(toks / dec, 2) if dec > 0 and toks else None,
            "total_s": round(total, 1),
            "reasoning_len": len(content) - len(ct),
            "content_only_len": len(ct)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8194")
    ap.add_argument("--targets", default="65536,131072,196608,262144")
    ap.add_argument("--out", default="/tmp/kilo/maple_ctx_results.jsonl")
    args = ap.parse_args()

    # espera health (carga dos 6,2 GB + KV pode levar minutos)
    t0 = time.time()
    while time.time() - t0 < 1800:
        try:
            with urllib.request.urlopen(args.base + "/health", timeout=10) as r:
                if r.status == 200:
                    break
        except Exception:
            time.sleep(10)
    else:
        print("FALHA: health não respondeu em 30 min", file=sys.stderr)
        sys.exit(1)
    with urllib.request.urlopen(args.base + "/v1/models", timeout=30) as r:
        model = ((json.loads(r.read().decode()).get("data") or [{}])[0]).get("id")
    print(f"model: {model}\n", flush=True)

    for target in [int(x) for x in args.targets.split(",")]:
        print(f"=== alvo {target} tokens ===", flush=True)
        prompt, real = build_prompt(args.base, target)
        print(f"prompt construido: {real} tokens, {len(prompt)} chars", flush=True)
        res = run_stream(args.base, model, prompt)
        res.update({"target": target, "prompt_tokens_built": real, "ts": time.time()})
        ok = NEEDLE_VAL in (res.get("content") or "")
        res["agulha_ok"] = ok
        with open(args.out, "a") as f:
            f.write(json.dumps(res, ensure_ascii=False) + "\n")
        print(f"  prompt_tokens={res.get('prompt_tokens')} ttft={res.get('ttft_s')}s "
              f"decode={res.get('decode_tps')} tok/s total={res.get('total_s')}s "
              f"finish={res.get('finish')} agulha={'OK' if ok else 'FALHOU'} "
              f"http={res.get('http_error')} {res.get('erro','')}\n"
              f"  resposta: {(res.get('content') or '')[:80]!r}", flush=True)


if __name__ == "__main__":
    main()
