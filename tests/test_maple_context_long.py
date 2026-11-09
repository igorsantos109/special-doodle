"""Testes de contexto longo (65k e 100k tokens) em todos os modelos CPU disponíveis via túnel SSH.

Modelos testados (todos em 127.0.0.1 via túnel):
- bonsai-9b-cpu   : porta 8090
- qwen3-1.7b      : porta 8103
- lfm2.5-1.2b     : porta 8104
- maple-pro-20b   : porta 8193

Conteúdo: "agulha no palheiro" — insere uma frase única num texto repetitivo e pede
para o modelo recuperá-la, medindo se consegue encontrar a informação no meio de
65k e 100k tokens de contexto.
"""
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
NEEDLE = "A palavra-chave secreta é AZUL-9921."
NEEDLE_ANSWER = "AZUL-9921"


def build_context(num_paragraphs: int) -> str:
    """Gera texto repetitivo para encher contexto. Cada parágrafo ~100 tokens."""
    para = ("O processamento de linguagem natural avançou muito nos últimos anos. "
            "Modelos de linguagem grandes são capazes de entender contexto, gerar texto, "
            "responder perguntas e realizar tarefas complexas. ")
    return para * num_paragraphs


def count_approx_tokens(text: str) -> int:
    """Aproximação bruta: ~0.75 tokens por palavra para português/inglês misto."""
    return int(len(text.split()) * 1.33)


def chat(port, model_name, context, needle_pos, max_tokens=200, temperature=0.1):
    """Insere a agulha numa posição específica do contexto e envia."""
    full_text = context[:needle_pos] + "\n" + NEEDLE + "\n" + context[needle_pos:]
    prompt = (full_text +
              "\n\nPergunta: Qual é a palavra-chave secreta mencionada no texto acima? "
              "Responda apenas com a palavra-chave.")
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
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
        with urllib.request.urlopen(req, timeout=300) as resp:
            body = resp.read()
            http_code = resp.getcode()
    except urllib.error.HTTPError as e:
        body = e.read()
        http_code = e.code
        return http_code, None, time.perf_counter() - t0, str(e)[:200]
    except Exception as e:
        return None, None, time.perf_counter() - t0, str(e)[:200]
    return http_code, body, time.perf_counter() - t0, None


def parse(body):
    try:
        return json.loads(body)
    except Exception:
        return {"_raw": body.decode("utf-8", errors="replace")}


def test_model(name, port, ctx_tokens):
    """Testa um modelo com contexto de aproximadamente ctx_tokens."""
    # Gerar texto base suficiente
    para = ("O processamento de linguagem natural avançou muito nos últimos anos. "
            "Modelos de linguagem grandes são capazes de entender contexto, gerar texto, "
            "responder perguntas e realizar tarefas complexas. ")
    tokens_per_para = count_approx_tokens(para)
    n_paras = max(1, ctx_tokens // tokens_per_para)
    context = para * n_paras
    actual_prompt_tokens = count_approx_tokens(context + NEEDLE + " Pergunta")

    # Inserir agulha no meio (50%)
    mid = len(context) // 2
    http_code, body, dt, erro = chat(port, name, context, mid, max_tokens=100, temperature=0.1)

    print(f"\n{'='*60}")
    print(f"MODELO: {name} (porta {port}) | alvo ~{ctx_tokens}K tokens")
    print(f"{'='*60}")
    print(f"Prompt aprox. tokens: {actual_prompt_tokens}")
    print(f"HTTP: {http_code} | tempo: {dt:.2f}s | erro: {erro or 'nenhum'}")

    if body:
        data = parse(body)
        if "choices" in data:
            content = data["choices"][0].get("message", {}).get("content", "")
            finish = data["choices"][0].get("finish_reason", "")
            usage = data.get("usage", {})
            reasoning = data["choices"][0].get("message", {}).get("reasoning_content", "")
            print(f"finish_reason: {finish}")
            print(f"usage: prompt={usage.get('prompt_tokens')} completion={usage.get('completion_tokens')}")
            print(f"resposta: '{content.strip()}'")
            acertou = NEEDLE_ANSWER in content
            print(f"ACERTOU AGULHA: {acertou} (esperado: {NEEDLE_ANSWER})")
            if reasoning:
                print(f"reasoning_len: {len(reasoning)}")
            return {
                "model": name,
                "port": port,
                "target_tokens": ctx_tokens,
                "actual_prompt_tokens": actual_prompt_tokens,
                "http_code": http_code,
                "finish_reason": finish,
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "tempo": dt,
                "resposta": content.strip(),
            "acertou": acertou,
            "erro": None,
            }
        else:
            print(f"RAW: {str(data)[:300]}")
            return {"model": name, "port": port, "target_tokens": ctx_tokens, "erro": str(data)[:200]}
    else:
        return {"model": name, "port": port, "target_tokens": ctx_tokens, "erro": erro}


resultados = []

for name, port in MODELS.items():
    for ctx in [65000, 100000]:
        r = test_model(name, port, ctx)
        resultados.append(r)

print("\n\n" + "="*60)
print("RELATÓRIO CONTEXTO LONGO (65k e 100k)")
print("="*60)
for r in resultados:
    if "erro" in r and r["erro"] and "acertou" not in r:
        print(f"{r['model']:18s} {r['target_tokens']//1000:5d}K | ERRO: {r['erro']}")
    else:
        print(f"{r['model']:18s} {r['target_tokens']//1000:5d}K | HTTP={r.get('http_code','?')} "
              f"prompt={r.get('prompt_tokens','?')} comp={r.get('completion_tokens','?')} "
              f"t={r.get('tempo',0):.1f}s | acertou={r.get('acertou','?')} | '{r.get('resposta','')[:40]}'")
