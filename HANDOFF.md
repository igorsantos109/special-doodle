# HANDOFF — PC-SALA Agent (Atualizado 2026-11-20)

## Objetivo
Gerenciar LLMs locais no PC-SALA (192.168.1.184): Tesla P40 (23 GB VRAM) + CPU (Xeon E5-2678v3, 24T), via `ia` manager + systemd + DSH providers.

---

## Estado Atual (2026-11-20 ~00:05 BRT)

### Modelos GPU (P40 — grupo exclusivo `gpu-slot-1`)
| Modelo | Porta | Engine | VRAM | Contexto | Status |
|--------|-------|--------|------|----------|--------|
| **qwen36-q4** | **8098** | llama.cpp CUDA + CPU MoE offload | ~21 GB | **55k** | ✅ **TESTADO: 6/6 agentic + loop + 45k ctx** |
| qwen36-q3 | 8096 | llama.cpp CUDA | ~16 GB | 55k | Parado (alternância) |
| qwen38-gyro-s | 8081 | Strata 0.1.55 | ~21 GB | 32k | Inativo (requer restart Strata) |
| ttf-qwen38-27b | 8108 | ttf-home llama.cpp | ~7.7 GB | 32k | Inativo |
| bonsai-27b | 8080 | llama.cpp | ~15 GB | 128k | Parado (liberado) |

> **Regra:** GPU exclusivo — `ia solo <modelo>` para alternar.

### Modelos CPU (ativos simultaneamente)
| Modelo | Porta | Engine | Contexto | RAM | Status |
|--------|-------|--------|----------|-----|--------|
| **maple-pro 20B-A1B** | **8193** | llama.cpp YARN x2 | **65k** | ~1.3 GB | ✅ TESTADO 5/5 agentic, ~14 tok/s |
| **qwen3-30b-a3b-moe-iq4k** | **8109** | ik_llama.cpp + YARN | **65k** | ~21 GB | ✅ TESTADO 5/5 agentic, ~7 tok/s |
| qwen3-1.7b | 8103 | llama.cpp | 8k | ~1.5 GB | Ativo (validador tools) |
| qwen2.5-1.5b | 8105 | llama.cpp | 32k | ~1.2 GB | Ativo |
| lfm2.5-1.2b | 8104 | llama.cpp | 32k | ~1 GB | Ativo (fallback) |
| phi35-mini | 8106 | llama.cpp | 4k | ~0.8 GB | Ativo (LAN liberada) |
| bonsai-9b-cpu | 8090 | llama.cpp | 32k | ~5 GB | Ativo |

---

## Resultados de Testes Agênticos (2026-11-20)

### qwen36-q4 GPU (8098) — **CPU MoE offload ativo** (`--cpu-moe`)
| Teste | Resultado | tps médio | Notas |
|-------|-----------|-----------|-------|
| T1 Tool Calling | ✅ PASS | 6.2 | get_weather city=São Paulo |
| T2 Code Gen (quicksort) | ✅ PASS | 5.6 | Executável |
| T3 Code Review (debug) | ✅ PASS | 5.2 | Bug -1 identificado |
| T4 Multi-file FastAPI | ✅ PASS | 6.1 | main.py + test_main.py |
| T5 JSON Estruturado | ✅ PASS | 4.7 | 5 vantagens válidas |
| T7 JSON Mode Strict | ✅ PASS | 5.6 | response_format |
| **Loop Agêntico (5 passos)** | ✅ **CONCLUÍDO** | ~5.5 | 141s, calc.py + test_calc.py |
| **Contexto Longo (~45k tokens)** | ✅ **PASS** | 2.1 | Needle in haystack 525s |

### maple-pro 20B-A1B CPU YARN (8193)
| Teste | Resultado | tps médio |
|-------|-----------|-----------|
| T1 Tool Calling | ✅ PASS | 13.8 |
| T2 Code Gen | ✅ PASS | 13.8 |
| T3 Code Review | ✅ PASS | 14.3 |
| T4 Multi-file | ✅ PASS | 14.4 |
| T5 JSON Estruturado | ✅ PASS | — |
| **Total** | **5/5** | **~14 tok/s** |

### qwen3-30b-a3b CPU YARN (8109)
| Teste | Resultado | tps médio |
|-------|-----------|-----------|
| T1 Tool Calling | ✅ PASS | 11.3 (sanity) / 7.3 |
| T2 Code Gen | ✅ PASS | 7.3 |
| T3 Code Review | ✅ PASS | 7.2 |
| T4 Multi-file | ✅ PASS | 7.2 |
| T5 JSON Estruturado | ✅ PASS | — |
| **Total** | **5/5** | **~7 tok/s** |

---

## Configuração DSH (DeepSeek Harness Web GUI — porta 3080)
- `~/.dsh/profiles/web/cordis.patch.yml` — providers: `ttf-qwen38` (8108), `gyro-s` (8081), `qwen3-30b-a3b` (8109, header `PCSALA_LOCAL_API_KEY`), `qwen36-q4` (8098), `maple-pro` (8193)
- `~/.dsh/.env` — `PCSALA_LOCAL_API_KEY=pcsala-open-no-auth`, `DSH_LOCAL_API_KEY=sk-strata-...`
- **Reinício GUI necessário:** `pnpm run dev:web`

---

## Serviços systemd Ativos
| Serviço | Porta | Estado | Notas |
|---------|-------|--------|-------|
| `qwen36-q4.service` | 8098 | **active** | GPU, CPU MoE offload, MTP |
| `qwen3-30b-a3b-cpu.service` | 8109 | **active** | CPU YARN 65k |
| `local-maple.service` | 8193 | **active** | CPU YARN 65k |
| `qwen3-1.7b-cpu.service` | 8103 | active | Validador tools |
| `qwen2.5-1.5b-cpu.service` | 8105 | active | |
| `lfm2.5-1.2b-cpu.service` | 8104 | active | |
| `phi35-mini-cpu.service` | 8106 | active | LAN 192.168.1.170 |
| `bonsai2-cpu.service` | 8090 | active | |
| `pcsala-worker.service` | — | active | Fila persistente LangGraph |

---

## Alterações Recentes (esta sessão)
1. **qwen36-q4**: Habilitado `--cpu-moe` (offload experts MoE para CPU/RAM) — libera VRAM, mantém performance
2. **qwen3-30b-a3b**: Ativado YARN (`--rope-scaling yarn --yarn-ext-factor 2.0 --yarn-orig-ctx 32768`) — contexto 32k → 65k
3. **Testes agênticos completos**: 3 modelos testados (GPU + 2 CPU) com suite de 5 testes + loop multi-step + contexto longo

---

## Próxima Ação Concreta
```bash
# Validar DSH providers
ssh igor@192.168.1.184 'curl -s http://127.0.0.1:8098/health && curl -s http://127.0.0.1:8109/health && curl -s http://127.0.0.1:8193/health'

# Reiniciar GUI DSH para ver novos providers
cd /home/igor/.npm-global/lib/node_modules/@deepseek-ai/dsh/apps/web && pnpm run dev:web
```

---

## Pendências / Bloqueios
| Item | Status |
|------|--------|
| Push `origin/fase-0` | **BLOQUEADO** — repos GitHub arquivados (403 read-only) |
| Gyro-S Strata restart com MCP | Pendente |
| Firewall LAN para 8098/8109 | Liberar no nft/ufw se necessário |
| qwen36-q3 (primário GPU) | Não testado esta sessão |

---

## Reversão Rápida (GPU)
```bash
ssh igor@192.168.1.184 'sudo systemctl stop qwen36-q4 qwen36-q3 qwen38-gyro-s ttf-qwen38-27b'
ssh igor@192.168.1.184 'sudo systemctl disable qwen36-q4 qwen36-q3 qwen38-gyro-s ttf-qwen38-27b'
```

---

**Última atualização:** 2026-11-20 00:10 (America/Sao_Paulo) — Testes agênticos completos, CPU MoE offload validado, YARN em 2 modelos CPU.
