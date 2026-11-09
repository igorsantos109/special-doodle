"""Rodada 2 de testes agenticos profundos — Maple-Pro 20B CPU (via túnel SSH 18193 -> 8193)."""
import json
import time
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:18193"
MODEL = "maple-pro"


def chat(prompt, max_tokens=512, temperature=0.7, stream=False):
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": stream,
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
        with urllib.request.urlopen(req, timeout=180) as resp:
            body = resp.read()
            http_code = resp.getcode()
    except urllib.error.HTTPError as e:
        body = e.read()
        http_code = e.code
    dt = time.perf_counter() - t0
    return http_code, body, dt


def parse(body):
    try:
        return json.loads(body)
    except Exception:
        return {"_raw": body.decode("utf-8", errors="replace")}


def run(name, prompt, max_tokens=512, temperature=0.7):
    print(f"\n{'='*70}")
    print(f"TESTE R2: {name}")
    print(f"{'='*70}")
    http_code, body, dt = chat(prompt, max_tokens=max_tokens, temperature=temperature)
    data = parse(body)
    print(f"HTTP: {http_code} | tempo total: {dt:.2f}s")
    if "choices" in data:
        c = data["choices"][0]
        msg = c.get("message", {})
        content = msg.get("content", "")
        reasoning = msg.get("reasoning_content", "")
        finish = c.get("finish_reason", "")
        usage = data.get("usage", {})
        timings = data.get("timings", {})
        print(f"finish_reason: {finish}")
        if reasoning:
            print(f"\n--- REASONING ---\n{reasoning[:600]}")
        print(f"\n--- RESPOSTA ---\n{content[:1000]}")
        print(f"\n--- USO --- prompt={usage.get('prompt_tokens')} completion={usage.get('completion_tokens')} total={usage.get('total_tokens')}")
        if timings:
            print(f"--- TIMINGS --- pred_per_s={timings.get('predicted_per_second')}")
    else:
        print(f"RAW: {str(data)[:1200]}")
    return data, dt


results = []

# --- Raciocínio em cadeia complexo ---
d, t = run("Chain of Thought: lógica de cavaleiros e knaves",
    "Três habitantes A, B e C. A diz: 'B é um knave'. B diz: 'A e C são do mesmo tipo'. C diz: 'Eu sou um cavaleiro'. Cavaleiros sempre dizem a verdade, knaves sempre mentem. Quem é cavaleiro e quem é knave? Mostre o raciocínio passo a passo.",
    max_tokens=500, temperature=0.3)
results.append(("cavaleiros_knaves", d, t))

# --- Instruções complexas de formatação ---
d, t = run("Seguir formato rígido (saída estruturada)",
    "Liste as 5 maiores economias do mundo em 2024. Responda APENAS com este formato exato, uma por linha, sem texto adicional:\n1. Nome — PIB (trilhões USD)\nNão adicione introdução, não adicione conclusão, apenas as 5 linhas.",
    max_tokens=200, temperature=0.1)
results.append(("formato_rigido", d, t))

# --- Contexto longo com agulha no palheiro ---
texto_base = "A capital da França é Paris. " * 200
d, t = run("Agulha no palheiro (contexto longo)",
    f"{texto_base}\n\nPergunta: Qual é a capital da França? Responda com apenas uma palavra.",
    max_tokens=100, temperature=0.1)
results.append(("agulha_palheiro", d, t))

# --- Consistência: mesma pergunta 3 vezes ---
respostas = []
for i in range(3):
    _, body, _ = chat("Qual é 17 vezes 23? Responda apenas com o número.", max_tokens=20, temperature=0.7)
    data = parse(body)
    if "choices" in data:
        respostas.append(data["choices"][0].get("message", {}).get("content", "").strip())
    else:
        respostas.append("ERRO")
consistente = len(set(respostas)) == 1
print(f"\n{'='*70}")
print(f"TESTE R2: Consistência (3x mesma pergunta)")
print(f"{'='*70}")
print(f"Respostas: {respostas}")
print(f"Consistente: {consistente}")
results.append(("consistencia", None, None))

# --- Raciocínio espacial ---
d, t = run("Raciocínio espacial",
    "Tenho uma caixa vermelha dentro de uma caixa azul. A caixa azul está dentro de uma caixa verde. Onde está a caixa vermelha em relação à caixa verde? Explique brevemente.",
    max_tokens=150, temperature=0.3)
results.append(("espacial", d, t))

print("\n\n" + "="*70)
print("RELATÓRIO RESUMIDO — RODADA 2")
print("="*70)
for nome, d, t in results:
    if d is None:
        print(f"{nome:25s} | consistencia={t}")
        continue
    if "choices" in d:
        c = d["choices"][0]
        finish = c.get("finish_reason", "")
        usage = d.get("usage", {})
        timings = d.get("timings", {})
        tok_s = timings.get("predicted_per_second", "n/a")
        print(f"{nome:25s} | finish={finish:10s} | tok/s={tok_s} | total_t={usage.get('total_tokens','?')}t | tempo={t:.2f}s")
    else:
        print(f"{nome:25s} | ERRO: {str(d)[:80]}")
