#!/usr/bin/env python3
"""Orquestrador: testa needle em 64K e ~230K com servidor reiniciado para cada -c.

Uso:
  python3 scripts/maple_ctx_orquestrador.py --port 8195
"""

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request

NEEDLE = "NEEDLE_MAPLE_CTX_4417"
NEEDLE_VAL = "abacaxi-roxo"
BIN = "/home/igor/opt/llama.cpp/build/bin/llama-server"
MODEL = "/mnt/arquivos/models/maple-preview/maple-pro.gguf"


def http_json(base, path, payload, timeout=3600):
    req = urllib.request.Request(
        base.rstrip("/") + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def count_tokens(base, text):
    try:
        return len(http_json(base, "/tokenize", {"content": text, "add_special": False}, timeout=300).get("tokens") or [])
    except Exception:
        return len(text) // 4


def build_prompt(base, target_tokens):
    """Prompt com agulha a ~50% e pergunta no fim; mede tokens via /tokenize."""
    lines = []
    for i in range(120):
        lines.append(f"def calc_{i:03d}(a, b={i}):")
        lines.append(f"    return (a * {i % 9 + 1}) + b - {i}")
    block = "# BLOCO MODULO\n" + "\n".join(lines) + "\n"
    tok_bloco = max(1, count_tokens(base, block))
    n_mod = max(2, -(-target_tokens // tok_bloco))
    print(f"  bloco={tok_bloco} tok, n_mod={n_mod}", flush=True)
    def rebuild(n):
        meio = n // 2
        parts = []
        for m in range(n):
            parts.append(f"# === modulo {m:05d} ===\n" + block)
            if m == meio:
                parts.append(f"# CONFIG_CRITICO: {NEEDLE} = \"{NEEDLE_VAL}\"\n")
        cab = (f"Texto com {n} módulos Python. No meio há a chave {NEEDLE}.\n"
               "Responda apenas o valor:\n\n")
        return cab + "".join(parts)
    prompt = rebuild(n_mod)
    real = count_tokens(base, prompt)
    for _ in range(12):
        if real < target_tokens * 0.97 and real + tok_bloco < 262000:
            n_mod += 1
        elif real > target_tokens * 1.01 and n_mod > 3:
            n_mod -= 1
        else:
            break
        prompt = rebuild(n_mod)
        real = count_tokens(base, prompt)
    return prompt, real


def chat(base, prompt, max_tokens=48, timeout=3600):
    t0 = time.time()
    try:
        d = http_json(base, "/v1/chat/completions", {
            "model": "t", "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2, "max_tokens": max_tokens}, timeout=timeout)
        dt = round(time.time() - t0, 1)
        c = d.get("choices", [{}])[0].get("message", {})
        content = (c.get("content") or "") or (c.get("reasoning_content") or "")
        t = d.get("timings", {})
        return {"content": content.strip(), "finish": d.get("choices", [{}])[0].get("finish_reason"),
                "prompt_tokens": d.get("usage", {}).get("prompt_tokens"),
                "pps": t.get("prompt_per_second"), "dps": t.get("predicted_per_second"),
                "total_s": dt, "reasoning_used": bool(c.get("reasoning_content"))}
    except urllib.error.HTTPError as e:
        return {"http_error": e.code, "body": e.read().decode()[:300], "total_s": round(time.time() - t0, 1)}
    except Exception as e:
        return {"error": str(e), "total_s": round(time.time() - t0, 1)}


def wait_health(base, timeout=900):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(base + "/health", timeout=10) as r:
                if r.status == 200:
                    return round(time.time() - t0, 1)
        except Exception:
            pass
        time.sleep(5)
    return None


def start_server(port, nctx):
    subprocess.run(["pkill", "-f", f"llama-server.*--port {port}"], capture_output=True)
    time.sleep(3)
    cmd = [BIN, "-m", MODEL, "--host", "127.0.0.1", "--port", str(port),
           "-c", str(nctx), "--threads", "20", "--threads-batch", "24",
           "-fa", "on", "-ngl", "0", "--no-kv-offload", "-n", "4096",
           "--parallel", "1", "--jinja", "--threads-http", "4"]
    logf = open(f"/tmp/kilo/maple_{port}_{nctx}.log", "w")
    p = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT, text=True)
    return p, logf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8195)
    ap.add_argument("--out", default="/tmp/kilo/maple_ctx_orq.json")
    args = ap.parse_args()
    base = f"http://127.0.0.1:{args.port}"
    results = []

    # (nctx_servidor, alvo_prompt_tokens, rótulo)
    testes = [
        (65536, 62000, "64K"),
        (262144, 240000, "240K"),
    ]

    for nctx, target, rotulo in testes:
        print(f"\n{'='*66}\n=== {rotulo}: servidor -c {nctx}, prompt alvo {target} tokens | {time.ctime()}\n", flush=True)
        proc, logf = start_server(args.port, nctx)
        t_ready = wait_health(base)
        print(f"servidor pronto em {t_ready}s", flush=True)
        if t_ready is None:
            proc.kill()
            results.append({"rotulo": rotulo, "erro": "startup timeout", "nctx": nctx})
            continue

        try:
            with urllib.request.urlopen(base + "/v1/models", timeout=30) as r:
                model = (json.loads(r.read().decode()).get("data") or [{}])[0].get("id", "?")
            print(f"model: {model}", flush=True)

            # sanity: pergunta simples
            s = chat(base, "Responda apenas: OK", max_tokens=8, timeout=300)
            print(f"sanity: {s.get('content','')[:40]!r} finish={s.get('finish')} "
                  f"pps={s.get('pps')} dps={s.get('dps')} ({s.get('total_s')}s)", flush=True)

            # build + needle
            t0 = time.time()
            prompt, real = build_prompt(base, target)
            print(f"prompt: {real} tokens, {len(prompt)} chars, build em {round(time.time()-t0,1)}s", flush=True)
            res = chat(base, prompt, max_tokens=32, timeout=7200)
            ok = NEEDLE_VAL in (res.get("content") or "")
            rec = {"rotulo": rotulo, "nctx": nctx, "prompt_built": real, **res, "agulha_ok": ok,
                   "ts": time.time()}
            results.append(rec)
            print(f"  prompt_tokens={res.get('prompt_tokens')} pps={res.get('pps')} dps={res.get('dps')} "
                  f"finish={res.get('finish')} total={res.get('total_s')}s "
                  f"agulha={'✅' if ok else '❌'} http={res.get('http_error')} "
                  f"err={res.get('error','')[:80]}", flush=True)
            print(f"  resposta: {(res.get('content') or '')[:100]!r}", flush=True)
            with open(args.out, "w") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=60)
            except Exception:
                proc.kill()
            logf.close()

    print(f"\n{json.dumps(results, ensure_ascii=False, indent=2)}")
    print(f"\nresultados: {args.out}")


if __name__ == "__main__":
    main()
