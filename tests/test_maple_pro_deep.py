"""Testes agenticos profundos no Maple-Pro 20B CPU via SSH túnel (porta 18193 -> 8193 remota)."""
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
        with urllib.request.urlopen(req, timeout=120) as resp:
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
    print(f"TESTE: {name}")
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
            print(f"\n--- REASONING ---\n{reasoning[:800]}")
        print(f"\n--- RESPOSTA ---\n{content[:1200]}")
        print(f"\n--- USO --- prompt={usage.get('prompt_tokens')} completion={usage.get('completion_tokens')} total={usage.get('total_tokens')}")
        if timings:
            print(f"--- TIMINGS --- prompt_ms={timings.get('prompt_ms')} pred_ms={timings.get('predicted_ms')} pred_per_s={timings.get('predicted_per_second')} tok/s_pred={1000.0/timings.get('predicted_per_token_ms',1) if timings.get('predicted_per_token_ms') else 'n/a'}")
    else:
        print(f"RAW: {str(data)[:1500]}")
    return data, dt


results = []

# 1. Chat simples em português
d, t = run("Chat simples (pt-BR)", "Olá! Apresente-se brevemente em português e diga qual é sua versão e modelo.", max_tokens=200)
results.append(("chat_simples", d, t))

# 2. Raciocínio matemático
d, t = run("Raciocínio matemático", "Resolva passo a passo: Uma loja vende camisas por R$ 49,90 cada. Se você comprar 3 camisas com 15% de desconto no total, quanto paga? Mostre o raciocínio.", max_tokens=400, temperature=0.3)
results.append(("raciocínio_matemático", d, t))

# 3. Lógica / programa
d, t = run("Lógica de programação", "Escreva uma função Python que receba uma lista de números e retorne apenas os números primos, ordenados. Inclua docstring e um exemplo de uso.", max_tokens=400, temperature=0.3)
results.append(("funcao_primos", d, t))

# 4. Raciocínio agente (planejamento)
d, t = run("Planejamento agente", "Você é um agente de suporte. Um cliente diz: 'meu computador não liga'. Liste os 5 primeiros passos de diagnóstico em ordem, justificando cada um em uma linha.", max_tokens=300, temperature=0.5)
results.append(("planejamento_agente", d, t))

# 5. Tool calling (simulado via instrução)
d, t = run("Tool calling simulado", "Use a ferramenta get_weather(cidade) para consultar o clima de São Paulo e depois a ferramenta calculate(operacao) para somar 10 + 25. Responda apenas com as chamadas de ferramenta no formato JSON.", max_tokens=200, temperature=0.1)
results.append(("tool_calling", d, t))

# 6. Contexto longo / resumo
d, t = run("Resumo de texto longo", "Resuma em 3 bullets em português o seguinte texto: " + ("O processamento de linguagem natural avançou muito nos últimos anos. " * 40), max_tokens=250, temperature=0.3)
results.append(("resumo_texto", d, t))

print("\n\n" + "="*70)
print("RELATÓRIO RESUMIDO")
print("="*70)
for nome, d, t in results:
    if "choices" in d:
        c = d["choices"][0]
        msg = c.get("message", {})
        finish = c.get("finish_reason", "")
        usage = d.get("usage", {})
        timings = d.get("timings", {})
        tok_s = timings.get("predicted_per_second", "n/a")
        print(f"{nome:25s} | HTTP={d.get('http_code','?')} | finish={finish:10s} | tok/s={tok_s} | total_t={usage.get('total_tokens','?')}t | tempo={t:.2f}s")
    else:
        print(f"{nome:25s} | ERRO: {str(d)[:80]}")
