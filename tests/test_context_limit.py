"""Busca binária do limite de contexto de cada modelo CPU disponível."""
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


def try_ctx(port, n_chars, max_tokens=10, timeout=60):
    """Tenta enviar n_chars de 'x' e retorna (http_code, tempo, corpo_erro)."""
    payload = {
        "model": "test",
        "messages": [{"role": "user", "content": "x" * n_chars}],
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
            return resp.getcode(), time.perf_counter() - t0, None
    except urllib.error.HTTPError as e:
        corpo = e.read().decode("utf-8", errors="replace")[:200]
        return e.code, time.perf_counter() - t0, corpo
    except Exception as e:
        return None, time.perf_counter() - t0, str(e)[:200]


def find_limit(name, port, low=1000, high=200000):
    """Busca binária aproximada do limite de contexto (em caracteres)."""
    print(f"\n{'='*60}")
    print(f"Buscando limite de contexto: {name} (porta {port})")
    print(f"{'='*60}")

    # Primeiro testa se high funciona
    code, dt, err = try_ctx(port, high)
    print(f"  {high:>7,} chars -> HTTP {code} ({dt:.1f}s) {err or ''}")
    if code == 200:
        print(f"  -> {high:,} chars ainda cabe (limite acima disso)")
        return high

    # Busca binária entre low e high
    best_ok = low
    best_fail = high
    while best_fail - best_ok > 2000:
        mid = (best_ok + best_fail) // 2
        code, dt, err = try_ctx(port, mid, timeout=120)
        print(f"  {mid:>7,} chars -> HTTP {code} ({dt:.1f}s) {err or ''}")
        if code == 200:
            best_ok = mid
        else:
            best_fail = mid
        time.sleep(1)  # não sobrecarregar o modelo

    print(f"\n  LIMITE APROXIMADO: entre {best_ok:,} e {best_fail:,} chars")
    print(f"  (em tokens aproximados: {int(best_ok*0.75):,} a {int(best_fail*0.75):,} tokens)")
    return best_ok, best_fail


if __name__ == "__main__":
    for name, port in MODELS.items():
        try:
            find_limit(name, port)
        except Exception as e:
            print(f"\n{name}: ERRO {e}")
        time.sleep(2)
