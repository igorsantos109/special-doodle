"""Teste final de agulha no palheiro no contexto máximo de cada modelo CPU.

Modelos e seus contextos máximos verificados:
- maple-pro-20b: 32.768 tokens (-c 32768)
- qwen3-1.7b:    8.192 tokens
- lfm2.5-1.2b:   8.192 tokens
- bonsai-9b-cpu: 32.768 tokens (declarado, mas muito lento)

Insere a agulha no meio do contexto e verifica se o modelo a recupera.
"""
import json
import time
import urllib.request
import urllib.error

MODELS = {
    "maple-pro-20b":   {"port": 8193, "max_tok": 32768, "model_name": "maple-pro"},
    "qwen3-1.7b":      {"port": 8103, "max_tok": 8192,   "model_name": "qwen3-1.7b"},
    "lfm2.5-1.2b":     {"port": 8104, "max_tok": 8192,   "model_name": "lfm2.5-1.2b"},
}

NEEDLE = "A palavra-chave secreta é VERDE-4482."
NEEDLE_ANS = "VERDE-4482"

BASE = "http://127.0.0.1"


def try_needle(port, model_name, max_tok, timeout=240):
    # Gerar texto repetitivo para preencher até perto do limite
    para = ("O processamento de linguagem natural avançou muito nos últimos anos. "
            "Modelos grandes entendem contexto e geram texto. ")
    toks_per_para = len(para.split()) * 1.33
    n_paras = int(max_tok * 0.8 / toks_per_para)  # 80% do limite para caber agulha + resposta
    context = para * n_paras
    mid = len(context) // 2
    full = context[:mid] + "\n" + NEEDLE + "\n" + context[mid:]
    prompt = full + f"\n\nPergunta: Qual é a palavra-chave secreta? Responda apenas com ela."

    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 50,
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
            http_code = resp.getcode()
    except urllib.error.HTTPError as e:
        corpo = e.read().decode("utf-8", errors="replace")[:200]
        return http_code, None, time.perf_counter() - t0, corpo
    except Exception as e:
        return None, None, time.perf_counter() - t0, str(e)[:200]

    try:
        d = json.loads(body)
    except Exception:
        d = {"_raw": body.decode("utf-8", errors="replace")[:200]}

    if "choices" in d:
        c = d["choices"][0]
        content = c.get("message", {}).get("content", "")
        finish = c.get("finish_reason", "")
        usage = d.get("usage", {})
        reasoning = c.get("message", {}).get("reasoning_content", "")
        acertou = NEEDLE_ANS in content
        return http_code, {
            "finish_reason": finish,
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "resposta": content.strip(),
            "acertou": acertou,
            "reasoning_len": len(reasoning),
            "tempo": time.perf_counter() - t0,
        }, time.perf_counter() - t0, None
    else:
        return http_code, d, time.perf_counter() - t0, None


resultados = []

for name, cfg in MODELS.items():
    print(f"\n{'='*60}")
    print(f"MODELO: {name} (contexto máx {cfg['max_tok']:,} tokens)")
    print(f"{'='*60}")
    http_code, r, dt, erro = try_needle(cfg["port"], cfg["model_name"], cfg["max_tok"])
    print(f"HTTP: {http_code} | tempo total: {dt:.1f}s | erro: {erro or 'nenhum'}")
    if r:
        print(f"finish_reason: {r['finish_reason']}")
        print(f"prompt_tokens: {r['prompt_tokens']} | completion_tokens: {r['completion_tokens']}")
        print(f"resposta: '{r['resposta']}'")
        print(f"ACERTOU AGULHA ({NEEDLE_ANS}): {r['acertou']}")
        if r['reasoning_len']:
            print(f"reasoning_len: {r['reasoning_len']}")
    else:
        print(f"RAW/ERRO: {r}")
    resultados.append((name, cfg["max_tok"], http_code, r, dt, erro))

print("\n\n" + "="*60)
print("RELATÓRIO FINAL — AGULHA NO PALHEIRO (contexto máximo)")
print("="*60)
for name, max_tok, http_code, r, dt, erro in resultados:
    if r and isinstance(r, dict) and "acertou" in r:
        print(f"{name:18s} {max_tok:>7,} toks | HTTP={http_code} | acertou={r['acertou']} | "
              f"prompt={r['prompt_tokens']} | t={dt:.1f}s | '{r['resposta'][:30]}'")
    else:
        print(f"{name:18s} {max_tok:>7,} toks | HTTP={http_code} | FALHA: {erro or r}")
