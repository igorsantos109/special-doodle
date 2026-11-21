#!/usr/bin/env python3
"""Benchmark do slot GPU (P40) — tok/s por tarefa e por contexto ate 100k.

Padrao dos scripts anteriores (bench_nemotron.py / bench_glm47flash_64k.py):
mesma recolha de `timings` do llama.cpp, mesma verificacao de truncamento
contra `/tokenize`, mesma fronteira HTTP 400, so que agora com modelos e
contextos parametrizaveis porque o slot `gpu-slot-1` troca de inquilino.

Uso:
    ./pcsala models switch flint-ternary-40b     # ou: ia solo flint-ternary
    python3 scripts/bench_gpu_slot.py flint tarefas
    python3 scripts/bench_gpu_slot.py flint escala
    python3 scripts/bench_gpu_slot.py flint ferramentas
    python3 scripts/bench_gpu_slot.py flint tudo            # tarefas+escala+ferramentas+needle

        
Endpoints (sobrepoe com --endpoint ou pela variavel do perfil):
    flint    -> PCSALA_ENDPOINT_FLINT_TERNARY_V1   (default http://127.0.0.1:8101)
    
Notas de capacidade (medicao 2026-11-08, Tesla P40 sm_61, 23 040 MiB):
    ver docs/expansao-gpu-2026-11.md — a guarda de VRAM do `pcsala models
    switch` exige folga >= 1 536 MiB com o Bonsai 4B residente na GPU.
"""
import argparse
import json
import os
import uuid
import subprocess
import sys
import time
import urllib.error
import urllib.request

MODELOS = {
    "flint": {
        "endpoint": os.environ.get("PCSALA_ENDPOINT_FLINT_TERNARY_V1",
                                   "http://127.0.0.1:8101"),
        "model_id": "flint-ternary-40b",
        "unit": "flint-ternary.service",
    },
            "endpoint": os.environ.get("PCSALA_ENDPOINT_FUSION4_AGENTIC_V1",
                                   "http://127.0.0.1:8102"),    },

CONTEXTOS = (4096, 8192, 16384, 32768, 65536, 100000)
NEEDLE = "The emergency codeword is Xylo9-Zurich."
NL = chr(10)
PERGUNTA = ("\n\nQuestion: What is the emergency codeword stated in the "
            "document? Answer with the codeword only.\nAnswer:")

TAREFAS = (
    ("matematica multi-etapa",
     "Uma fabrica produz 3 tipos de pecas. O tipo A custa 4 EUR e da 1 EUR de "
     "lucro; o tipo B custa 9 EUR e da 2,5 EUR; o tipo C custa 15 EUR e da 5 "
     "EUR. O orcamento e de 1000 EUR e cada tipo exige pelo menos 10 pecas. "
     "Maximiza o lucro e justifica cada restricao."),
    ("logica dedutiva",
     "Ana, Bruno, Clara e Diogo tem cores: vermelho, azul, verde, amarelo. Ana "
     "nao tem azul nem amarelo. Bruno tem vermelho e e irmao de Clara. Diogo "
     "tem verde. Clara nao tem vermelho. Quem tem cada cor? Elimina hipoteses."),
    ("geracao de codigo",
     "Escreve em Python uma funcao `merge_intervals(intervals)` que funde "
     "intervalos sobrepostos e uma `test_merge_intervals()` com 5 casos, "
     "incluindo lista vazia e intervalos adjacentes. So codigo."),
    ("depuracao",
     "Isto esta certo? `def f(xs): s = 0\n  for x in xs:\n   s += x\n return s/"
     "len(xs)` em Python 3 com xs=[]. Diz exactamente o que acontece e "
     "corrige."),
    ("resumo tecnico",
     "Explica em 6 frases porque um modelo MoE ternario de 1,58 bits corre mais "
     "depressas numa GPU de 24 GB do que um denso Q4_K_M de tamanho equivalente, "
     "mencionando largura de banda, experts activos e KV cache."),
)

FERRAMENTA = [{
    "type": "function",
    "function": {
        "name": "executar_comando",
        "description": "Executa um comando de shell e devolve a saida.",
        "parameters": {
            "type": "object",
            "properties": {
                "comando": {"type": "string",
                            "description": "comando de shell a executar"},
            },
            "required": ["comando"],
        },
    },
}]

RESULTADOS = {}

def post(base, path, obj, timeout=3600):
    req = urllib.request.Request(
        base + path, data=json.dumps(obj).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode()), time.time() - t0, None
    except urllib.error.HTTPError as e:
        return None, time.time() - t0, (e.code, e.read().decode(errors="replace")[:300])

def tokenize(base, text):
    d, _w, err = post(base, "/tokenize", {"content": text}, timeout=300)
    if err:
        raise RuntimeError(f"tokenize falhou: {err}")
    return d["tokens"]

def vram_usada_mb():
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10)
        return int(out.stdout.splitlines()[0].strip())
    except Exception:
        return None

def linha(nome, t, wall, extra=""):
    pp = t.get("prompt_per_second") or 0
    gg = t.get("predicted_per_second") or 0
    print(f"  {nome}")
    print(f"    prompt : {t.get('prompt_n', 0):>6} tok em "
          f"{(t.get('prompt_ms', 0) or 0)/1000:7.2f}s -> {pp:>8.2f} tok/s")
    print(f"    geracao: {t.get('predicted_n', 0):>6} tok em "
          f"{(t.get('predicted_ms', 0) or 0)/1000:7.2f}s -> {gg:>8.2f} tok/s")
    print(f"    total  : {wall:7.2f}s{extra}")

def chat(base, msg, max_tokens=512, temperature=0.2, tools=None):
    payload = {
        "messages": [{"role": "user", "content": msg}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    return post(base, "/v1/chat/completions", payload)

def tarefas(base):
    print("=== TAREFAS (tok/s por tarefa) ===", flush=True)
    registo = []
    for nome, msg in TAREFAS:
        d, wall, err = chat(base, msg, max_tokens=512)
        if err:
            print(f"  {nome}: FAIL HTTP {err[0]}: {err[1][:160]}", flush=True)
            registo.append({"tarefa": nome, "erro": err[0]})
            continue
        t = d.get("timings", {})
        corpo = " ".join((d.get("choices", [{}])[0].get("message", {})
                          .get("content") or "").split())
        linha(nome, t, wall)
        print(f"    resposta: {corpo[:140]}...", flush=True)
        registo.append({"tarefa": nome,
                        "prefill_tok_s": round(t.get("prompt_per_second") or 0, 2),
                        "decode_tok_s": round(t.get("predicted_per_second") or 0, 2),
                        "prompt_n": t.get("prompt_n"),
                        "predicted_n": t.get("predicted_n"),
                        "wall_s": round(wall, 2)})
        print(flush=True)
    RESULTADOS["tarefas"] = registo
    decode = [r["decode_tok_s"] for r in registo if r.get("decode_tok_s")]
    if decode:
        print(f"  media de geracao nas tarefas: {sum(decode)/len(decode):.2f} tok/s",
              flush=True)
    return 0

def n_ctx_servidor(base):
    props, err = get(base, "/props")
    if err or not props:
        return None
    return props.get("default_generation_settings", {}).get("n_ctx")

FRASE = ("Registo {i} do modulo {m}: janela deslizante {j}, fila {f}, "
         "verificacao {v} (selo {s}).\n")

def _frases(base, inicio, qtd, selo):
    return "".join(FRASE.format(i=i, m=i % 11, j=i % 97, f=i % 5,
                                v=(i * 7 % 13) + 1, s=selo)
                   for i in range(inicio, inicio + qtd))

def _custo_por_frase(base, selo):
    """Tokens por frase medidos numa amostra: evita tokenizar o corpo todo
    a cada frase (o construtor antigo era O(n^2) e dava horas a 100k)."""
    amostra = _frases(base, 0, 256, selo)
    return len(tokenize(base, amostra)) / 256.0

def prompt_contexto(base, alvo, custo=None, selo=None):
    """Contexto com ~`alvo` tokens, unico por execucao (frases numeradas).

    As frases numeradas matam o cache de prompt do servidor: com texto
    repetido, o prefill medido e o do bloco novo e sai inflacionado.
    """
    selo = selo or uuid.uuid4().hex[:10]
    custo = custo or _custo_por_frase(base, selo)
    qtd = max(1, int(alvo / custo))
    corpo = _frases(base, 0, qtd, selo)
    n = len(tokenize(base, corpo))
    for _ in range(4):
        if abs(n - alvo) <= max(32, 0.005 * alvo):
            break
        qtd = max(1, qtd + int((alvo - n) / custo))
        corpo = _frases(base, 0, qtd, selo)
        n = len(tokenize(base, corpo))
    return corpo, n

def escala(base, ctx_max=None, ctx_min=None, n_predict=32):
    print("=== ESCALA DE CONTEXTO (prefill e decode por tamanho) ===", flush=True)
    n_ctx = n_ctx_servidor(base)
    if n_ctx:
        print(f"  n_ctx do servidor: {n_ctx}", flush=True)
    alvo_max = ctx_max if ctx_max else max(CONTEXTOS)
    brutos = [c for c in CONTEXTOS if c <= alvo_max and c >= (ctx_min or 0)]
    if n_ctx:
        brutos.append(n_ctx - 1024)          # o ultimo degrau utilizavel do slot
    limites = sorted({min(c, n_ctx - 1024) if n_ctx else c
                      for c in brutos if (n_ctx is None or c > 512)})
    print(f"  {'alvo':>8} {'tokens':>8} {'prompt_s':>9} {'prefill':>9} "
          f"{'decode':>9} {'VRAM MiB':>9}", flush=True)
    linhas = []
    for alvo in limites:
        corpo, n = prompt_contexto(base, alvo)
        d, wall, err = post(base, "/completion", {
            "prompt": corpo, "n_predict": n_predict, "temperature": 0,
            "top_k": 1, "cache_prompt": False})
        if err:
            print(f"  {alvo:>8} {n:>8}  FAIL HTTP {err[0]}: {err[1][:120]}",
                  flush=True)
            linhas.append({"alvo": alvo, "tokens": n, "erro": err[0]})
            break
        t = d.get("timings", {})
        usado = vram_usada_mb()
        if not t.get("predicted_n"):
            print(f"  {alvo:>8} {n:>8}  sem tokens gerados (decode n/a)", flush=True)
        truncado = t.get("prompt_n") != n
        if truncado:
            print("    truncamento detectado — para aqui (o slot nao tem este "
                  "contexto)", flush=True)
            linhas.append({"alvo": alvo, "tokens": n, "erro": "truncado",
                           "prompt_n": t.get("prompt_n")})
            break
        print(f"  {alvo:>8} {n:>8} {(t.get('prompt_ms', 0) or 0)/1000:>9.2f} "
              f"{(t.get('prompt_per_second') or 0):>9.2f} "
              f"{(t.get('predicted_per_second') or 0):>9.2f} "
              f"{(usado if usado is not None else -1):>9}"
              + ("  TRUNCADO" if truncado else ""), flush=True)
        linhas.append({"alvo": alvo, "tokens": n,
                       "prompt_n": t.get("prompt_n"),
                       "n_ctx_servidor": n_ctx,
                       "prefill_tok_s": round(t.get("prompt_per_second") or 0, 2),
                       "decode_tok_s": round(t.get("predicted_per_second") or 0, 2),
                       "vram_used_mb": usado,
                       "truncado": truncado,
                       "wall_s": round(wall, 2)})
    RESULTADOS["escala"] = linhas
    bons = [l for l in linhas if not l.get("erro")]
    if bons:
        ultimo = bons[-1]
        print(f"\n  maior contexto servido sem truncamento: {ultimo['tokens']} tok "
              f"({ultimo['decode_tok_s']} tok/s decode, {ultimo['vram_used_mb']} MiB)",
              flush=True)
    return 0

def ferramentas(base, repeticoes=3):
    print("=== TOOL CALLING (--jinja) ===", flush=True)
    ok = 0
    tempos = []
    for i in range(repeticoes):
        d, wall, err = chat(
            base,
            "Corre `git status` no repositorio /srv/app e diz-me o resultado.",
            max_tokens=256, tools=FERRAMENTA)
        if err:
            print(f"  #{i+1}: FAIL HTTP {err[0]}: {err[1][:200]}", flush=True)
            continue
        msg = d.get("choices", [{}])[0].get("message", {})
        calls = msg.get("tool_calls") or []
        t = d.get("timings", {})
        if calls and calls[0].get("function", {}).get("name") == "executar_comando":
            argumentos = calls[0]["function"].get("arguments") or "{}"
            try:
                parsed = json.loads(argumentos)
            except json.JSONDecodeError:
                parsed = {}
            bom = "git status" in str(parsed.get("comando", ""))
            ok += bool(bom)
            tempos.append(t.get("predicted_per_second") or 0)
            print(f"  #{i+1}: OK finish={d.get('choices',[{}])[0].get('finish_reason')} "
                  f"args={argumentos[:120]} decode={t.get('predicted_per_second')} tok/s",
                  flush=True)
        else:
            print(f"  #{i+1}: SEM tool_calls; content="
                  f"{(msg.get('content') or '')[:120]!r}", flush=True)
    RESULTADOS["ferramentas"] = {"ok": ok, "total": repeticoes}
    print(f"  resultado: {ok}/{repeticoes} tool calls validos", flush=True)
    return 0 if ok == repeticoes else 1

def build_agulha(base, n_ctx):
    """Contexto com agulha a meio, dimensionado por estimativa (1-2 tokenizacoes)."""
    selo = uuid.uuid4().hex[:10]
    custo = _custo_por_frase(base, selo)
    corpo, n = prompt_contexto(base, n_ctx - 512, custo=custo, selo=selo)
    linhas = corpo.split("\n")
    meio = len(linhas) // 2
    linhas.insert(meio, "NOTA " + NEEDLE)
    corpo = NL.join(linhas)
    n = len(tokenize(base, corpo + PERGUNTA))
    if n > n_ctx - 256:                       # tira o excedente de uma vez
        sobra = int((n - (n_ctx - 256)) / custo)
        del linhas[-(sobra + 1):]
        corpo = NL.join(linhas)
        n = len(tokenize(base, corpo + PERGUNTA))
    return corpo + PERGUNTA, n

def agulha(base, n_ctx=None):
    print("=== AGULHA NO PALHEIRO + FRONTEIRA DO CONTEXTO ===", flush=True)
    if n_ctx is None:
        n_ctx = n_ctx_servidor(base) or 32768
        limites = [l for l in (RESULTADOS.get("escala") or []) if not l.get("erro")]
        if limites:
            n_ctx = min(n_ctx, max(l["tokens"] for l in limites) + 1024)
    prompt, n = build_agulha(base, n_ctx)
    print(f"  contexto testado: {n} tokens", flush=True)
    d, wall, err = post(base, "/completion", {
        "prompt": prompt, "n_predict": 64, "temperature": 0, "top_k": 1,
        "cache_prompt": False})
    if err:
        print(f"  FAIL HTTP {err[0]}: {err[1][:200]}", flush=True)
        RESULTADOS["agulha"] = {"tokens": n, "ok": False, "erro": err[0]}
        return 1
    t = d.get("timings", {})
    conteudo = d.get("content", "")
    exacta = "Xylo9-Zurich" in conteudo
    truncada = t.get("prompt_n") != n
    print(f"  prompt_n={t.get('prompt_n')} esperado={n} truncada={truncada}",
          flush=True)
    print(f"  prefill={t.get('prompt_per_second')} tok/s "
          f"decode={t.get('predicted_per_second')} tok/s", flush=True)
    print(f"  resposta={conteudo.strip()[:120]!r}", flush=True)
    # fronteira: um pedido acima do limite deve dar HTTP 400, nunca corte mudo
    excesso = tokenize(base, prompt + " extra " * 4000)
    _, _w2, err2 = post(base, "/completion",
                        {"prompt": " ".join(["fluxo"] * len(excesso)),
                         "n_predict": 8}, timeout=300)
    fronteira = bool(err2) and err2[0] == 400
    print(f"  fronteira acima do limite: {'PASS (HTTP 400)' if fronteira else 'FAIL'}",
          flush=True)
    ok = exacta and not truncada
    RESULTADOS["agulha"] = {"tokens": n, "ok": ok, "fronteira": fronteira,
                           "decode_tok_s": t.get("predicted_per_second")}
    print(f"  RESULTADO={'PASS' if ok else 'FAIL'}", flush=True)
    return 0 if ok else 1

def get(base, path, timeout=60):
    try:
        with urllib.request.urlopen(base + path, timeout=timeout) as r:
            return json.loads(r.read().decode()), None
    except urllib.error.HTTPError as e:
        return None, (e.code, e.read().decode(errors="replace")[:300])

def main():
    ap = argparse.ArgumentParser(description="bench do slot GPU (P40)")
    ap.add_argument("modelo", choices=sorted(MODELOS))
    ap.add_argument("modo", nargs="?", default="tudo",
                    choices=["tarefas", "escala", "ferramentas", "agulha", "tudo"])
    ap.add_argument("--endpoint", default=None)
    ap.add_argument("--ctx", type=int, default=None,
                    help="tecto de contexto a testar em `escala`")
    ap.add_argument("--de", type=int, default=None,
                    help="piso de contexto a testar em `escala` (so os degraus altos)")
    ap.add_argument("--json", default=None, help="gravar resultados em JSON")
    args = ap.parse_args()

    base = (args.endpoint or MODELOS[args.modelo]["endpoint"]).rstrip("/")
    print(f"# {args.modelo} ({MODELOS[args.modelo]['model_id']}) @ {base} "
          f"unit={MODELOS[args.modelo]['unit']}", flush=True)
    _d, err = get(base, "/health")
    print(f"# health: {'ok' if not err else err}", flush=True)
    props, _ = get(base, "/props")
    if props:
        print(f"# n_ctx servidor: {props.get('default_generation_settings', {}).get('n_ctx')}",
              flush=True)
    print(f"# VRAM usada antes do bench: {vram_usada_mb()} MiB", flush=True)
    RESULTADOS["modelo"] = MODELOS[args.modelo]["model_id"]
    RESULTADOS["endpoint"] = base

    rc = 0
    modos = (["tarefas", "escala", "ferramentas", "agulha"]
             if args.modo == "tudo" else [args.modo])
    for m in modos:
        r = {"tarefas": lambda: tarefas(base),
             "escala": lambda: escala(base, args.ctx, args.de),
             "ferramentas": lambda: ferramentas(base),
             "agulha": lambda: agulha(base)}[m]()
        rc = rc or r

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(RESULTADOS, f, indent=1, ensure_ascii=False)
        print(f"# resultados JSON: {args.json}", flush=True)
    return rc

if __name__ == "__main__":
    sys.exit(main())
