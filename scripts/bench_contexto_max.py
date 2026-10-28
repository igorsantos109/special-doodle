#!/usr/bin/env python3
"""Teste de contexto alto (64K/131K/196K) no Ternary-Nemotron-3.5.

Serve para decidir se o contexto maximo (-c 262144) vale a pena: mede
prefill, geracao e VRAM em tres pontos altos e regista a degradacao.

Uso:
    ./pcsala models switch nemotron-3.5-30b-gpu
    python3 scripts/bench_contexto_max.py

Endpoint por omissao:
    PCSALA_ENDPOINT_NEMOTRON_TERNARY_V1

Resultado em 2026-10-28 (Tesla P40, -c 262144, fa=on, kv=q8_0):
    alvo   prompt_n  prefill_s  prefill_t/s  gen_t/s   vram(MiB)
    65536     66755       81.7        816.6     56.2       11253
   131072    133511      248.6        537.0     41.4       11253
   196608    200308      501.7        399.3     24.9       11253
    => 262144 extrap.: prefill ~13-15 min, geracao ~15-25 tok/s.
       VRAM constante (KV pre-alocado) -> memoria viavel; o limite e'
       tempo, nao memoria. Recomendado <=32K para uso interativo.
"""
import json
import os
import subprocess
import time
import urllib.request

BASE = os.environ.get("PCSALA_ENDPOINT_NEMOTRON_TERNARY_V1",
                      "http://127.0.0.1:8083")
BASE_TXT = ("A analise de sistemas distribuidos exige avaliar consistencia, "
            "particao, latencia e custo. Cada observacao registra um evento, "
            "uma causa provavel e uma mitigacao. ")


def post(path, payload, timeout=2400):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read()), time.time() - t0


def texto_para_tokens(alvo):
    bloco = BASE_TXT * ((alvo * 4 // len(BASE_TXT)) + 2)
    d, _ = post("/tokenize", {"content": bloco, "add_special": True})
    n = len(d.get("tokens", []))
    if n and n < alvo:
        extra = (alvo - n)
        bloco = bloco + " " + BASE_TXT * max(extra // 40, 0)
    return bloco


def vram():
    out = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used",
         "--format=csv,noheader,nounits"],
        capture_output=True, text=True).stdout.strip()
    return out.splitlines()[0] if out else "?"


def main():
    print("VRAM antes:", vram(), "MiB")
    print(f"{'alvo':>8} {'prompt_n':>9} {'prefill_s':>10} {'prefill_t/s':>12} "
          f"{'gen_t/s':>9} {'vram':>7}")
    for alvo in (65536, 131072, 196608):
        bloco = texto_para_tokens(alvo)
        d, _wall = post("/completion", {
            "prompt": bloco, "max_tokens": 48, "temperature": 0.0,
        })
        t = d.get("timings", {})
        print(f"{alvo:>8} {t.get('prompt_n',0):>9} "
              f"{t.get('prompt_ms',0)/1000:>10.1f} "
              f"{t.get('prompt_per_second',0):>12.1f} "
              f"{t.get('predicted_per_second',0):>9.1f} {vram():>7}")
        del d
    print("VRAM depois:", vram(), "MiB")


if __name__ == "__main__":
    main()