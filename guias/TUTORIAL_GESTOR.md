# Tutorial: Gestor de Modelos (pcsala models)

## Comandos rápidos

| Quer... | Comando |
|---|---|
| Listar modelos | `./pcsala models list` |
| Ver estado | `./pcsala models status <id>` |
| Ver saúde | `./pcsala models health <id>` |
| Trocar GPU | `./pcsala models switch <id>` |
| Iniciar CPU | `./pcsala models start <id>` |
| Parar | `./pcsala models stop <id>` |
| Ver VRAM | `./pcsala models vram` |
| Diagnóstico completo | `./pcsala health` |

## Modelos (2026-11-20)

### GPU (exclusivo — um por vez, grupo `gpu-slot-1`)

| Alias | Modelo | Porta | Engine | Quando usar |
|---|---|---|---|---|
| `qwen36-q4` | Qwen3.6-35B-A3B Q4_K + **CPU MoE offload** | 8098 | llama.cpp CUDA | **Programação agêntica GPU**, 55k ctx, testado 6/6 |
| `qwen36-q4-strata` | Qwen3.6-35B-A3B UD-Q4_K_XL **Strata** | 8098 | **Strata 0.1.55** | **GPU agêntica + YaRN 100k + CPU MoE offload auto + KV q4_0 + MTP**, 55 tok/s curto / 4.5 tok/s longo |
| `qwen36-q3` | Qwen3.6-35B-A3B Q3_K (primário) | 8096 | llama.cpp CUDA | Uso geral GPU, mais rápido (~35-40 tok/s) |
| `qwen38-gyro-s` | Qwen3.8-Flash-Next Gyro-S TQ1_0 | 8081 | Strata 0.1.55 | Visão/MTP, 32k ctx |
| `ttf-qwen38` | TTF Qwen3.8-27B ternário 1.58-bit | 8108 | ttf-home llama.cpp | Compressão extrema, 32k ctx |
| `bonsai-27b-gpu` | Bonsai 27B + MTP (PrismML) | 8080 | llama.cpp | Legado, 64k ctx |

### CPU (compartilhado — todos simultâneos)

| Alias | Modelo | Porta | Engine | Quando usar |
|---|---|---|---|---|
| `maple-pro` | Maple-Pro 20B-A1B **YARN 65k** | 8193 | llama.cpp | **Programação agêntica CPU rápido** (~14 tok/s), 65k ctx |
| `qwen3-30b-a3b-cpu` | Qwen3-30B-A3B MoE IQ4_K **YARN 65k** | 8109 | ik_llama.cpp | **Programação agêntica CPU pesado** (~7 tok/s), 65k ctx |
| `qwen3-1.7b-cpu` | Qwen3-1.7B Q4_K_M | 8103 | llama.cpp | Validador tool calls, 8k ctx |
| `qwen2.5-1.5b-cpu` | Qwen2.5-1.5B-Instruct | 8105 | llama.cpp | Compactador contexto, 32k ctx |
| `lfm2.5-1.2b-cpu` | LFM2.5-1.2B-Instruct | 8104 | llama.cpp | Fallback ultra-rápido, 32k ctx |
| `phi35-mini-cpu` | Phi-3.5-mini | 8106 | llama.cpp | Reasoning agent, 4k ctx, LAN liberada |
| `bonsai2-cpu` | Bonsai 9B CPU | 8090 | llama.cpp | Batch/triagem, 32k ctx |

## Trocar GPU (com guarda VRAM)

```bash
./pcsala models switch qwen36-q4        # Recomendado para agêntico (CPU MoE llama.cpp, 55k ctx)
./pcsala models switch qwen36-q4-strata # GPU agêntica + Strata 0.1.55 + YaRN 100k + KV q4_0 + MTP
./pcsala models switch qwen36-q3        # Primário, mais rápido (~35-40 tok/s, 55k ctx)
./pcsala models switch qwen38-gyro-s    # Strata (visão/MTP, 32k ctx)
./pcsala models switch ttf-qwen38       # Ternário 1.58-bit (32k ctx)
./pcsala models switch bonsai-27b-gpu   # PrismML (64k ctx)
```

## Iniciar/Parar CPU (independentes)

```bash
./pcsala models start maple-pro      # YARN 65k
./pcsala models start qwen3-30b-a3b-cpu # YARN 65k
./pcsala models stop qwen3-1.7b-cpu
```

## Diário sem guarda: `ia solo <alias>`

```bash
ia solo qwen36-q4        # GPU recomendada agêntica (llama.cpp CPU MoE)
ia solo qwen36-q4-strata # GPU agêntica + Strata 0.1.55 + YaRN 100k + KV q4_0 + MTP
ia solo qwen36-q3        # GPU primário (mais rápido ~35-40 tok/s)
ia solo gyro-s           # Strata (visão/MTP)
ia solo ttf-qwen38       # Ternário 1.58-bit
ia solo bonsai           # Bonsai 27B
```

## Dica

Use `./pcsala health` para diagnóstico completo do sistema.
Para o gestor `ia` (estado, liga/desliga, `doctor`): `guias/GUIA_DIDATICA_IA.md`.