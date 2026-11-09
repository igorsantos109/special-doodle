"""Rodada 3 — teste de carga concorrente no Maple-Pro 20B CPU (via túnel SSH 18193)."""
import json
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = "http://127.0.0.1:18193"
MODEL = "maple-pro"


def chat(idx, prompt, max_tokens=300, temperature=0.7):
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/v1/chat/completions",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            body = resp.read()
            http_code = resp.getcode()
    except urllib.error.HTTPError as e:
        body = e.read()
        http_code = e.code
    except Exception as e:
        return idx, None, time.perf_counter() - t0, str(e)
    dt = time.perf_counter() - t0
    return idx, body, dt, None


def parse(body):
    try:
        return json.loads(body)
    except Exception:
        return {"_raw": body.decode("utf-8", errors="replace")}


prompts = [
    "Responda em português: qual é a capital do Brasil? Apenas uma palavra.",
    "Qual é 25 vezes 4? Responda apenas com o número.",
    "Diga 'Olá mundo' em português.",
    "Quantos planetas tem o sistema solar? Responda com um número.",
    "Complete: O sol nasce no ___",
]

print(f"Iniciando {len(prompts)} requisições concorrentes no Maple-Pro (CPU)...")
t_inicio = time.perf_counter()

resultados = []
with ThreadPoolExecutor(max_workers=len(prompts)) as pool:
    futuros = {pool.submit(chat, i, p): i for i, p in enumerate(prompts)}
    for futuro in as_completed(futuros):
        idx, body, dt, erro = futuro.result()
        if erro:
            print(f"  [{idx}] ERRO: {erro} em {dt:.2f}s")
            resultados.append((idx, None, dt, erro))
        else:
            data = parse(body)
            content = ""
            if "choices" in data:
                content = data["choices"][0].get("message", {}).get("content", "")
            finish = data.get("choices", [{}])[0].get("finish_reason", "") if "choices" in data else ""
            usage = data.get("usage", {})
            print(f"  [{idx}] HTTP={data.get('http_code','?')} finish={finish} tok={usage.get('total_tokens','?')} tempo={dt:.2f}s resp='{content[:60]}'")
            resultados.append((idx, data, dt, None))

t_total = time.perf_counter() - t_inicio
sucessos = sum(1 for _, _, _, e in resultados if e is None)
print(f"\n{'='*60}")
print(f"RESULTADO CARGA CONCORRENTE ({len(prompts)} requisições paralelas)")
print(f"{'='*60}")
print(f"Sucessos: {sucessos}/{len(prompts)}")
print(f"Tempo total (makespan): {t_total:.2f}s")
print(f"Throughput agregado: {len(prompts)/t_total:.2f} req/s")
tempos = [dt for _, _, dt, _ in resultados if dt is not None]
if tempos:
    print(f"Tempo médio por requisição: {sum(tempos)/len(tempos):.2f}s")
    print(f"Tempo min/max: {min(tempos):.2f}s / {max(tempos):.2f}s")
