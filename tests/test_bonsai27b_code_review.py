#!/usr/bin/env python3
"""Teste de code review em arquivo real do projeto + geração de teste unitário.
Usa bonsai-27b (192.168.1.184:8080) com contexto grande (~64k).
"""
import json, time, sys, os, re
import urllib.request

URL = "http://192.168.1.184:8080/v1/chat/completions"
MODEL = "bonsai"

def chat(messages, max_tokens=3000, temperature=0.1, timeout=900):
    body = {"model": MODEL, "messages": messages, "max_tokens": max_tokens,
            "temperature": temperature, "enable_thinking": False}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    t0 = time.time()
    with opener.open(req, timeout=timeout) as r:
        d = json.loads(r.read().decode())
    dt = time.time()-t0
    msg = d["choices"][0]["message"]
    tps = d.get("timings",{}).get("predicted_per_second") or 0
    return {"content": msg.get("content") or "", "usage": d.get("usage",{}),
            "tps": round(tps,1), "wall_s": round(dt,1), "finish": d["choices"][0].get("finish_reason")}

SRC = "/home/igor/ia-sh/pc-sala-agent/src/pcsala_agent/execution_contract.py"

def main():
    with open(SRC) as f:
        code = f.read()
    print(f"Arquivo: {SRC} ({len(code)} chars, {code.count(chr(10))+1} linhas)")

    # 1) code review
    r1 = chat([
        {"role":"system","content":"Você é um revisor de código Python sênior. Seja direto."},
        {"role":"user","content": f"Analise este código Python e liste até 5 problemas reais (bugs, más práticas, edge cases). Se não houver problemas, diga 'SEM PROBLEMAS'.\n\n```python\n{code}\n```"}
    ], max_tokens=1500)
    print(f"\n=== CODE REVIEW (tps={r1['tps']} wall={r1['wall_s']}s) ===")
    print(r1["content"][:1500])

    # 2) gerar teste unitário para uma função do arquivo
    # pega a primeira função def
    m = re.search(r"def (\w+)\(", code)
    func = m.group(1) if m else "main"
    r2 = chat([
        {"role":"system","content":"Você gera testes unitários pytest em Python. Responda só com o código do teste."},
        {"role":"user","content": f"Dado este código:\n```python\n{code}\n```\nEscreva um arquivo de teste pytest `test_review.py` que importe e teste a função `{func}` com pelo menos 2 casos (happy path + edge case). Só o código dentro de ```python."}
    ], max_tokens=2000)
    print(f"\n=== TESTE GERADO (tps={r2['tps']} wall={r2['wall_s']}s) ===")
    m2 = re.search(r"```python\n(.*?)```", r2["content"], re.S)
    test_code = m2.group(1) if m2 else r2["content"]
    print(test_code[:1200])
    # salva e tenta rodar
    out = "/tmp/test_review_bonsai.py"
    with open(out, "w") as f:
        f.write(test_code)
    import subprocess
    rr = subprocess.run(["python3","-m","pytest",out,"-x","-q","--no-header","-p","no:cacheprovider"],
                        capture_output=True, text=True, timeout=60,
                        cwd="/home/igor/ia-sh/pc-sala-agent")
    print(f"\n=== PYTEST (exit={rr.returncode}) ===")
    print((rr.stdout+rr.stderr)[-800:])
    ok = rr.returncode == 0 or "passed" in rr.stdout
    print(f"\nVEREDICTO: {'✅ review + teste OK' if ok else '⚠️ teste nao passou (ver acima)'}")
    print(f"prompt_tokens review={r1['usage'].get('prompt_tokens')} | teste={r2['usage'].get('prompt_tokens')}")

if __name__ == "__main__":
    main()
