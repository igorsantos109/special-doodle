#!/usr/bin/env python3
"""Benchmark do Ternary-Nemotron-3.5-Lightning-30B-A3B (Q2_0) em 8083.

Mede tk/s de geracao e prefill no endpoint do proprio `nemotron.service`
(caminho `/v1/chat/completions`, o mesmo que a producao usa).

Uso:
    ./pcsala models switch nemotron-3.5-30b-gpu
    python3 scripts/bench_nemotron.py            # tarefas medias
    python3 scripts/bench_nemotron.py escala     # prefill 2K..32K
    python3 scripts/bench_nemotron.py tokens     # conta tokens

Endpoint por omissao (sobrepondo igual aos perfis):
    PCSALA_ENDPOINT_NEMOTRON_TERNARY_V1

Baseline medido em Tesla P40 (sm_61, CUDA 12.4), -c 262144 -fa on
--cache-type-k/v q8_0, 2026-10-28:
    contexto   8K    16K    32K    66K   134K   200K
    geracao  90.8   85.1   73.3   56.2   41.4   24.9 tok/s
    prefill 1454   1315   1098    817    537    399 tok/s
    prefill 5.6s  12.4s  29.8s  81.7s 248.6s 501.7s
    VRAM constante 11253 MiB (KV de 262144 pre-alocado).
    Curto (~100 tok): geracao 100.2-100.8, prefill 322-391 tok/s.
    262144 extrap.: prefill ~13-15 min, geracao ~15-25 tok/s.
"""
import json
import os
import sys
import time
import urllib.request

BASE = os.environ.get("PCSALA_ENDPOINT_NEMOTRON_TERNARY_V1",
                      "http://127.0.0.1:8083")


def post(path, payload, timeout=1800):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read()), time.time() - t0


def tokenize(text, add_special=True):
    d, _ = post("/tokenize", {"content": text, "add_special": add_special})
    return d.get("tokens", [])


def completar(user, max_tokens=700, temperature=0.2, system=None,
              prompt=None):
    if prompt is not None:
        payload = {"prompt": prompt, "max_tokens": max_tokens,
                   "temperature": temperature, "top_p": 0.95}
        path = "/completion"
    else:
        payload = {
            "messages": ([{"role": "system", "content": system}]
                         if system else [])
            + [{"role": "user", "content": user}],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": 0.95,
        }
        path = "/v1/chat/completions"
    d, wall = post(path, payload)
    t = d.get("timings", {})
    txt = (d.get("content")
           or d.get("choices", [{}])[0].get("message", {}).get("content", ""))
    return txt, t, wall, d


def linha(nome, t, wall):
    pp = t.get("prompt_per_second")
    gg = t.get("predicted_per_second")
    pn = t.get("prompt_n", 0)
    gn = t.get("predicted_n", 0)
    print(f"  {nome}")
    print(f"    prompt : {pn:>6} tok em {t.get('prompt_ms',0)/1000:7.2f}s "
          f"-> {pp:>8.2f} tok/s")
    print(f"    geração: {gn:>6} tok em {t.get('predicted_ms',0)/1000:7.2f}s "
          f"-> {gg:>8.2f} tok/s")
    print(f"    total  : {wall:7.2f}s")


def medias():
    print("=== TAREFAS MÉDIAS COM RACIOCÍNIO ===")
    casos = [
        ("matemática multi-etapa",
         "Uma fábrica produz 3 tipos de peças. O tipo A custa 4 € e dá "
         "1 € de lucro; o tipo B custa 9 € e dá 2,5 €; o tipo C custa "
         "15 € e dá 5 €. O orçamento é de 1000 € e cada tipo exige pelo "
         "menos 10 peças. Maximiza o lucro e justifica cada restrição. "
         "Raciocina passo a passo."),
        ("lógica dedutiva",
         "Ana, Bruno, Clara e Diogo têm cores: vermelho, azul, verde, "
         "amarelo. Cada um tem uma cor. Ana não tem azul nem amarelo. "
         "Bruno tem vermelho e é irmão de Clara. Diogo tem verde. "
         "Clara não tem vermelho. Quem tem cada cor? Mostra o raciocínio "
         "passo a passo, eliminando hipóteses."),
        ("trade-off técnico",
         "Um serviço precisa de 99,95% de disponibilidade. Tendo em conta "
         "manutenção mensal de 30 min, cálculos de MTBF/MTTR e a escolha "
         "entre 1 ou 3 réplicas com failover, compara as duas opções "
         "quantitativamente e conclui qual escolher. Explica o "
         "raciocínio."),
    ]
    for nome, msg in casos:
        txt, t, wall, _ = completar(msg, max_tokens=700, temperature=0.2)
        linha(nome, t, wall)
        corpo = " ".join(txt.split())
        print(f"    resposta: {corpo[:140]}…")
        print()


def escala():
    """Prefill por tamanho de contexto; devolve a degradacao observada."""
    print("=== PREFILL POR CONTEXTO ===")
    base = ("Texto técnico de engenharia: o sistema processa um fluxo de "
            "eventos com prioridades, filas e janelas deslizantes. ")
    print(f"  {'alvo':>8} {'tokens':>8} {'prompt_s':>10} {'tok/s':>9}  "
          f"{'gen tok/s':>10}")
    resultados = []
    for alvo in (2048, 4096, 8192, 16384, 32768):
        bloco = (base * ((alvo * 4 // len(base)) + 1))
        toks = tokenize(bloco)
        while len(toks) < alvo:
            bloco += " " + base
            toks = tokenize(bloco)
        _, t, _wall, _ = completar(None, max_tokens=8, temperature=0,
                                   prompt=bloco)
        n = t.get("prompt_n", 0)
        pps = t.get("prompt_per_second", 0)
        gps = t.get("predicted_per_second", 0)
        resultados.append((n, pps, gps))
        print(f"  {alvo:>8} {n:>8} {t.get('prompt_ms',0)/1000:>10.2f} "
              f"{pps:>9.2f}  {gps:>10.2f}")
    total_t = sum(n / pps for n, pps, _ in resultados if pps)
    total_n = sum(n for n, pps, _ in resultados if pps)
    media = total_n / total_t if total_t else 0
    gg = [g for _, _, g in resultados if g]
    print()
    print(f"  prefill médio observado: {media:.1f} tok/s ({total_n} tok)")
    if media:
        print(f"  262144 tokens estimados: {262144/media/60:.1f} min")
    if gg:
        print(f"  geração média observada: {sum(gg)/len(gg):.1f} tok/s")


def tokens():
    t = "Raciocina passo a passo." * 20
    print(f"  tokens = {len(tokenize(t))}")


if __name__ == "__main__":
    modo = sys.argv[1] if len(sys.argv) > 1 else "medias"
    {"medias": medias, "escala": escala, "tokens": tokens}[modo]()