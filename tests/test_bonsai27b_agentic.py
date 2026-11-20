#!/usr/bin/env python3
"""Bateria de testes de programação agêntica para bonsai-27b (192.168.1.184:8080).

Testa: tool calling, code gen, code review/debug, edição multi-arquivo,
instruções complexas e uso de contexto longo (até ~64k tokens).

Uso: python3 test_bonsai27b_agentic.py [--url http://192.168.1.184:8080]
"""
import argparse, json, time, sys, re
import urllib.request

URL_DEFAULT = "http://192.168.1.184:8080/v1/chat/completions"
MODEL = "bonsai"

def chat(messages, max_tokens=2048, temperature=0.2, tools=None, extra=None, no_think=False, timeout=600):
    body = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if no_think:
        # Qwen-style: desliga reasoning por request
        body["enable_thinking"] = False
        body["chat_template_kwargs"] = {"enable_thinking": False}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    if extra:
        body.update(extra)
    req = urllib.request.Request(
        URL_DEFAULT, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    # sem proxy
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    t0 = time.time()
    with opener.open(req, timeout=timeout) as r:
        d = json.loads(r.read().decode())
    dt = time.time() - t0
    msg = d["choices"][0]["message"]
    # modelo em reasoning mode: content pode vir vazio, usar reasoning_content como fallback
    content = msg.get("content") or ""
    reasoning = msg.get("reasoning_content") or ""
    # texto combinado para análisis: se content vazio, usa reasoning
    full_text = content if content.strip() else reasoning
    usage = d.get("usage", {})
    tps = (usage.get("completion_tokens", 0) / dt) if dt > 0 else 0
    timings = d.get("timings", {})
    if timings.get("predicted_per_second"):
        tps = timings["predicted_per_second"]
    return {
        "content": content, "reasoning": reasoning, "full_text": full_text,
        "tool_calls": msg.get("tool_calls"), "finish_reason": d["choices"][0].get("finish_reason"),
        "usage": usage, "tps": round(tps, 1), "wall_s": round(dt, 1),
    }

def check(name, ok, detail=""):
    status = "✅ PASS" if ok else "❌ FAIL"
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))
    return ok

# ---------- TESTES ----------

def t1_tool_calling():
    print("\n=== T1: Tool Calling (function calling) ===")
    tools = [{
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Obtém a temperatura atual de uma cidade",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "Nome da cidade"},
                    "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]}
                },
                "required": ["city"]
            }
        }
    }]
    r = chat([
        {"role": "system", "content": "Você é um assistente que usa ferramentas quando necessário."},
        {"role": "user", "content": "Qual a temperatura em São Paulo hoje? Use a ferramenta get_weather."}
    ], tools=tools, max_tokens=300)
    tc = r["tool_calls"]
    ok = bool(tc) and tc[0]["function"]["name"] == "get_weather"
    detail = ""
    if tc:
        try:
            args = json.loads(tc[0]["function"]["arguments"])
            detail = f"args={args}"
            ok = ok and "city" in args and "São Paulo" in args.get("city","")
        except Exception as e:
            ok = False; detail = f"parse fail: {e}"
    else:
        detail = f"sem tool_call. content={r['content'][:100]!r} reasoning_tail={r['reasoning'][-150:]!r}"
    return check("tool call get_weather com city=São Paulo", ok, detail), r

def t2_code_gen_python():
    print("\n=== T2: Geração de código Python (algoritmo) ===")
    r = chat([
        {"role": "user", "content": "Escreva uma função Python `quicksort(arr)` que ordene uma lista em ordem crescente, sem usar sorted(). Inclua um exemplo de uso no final. Responda SOMENTE com código dentro de bloco ```python."}
    ], max_tokens=800, temperature=0.0, no_think=True)
    code = r["full_text"]
    has_def = "def quicksort" in code
    has_block = "```python" in code
    # tenta extrair e executar
    executed = False
    m = re.search(r"```python\n(.*?)```", code, re.S)
    if m:
        src = m.group(1)
        try:
            ns = {}
            exec(src, ns)
            if "quicksort" in ns:
                res = ns["quicksort"]([5,3,8,1,9,2])
                executed = res == [1,2,3,5,8,9]
        except Exception as e:
            executed = f"erro: {e}"
    ok = has_def and has_block and executed is True
    return check("quicksort correto e executável", ok, f"def={has_def} exec={executed} tps={r['tps']}"), r

def t3_code_review_debug():
    print("\n=== T3: Code review / debug (encontrar bug) ===")
    buggy = '''```python
def media(valores):
    total = 0
    for v in valores:
        total += v
    return total / len(valores) - 1  # BUG: subtrai 1

print(media([10, 20, 30]))  # deveria dar 20
```'''
    r = chat([
        {"role": "user", "content": f"Analise este código e encontre o bug. Explique em 1 frase e mostre o código corrigido.\n{buggy}"}
    ], max_tokens=600, temperature=0.0, no_think=True)
    txt = r["full_text"]
    ok = ("- 1" in txt or "subtrai" in txt.lower() or "bug" in txt.lower()) and "total / len(valores)" in txt
    return check("identificou o bug (-1) e corrigiu", ok, f"tps={r['tps']} resp_tail={txt[-120:]!r}"), r

def t4_multi_file_edit():
    print("\n=== T4: Edição multi-arquivo (projeto pequeno) ===")
    r = chat([
        {"role": "user", "content": """Crie uma mini aplicação FastAPI com 2 arquivos:
1) `main.py` — app FastAPI com rota GET /ping que retorna {"ping": "pong"}
2) `test_main.py` — teste com TestClient que verifica /ping retorna 200 e {"ping":"pong"}
Responda no formato:
--- main.py ---
```python
...
```
--- test_main.py ---
```python
...
```"""}
    ], max_tokens=1200, temperature=0.0, no_think=True)
    txt = r["full_text"]
    has_main = "main.py" in txt and "FastAPI" in txt and "/ping" in txt
    has_test = "test_main.py" in txt and "TestClient" in txt
    ok = has_main and has_test
    return check("gerou main.py + test_main.py coerentes", ok, f"tps={r['tps']}"), r

def t5_complex_instructions():
    print("\n=== T5: Instruções complexas / formato estruturado ===")
    r = chat([
        {"role": "user", "content": """Liste 5 Vorteile (vantagens) de usar modelos locais em português, no formato JSON exato:
{"vantagens": [{"n": 1, "titulo": "...", "desc": "..."}, ...]}
Nada além do JSON."""}
    ], max_tokens=800, temperature=0.0, no_think=True)
    txt = r["full_text"]
    ok = False; detail = ""
    m = re.search(r"\{.*\}", txt, re.S)
    if m:
        try:
            d = json.loads(m.group(0))
            ok = len(d.get("vantagens", [])) == 5
            detail = f"{len(d.get('vantagens',[]))} itens"
        except Exception as e:
            detail = f"json fail: {e} raw={txt[:100]!r}"
    else:
        detail = f"sem JSON. raw={txt[:150]!r}"
    return check("JSON válido com 5 vantagens", ok, detail), r

def t6_long_context():
    print("\n=== T6: Contexto longo (~40k tokens) — 'agulha no palheiro' ===")
    # 1 token ≈ 4 chars. Queremos ~40k tokens ≈ 160k chars de filler.
    filler = ("Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 50 + "\n")  # ~3000 chars
    big = filler * 55  # ~165k chars ≈ ~41k tokens
    needle = "A SENTENCA SECRETA E: CODIGO_42_ACTIVADO"
    prompt = big + "\n" + needle + "\n" + big + "\nPERGUNTA: Qual e a sentenca secreta? Responda so ela."
    r = chat([{"role": "user", "content": prompt}], max_tokens=60, temperature=0.0, no_think=True, timeout=900)
    txt = r["full_text"].strip()
    ok = "CODIGO_42_ACTIVADO" in txt or "42" in txt
    pt = r["usage"].get("prompt_tokens", 0)
    return check("achou a agulha no meio de ~contexto longo", ok, f"prompt_tokens={pt} resp={txt[:80]!r} tps={r['tps']}"), r

def t7_json_mode_structured():
    print("\n=== T7: Saída JSON estrita (response_format) ===")
    r = chat([
        {"role": "user", "content": "Descreva o modelo 'bonsai' em JSON: {\"nome\": str, \"params\": str, \"uso\": str}. Só o JSON."}
    ], max_tokens=300, temperature=0.0, no_think=True,
       extra={"response_format": {"type": "json_object"}})
    txt = r["full_text"]
    ok = False; detail = ""
    try:
        # tenta achar JSON no texto
        m = re.search(r"\{.*\}", txt, re.S)
        d = json.loads(m.group(0)) if m else json.loads(txt)
        ok = all(k in d for k in ("nome", "params", "uso"))
        detail = f"chaves={list(d.keys())}"
    except Exception as e:
        detail = f"fail: {e} raw={txt[:120]!r}"
    return check("JSON com chaves nome/params/uso", ok, detail), r

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=URL_DEFAULT)
    ap.add_argument("--skip-long", action="store_true")
    args = ap.parse_args()
    globals()["URL_DEFAULT"] = args.url

    print(f"Testando bonsai-27b em {URL_DEFAULT}")
    # sanity
    try:
        r = chat([{"role":"user","content":"Diga apenas: SANE"}], max_tokens=30, temperature=0)
        print(f"Sanity: tps={r['tps']} wall={r['wall_s']}s finish={r['finish_reason']}")
    except Exception as e:
        print(f"❌ ERRO de conexão: {e}"); sys.exit(1)

    results = []
    results.append(t1_tool_calling())
    results.append(t2_code_gen_python())
    results.append(t3_code_review_debug())
    results.append(t4_multi_file_edit())
    results.append(t5_complex_instructions())
    results.append(t7_json_mode_structured())
    if not args.skip_long:
        results.append(t6_long_context())

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    print(f"\n{'='*50}\nRESULTADO: {passed}/{total} testes passaram\n{'='*50}")
    for i, (ok, r) in enumerate(results, 1):
        print(f"  T{i}: {'✅' if ok else '❌'} tps={r['tps']} wall={r['wall_s']}s comp_tokens={r['usage'].get('completion_tokens')}")
    sys.exit(0 if passed == total else 1)

if __name__ == "__main__":
    main()
