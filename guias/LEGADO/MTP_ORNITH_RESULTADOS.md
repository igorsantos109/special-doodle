# MTP no Ornith-1.0-35B — Resultados da implementação

**Data:** 2026-10-22T21:58 UTC
**Build:** `/home/igor/opt/llama-cuda-official/` — llama.cpp oficial (commit `73bfe6c`)
**GGUF:** `ornith-1.0-35b-MTP-graft-Q4_K_M.gguf` (21 GB, arquitetura `qwen35moe`)

## MTP — Funcional e demonstrado ✅

O GGUF já contém a cabeça MTP integrada (`nextn_predict_layers: 1`, 753 tensores totais). Nenhum download ou enxerto foi necessário.

### Baseline (--spec-type none)
| Métrica | Valor |
|---|---|
| Prompt eval | 16.61 tok/s |
| Geração | 18.72 tok/s |
| VRAM | 19,285 MiB (18.8 GB) |
| Health | 200 ✅ |
| Código | Fibonacci correto ✅ |

### Com MTP (--spec-type draft-mtp, depth 2)
| Métrica | Valor |
|---|---|
| Prompt eval | 24.47 tok/s |
| Geração | **24.70 tok/s** |
| Draft gerados | 23 |
| Draft aceitos | 17 |
| Taxa de aceitação | **74%** |
| MTP spec_type | `none,draft-mtp` ✅ |
| VRAM | 19,861 MiB (19.4 GB) |
| Ganho sobre baseline | **1.32x** |

### Otimização de profundidade
| Depth | Geração | Aceitação | Nota |
|---|---|---|---|
| 2 (default) | **24.70 tok/s** | 74% | ✅ Melhor |
| 3 | 21.08 tok/s | 55% | Chained não suportado |
| 5 | 15.97 tok/s | 33% | Pior que baseline |

### Cache de contexto
- Conversas sucessivas com `cache_prompt=true` funcionam (LCP similarity match)
- Prompt reutilizado corretamente entre requisições

### Logs de carregamento da cabeça MTP
```
using MTP draft depth 2 on CUDA
creating MTP draft context against the target model
speculative decoding enabled: draft-mtp
```

## Comparação com PrismML

| Backend | Geração | MTP | VRAM |
|---|---|---|---|
| PrismML GPU build | **40 tok/s** | ❌ (ignora nextn.*) | 19,425 MiB |
| llama.cpp oficial sem MTP | 18.72 tok/s | - | 19,285 MiB |
| **llama.cpp oficial com MTP** | **24.70 tok/s** | ✅ 74% acc | 19,861 MiB |

O PrismML GPU build é mais rápido mesmo sem MTP (40 tok/s vs 24.7 tok/s com MTP no oficial). Para usar MTP no Ornith, é necessário trocar o backend para o llama.cpp oficial, com uma perda de desempenho base.

## Recomendação

- **Manter PrismML** para o serviço Ornith atual (40 tok/s, serviço já funcional)
- **Usar llama.cpp oficial + MTP** como configuração experimental quando qualidade de código com MTP for prioridade
- Para integração no serviço: criar `ornith-mtp.service` alternativo apontando para o binário oficial

## Reversão

Nenhuma alteração permanente foi feita. O build está em diretório independente:
```bash
rm -rf /home/igor/opt/llama-cuda-official/
```

Bonsai restaurado como GPU primária (porta 8080, 8.427 MiB VRAM).