# Diagnóstico — Laguna XS 2.1 + Ornith 35B na P40

**Data:** 22/10/2026 · **Resultado:** ambos validados na P40 ✅

## Resultados

### Laguna XS 2.1 APEX I-Compact (15 GB)
- Full offload `-ngl 40` na P40: ✅
- VRAM: 15.881 MiB (16K ctx) → 21.223 MiB (150K ctx)
- Contexto: **150K tokens** · Prompt eval: 55-70 tok/s · Geração: **40-47 tok/s**
- Serviço: `laguna-gpu.service` (8082, disabled)

### Ornith 35B Q4_K_M (21 GB)
- Full offload `-ngl 40` na P40: ✅
- VRAM: ~19.425 MiB · Prompt eval: ~54 tok/s · Geração: **~40 tok/s** (PrismML)
- MTP no llama.cpp oficial: 24,7 tok/s, 74% aceitação, depth 2
- Serviço: `ornith.service` (8092, disabled)

## Ambiente

- Tesla P40 23.040 MiB, driver 580.178.04, CUDA 12.4.131
- Xeon E5-2697 v4 36T, 30 GiB RAM, 8 GiB swap
- Rede: 192.168.1.150/24 (enp6s0)

## Serviços

| Serviço | Porta | Modelo | Estado |
|---|---|---|---|
| `bonsai2-27b.service` | 8080 | Bonsai 27B GPU + MTP | active |
| `bonsai2-cpu.service` | 8090 | Bonsai 9B CPU | active |
| `laguna.service` | 8091 | Laguna XS 2.1 CPU | disabled |
| `laguna-gpu.service` | 8082 | Laguna XS 2.1 GPU | disabled |
| `ornith.service` | 8092 | Ornith 35B GPU | disabled |
| `pcsala-worker.service` | — | Worker LangGraph | active |

## Pesos em disco

| Modelo | Caminho | Tamanho |
|---|---|---|
| Bonsai 27B | `…/bonsai-2-27b/Ternary-Bonsai-2-27B-PQ2_0.gguf` | 6,8 GB |
| Drafter MTP | `…/bonsai-2-27b/mtp-bonsai2-native-v5b-dv64k.gguf` | ~1 GB |
| Bonsai 9B | `…/ternary-bonsai-2-9b-cpu/` | 2,4 GB |
| Laguna XS 2.1 | `…/laguna-xs-2-1/Laguna-XS-2.1-APEX-I-Compact.gguf` | 15 GB |
| Ornith | `…/ornith/ornith-1.0-35b-MTP-graft-Q4_K_M.gguf` | 21 GB |

## Binários

| Build | Localização | GPU |
|---|---|---|
| Pascal (MTP) | `prism-pascal-build/build/bin/llama-server` | ✅ CUDA 6.1 |
| CPU | `prism-cpu-install-aswyUW/install/bin/llama-server` | CPU |
| GPU original | `prism-gpu-build/install/bin/llama-server` | quebrado |

## Orçamento de VRAM (Laguna)

| Componente | APEX I-Compact |
|---|---|
| Pesos (15 GB GGUF) | ~15,8 GB |
| Cache KV (16K ctx) | ~2,5 GB |
| Buffers | ~500 MB |
| **Total** | **~18,8 GB** |

Cabe na P40 (23 GB) com `-ngl 40`. Com Bonsai a usar ~12,4 GB, GPU é exclusiva.

## Riscos

| Risco | Probabilidade | Mitigação |
|---|---|---|
| I-Compact não cabe na P40 | Baixa (validado) | `-ngl` entre 10-30 layers |
| Ornith não cabe na P40 | Baixa (validado) | Priorizar Laguna |
| Pascal crasha com Laguna | Baixa | Testar com `-c 4096` |