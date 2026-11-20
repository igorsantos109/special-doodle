#!/usr/bin/env python3
"""Teste de LOOP AGÊNTICO real no bonsai-27b: o modelo deve完成 uma tarefa de
programação em múltiplos passos usando tool calling (ler arquivo, editar, rodar teste).

Simula um agente de código estilo DSH/Cline: system prompt + ferramentas + loop até concluir.

Uso: python3 test_bonsai27b_agent_loop.py [--url http://192.168.1.184:8080/v1/chat/completions]
"""
import argparse, json, time, sys, re, subprocess, os
import urllib.request

URL = "http://192.168.1.184:8080/v1/chat/completions"
MODEL = "bonsai"
WORKDIR = "/tmp/bonsai-agent-loop"

def chat(messages, tools=None, max_tokens=1500, temperature=0.2, timeout=600):
    body = {"model": MODEL, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    # desliga thinking para respostas diretas de ação
    body["enable_thinking"] = False
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    t0 = time.time()
    with opener.open(req, timeout=timeout) as r:
        d = json.loads(r.read().decode())
    dt = time.time() - t0
    msg = d["choices"][0]["message"]
    usage = d.get("usage", {})
    tps = d.get("timings", {}).get("predicted_per_second") or (usage.get("completion_tokens",0)/dt if dt>0 else 0)
    return {
        "content": msg.get("content") or "",
        "reasoning": msg.get("reasoning_content") or "",
        "tool_calls": msg.get("tool_calls"),
        "finish_reason": d["choices"][0].get("finish_reason"),
        "usage": usage, "tps": round(tps,1), "wall_s": round(dt,1),
    }

# ---------- ferramentas disponíveis para o agente ----------
def tool_read_file(path):
    try:
        with open(os.path.join(WORKDIR, path)) as f:
            return f.read()
    except FileNotFoundError:
        return f"ERRO: arquivo {path} nao existe"

def tool_write_file(path, content):
    full = os.path.join(WORKDIR, path)
    os.makedirs(os.path.dirname(full) or WORKDIR, exist_ok=True)
    with open(full, "w") as f:
        f.write(content)
    return f"OK: {path} escrito ({len(content)} bytes)"

def tool_run_test(path):
    full = os.path.join(WORKDIR, path)
    try:
        r = subprocess.run(["python3", full], capture_output=True, text=True, timeout=30, cwd=WORKDIR)
        out = (r.stdout + r.stderr).strip()
        return f"exit={r.returncode}\n{out[:2000]}"
    except Exception as e:
        return f"ERRO ao rodar: {e}"

def tool_list_files():
    out = []
    for root, _, files in os.walk(WORKDIR):
        for fn in files:
            out.append(os.path.relpath(os.path.join(root, fn), WORKDIR))
    return "\n".join(out) or "(vazio)"

TOOLS = [
    {"type":"function","function":{"name":"read_file","description":"Le um arquivo do projeto","parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}}},
    {"type":"function","function":{"name":"write_file","description":"Escreve/cria um arquivo no projeto","parameters":{"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"}},"required":["path","content"]}}},
    {"type":"function","function":{"name":"run_test","description":"Roda um arquivo Python de teste e retorna a saída","parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}}},
    {"type":"function","function":{"name":"list_files","description":"Lista arquivos do projeto","parameters":{"type":"object","properties":{}}}},
]

def dispatch(tool_call):
    name = tool_call["function"]["name"]
    args = json.loads(tool_call["function"]["arguments"])
    if name == "read_file": return tool_read_file(args["path"])
    if name == "write_file": return tool_write_file(args["path"], args["content"])
    if name == "run_test": return tool_run_test(args["path"])
    if name == "list_files": return tool_list_files()
    return f"ferramenta desconhecida: {name}"

SYSTEM = """Você é um agente de programação. Você tem ferramentas: read_file, write_file, run_test, list_files.
Objetivo: criar um arquivo `calc.py` com funções soma(a,b), sub(a,b), mul(a,b), div(a,b) (div deve tratar divisão por zero retornando None),
e um arquivo `test_calc.py` que testa todas elas e imprime 'TODOS OS TESTES PASSARAM' se estiver tudo certo.
Trabalhe passo a passo: escreva calc.py, escreva test_calc.py, rode run_test em test_calc.py.
Se o teste falhar, corrija o código e rode de novo. Quando o teste passar, responda com a mensagem final 'TAREFA CONCLUIDA'."""

def main():
    global URL
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=URL)
    ap.add_argument("--max-steps", type=int, default=12)
    args = ap.parse_args()
    URL = args.url

    os.makedirs(WORKDIR, exist_ok=True)
    # limpa
    for f in os.listdir(WORKDIR):
        os.remove(os.path.join(WORKDIR, f))

    messages = [{"role":"system","content":SYSTEM},
                {"role":"user","content":"Comece agora. Liste os arquivos, crie calc.py e test_calc.py, e rode o teste até passar."}]

    print(f"🤖 Iniciando loop agêntico (max {args.max_steps} passos) em {URL}\n")
    t_start = time.time()
    done = False
    for step in range(1, args.max_steps+1):
        r = chat(messages, tools=TOOLS, max_tokens=1500)
        msg = {"role":"assistant","content":r["content"]}
        if r["tool_calls"]:
            msg["tool_calls"] = r["tool_calls"]
        messages.append(msg)
        print(f"--- passo {step}: tps={r['tps']} wall={r['wall_s']}s finish={r['finish_reason']} comp={r['usage'].get('completion_tokens')}")
        if r["tool_calls"]:
            for tc in r["tool_calls"]:
                res = dispatch(tc)
                print(f"    🔧 {tc['function']['name']}({json.loads(tc['function']['arguments']).get('path','')}) -> {res[:120]!r}")
                messages.append({"role":"tool","tool_call_id":tc["id"],"name":tc["function"]["name"],"content":res})
        else:
            print(f"    💬 resposta final: {r['content'][:300]!r}")
            if "CONCLUIDA" in r["content"].upper() or "CONCLUÍDA" in r["content"].upper():
                done = True
            break

    # verificação final independente
    print("\n=== Verificação final ===")
    test_out = tool_run_test("test_calc.py")
    print(f"run_test(test_calc.py):\n{test_out}")
    ok = "TODOS OS TESTES PASSARAM" in test_out and done
    total_s = round(time.time()-t_start,1)
    print(f"\n{'='*50}\nVEREDICTO: {'✅ AGENTE CONCLUIU A TAREFA' if ok else '❌ NAO CONCLUIU'} em {total_s}s, {len(messages)} mensagens")
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
