"""Teste direto de contexto: 65k e 100k tokens para cada modelo CPU."""
import json
import time
import urllib.request
import urllib.error

MODELS = {
    "bonsai-9b-cpu":   8090,
    "qwen3-1.7b":      8103,
    "lfm2.5-1.2b":     8104,
    "maple-pro-20b":   8193,
}

BASE = "http://127.0.0.1"


def try_ctx(port, n_chars, max_tokens=20, timeout=180):
    payload = {
        "model": "test",
        "messages": [{"role": "user", "content": "x" * n_chars + "\n\nQuantas letras x acima? Responda só o número."}],
        "max_tokens": max_tokens,
        "temperature": 0.1,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}:{port}/v1/chat/completions",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            return resp.getcode(), time.perf_counter() - t0, body
    except urllib.error.HTTPError as e:
        corpo = e.read().decode("utf-8", errors="replace")[:300]
        return e.code, time.perf_counter() - t0, corpo.encode()
    except Exception as e:
        return None, time.perf_counter() - t0, str(e)[:300].encode()


# Tamanhos em caracteres (~0.75 tok/char para 'x')
sizes = {
    "65k_tokens":  int(65000 / 0.75),   # ~86666 chars
    "100k_tokens": int(100000 / 0.75),  # ~133333 chars
    "32k_tokens":  int(32000 / 0.75),   # ~42666 chars
    "16k_tokens":  int(16000 / 0.75),   # ~21333 chars
}

results = {}

for name, port in MODELS.items():
    print(f"\n{'='*60}")
    print(f"MODELO: {name} (porta {port})")
    print(f"{'='*60}")
    results[name] = {}
    for label, n_chars in sizes.items():
        code, dt, body = try_ctx(port, n_chars)
        n_tok_approx = int(n_chars * 0.75)
        ok = code == 200
        results[name][label] = {"code": code, "chars": n_chars, "toks": n_tok_approx, "tempo": dt, "ok": ok}
        status = "OK" if ok else f"HTTP {code}"
        print(f"  {label:15s} ({n_tok_approx:>6,} toks, {n_chars:>7,} chars): {status}  {dt:.1f}s")
        if not ok:
            print(f"    erro: {body[:200]}")
        time.sleep(2)

print("\n\n" + "="*60)
print("RESUMO LIMITE DE CONTEXTO")
print("="*60)
for name, data in results.items():
    print(f"\n{name}:")
    for label, r in data.items():
        print(f"  {label:15s} ({r['toks']:>6,} toks): {'OK' if r['ok'] else 'FALHA'} ({r['code']})")
