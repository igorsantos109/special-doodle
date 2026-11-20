# HANDOFF — PC-SALA Agent (Atualizado 2026-11-20 13:50)

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
| **tiel-coder-35b-a3b** | **8087** | llama.cpp CUDA MTP IQ4_XS | ~32k* | ~17.3 GB | ✅ TESTADO 6/6 agentic, ~60 tok/s |
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

### tiel-coder-35b-a3b GPU (8087) — MTP IQ4_XS
| Teste | Resultado | tps médio | Notas |
|-------|-----------|-----------|-------|
| T1 Tool Calling | ✅ PASS | ~52 | get_weather city=São Paulo |
| T2 Code Gen (quicksort) | ✅ PASS | ~64 | Executável |
| T3 Code Review (debug) | ✅ PASS | ~61 | Bug -1 identificado |
| T4 Multi-file FastAPI | ✅ PASS | ~63 | main.py + test_main.py |
| T5 JSON Estruturado | ✅ PASS | ~60 | 5 vantagens válidas |
| T7 JSON Mode Strict | ✅ PASS | ~58 | response_format |
| **Total** | **6/6** | **~60 tok/s** | |
| **Contexto Longo (>5k)** | ❌ FALHA | — | **BUG:** llama-server conta tokens incorretamente (ex: 5k chars → 2M tokens), excede 32768. Requer correção no build llama-cuda-official 73bfe6c. Contexto útil limitado a ~5k tokens. |

---

## Configuração DSH (DeepSeek Harness Web GUI — porta 3080)
- `~/.dsh/profiles/web/cordis.patch.yml` — providers: `ttf-qwen38` (8108), `gyro-s` (8081), `qwen3-30b-a3b` (8109, header `PCSALA_LOCAL_API_KEY`), `qwen36-q4` (8098), `maple-pro` (8193), **`nvidia-nim-tor` (via Tor)**
- `~/.dsh/.env` — `PCSALA_LOCAL_API_KEY=pcsala-open-no-auth`, `DSH_LOCAL_API_KEY=sk-strata-...`, `NVIDIA_API_KEY=nvapi-PZ9LEaX_...`, `OMNIROUTE_API_KEY=sk-8a28e069...`
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
| `codium-proxy.service` (sing-box) | 18118 | **active** | Tor gateway (18118 → 9050) |
| `tor@default.service` | 9050 | **active** | Tor daemon |

---

## Alterações Recentes (esta sessão - 2026-11-20 00:05→13:50)
1. **qwen36-q4**: Habilitado `--cpu-moe` (offload experts MoE para CPU/RAM) — libera VRAM, mantém performance
2. **qwen3-30b-a3b**: Ativado YARN (`--rope-scaling yarn --yarn-ext-factor 2.0 --yarn-orig-ctx 32768`) — contexto 32k → 65k
3. **Testes agênticos completos**: 3 modelos testados (GPU + 2 CPU) com suite de 5 testes + loop multi-step + contexto longo
4. **Tor Gateway + DSH Integration (NOVO)**: 
   - sing-box (`codium-proxy.service`) rodando em `127.0.0.1:18118` → Tor daemon `127.0.0.1:9050`
   - Perfis isolados: `p-omniroute` (18119, usuário `omniroute`), `p-test_profile` (9999)
   - `dsh-http-proxy` carrega `HTTP_PROXY/HTTPS_PROXY=18118` do `~/.dsh/.env`
   - OmniRoute process tem `ALL_PROXY=socks5://127.0.0.1:18119` (perfil isolado)
5. **DSH Provider Config (NOVO)**:
   - `~/.dsh/profiles/web/cordis.patch.yml` editado:
     - `llm-newapi` (dsh-gateway-provider) **desabilitado** (`disabled: true`)
     - `llm-pi-ai` adicionado provider `nvidia-nim-tor`:
       - `baseURL: https://integrate.api.nvidia.com/v1`
       - `apiKeyEnv: NVIDIA_API_KEY`
       - Modelos: `mistralai/mistral-large-4-1t-a52b`, `minimaxai/minimax-m3.1-flash`, `stepfun-ai/step-5-preview`
       - Todos com `input: [text, image]`
   - Backup: `~/.dsh/profiles/web/cordis.patch.yml.bak-pre-omniroute-tor-20261120-0530`
6. **Validação funcional**: 
   - `curl --proxy 18118 https://integrate.api.nvidia.com/v1/chat/completions` → **OK** (exit IP 109.70.100.6 via Tor)
   - `curl --proxy 18119 https://api.ipify.org` → **OK** (exit IP 185.220.101.165 via Tor, perfil isolado)
   - DSH web GUI restartado para carregar novo patch

---

## Próxima Ação Concreta
```bash
# Validar DSH providers locais
ssh igor@192.168.1.184 'curl -s http://127.0.0.1:8098/health && curl -s http://127.0.0.1:8109/health && curl -s http://127.0.0.1:8193/health'

# Verificar DSH GUI providers carregados (após restart)
# http://127.0.0.1:3080 → Settings → Models → nvidia-nim-tor deve aparecer

# Testar nvidia-nim-tor no DSH:
# 1. Settings → Models → selecionar nvidia-nim-tor → mistralai/mistral-large-4-1t-a52b
# 2. Nova conversa → testar chamada
```

---

## Pendências / Bloqueios
| Item | Status |
|------|--------|
| Push `origin/fase-0` | **BLOQUEADO** — repos GitHub arquivados (403 read-only) |
| Gyro-S Strata restart com MCP | Pendente |
| tiel-coder-35b-a3b contexto >5k | **FALHA — bug contagem tokens** — llama-server conta 2M+ tokens em prompts ~5k chars, excede 32768. Requer correção no build llama-cuda-official 73bfe6c. |
| Firewall LAN para 8098/8109 | Liberar no nft/ufw se necessário |
| qwen36-q3 (primário GPU) | Não testado esta sessão |
| DSH GUI recarregar providers | **EM ANDAMENTO** — restart necessário, verificar nvidia-nim-tor aparece |

---

## Reversão Rápida (GPU)
```bash
ssh igor@192.168.1.184 'sudo systemctl stop qwen36-q4 qwen36-q3 qwen38-gyro-s ttf-qwen38-27b'
ssh igor@192.168.1.184 'sudo systemctl disable qwen36-q4 qwen36-q3 qwen38-gyro-s ttf-qwen38-27b'
```

---

## Reversão Tor/DSH Integration
```bash
# Restaurar patch anterior
cp ~/.dsh/profiles/web/cordis.patch.yml.bak-pre-omniroute-tor-20261120-0530 ~/.dsh/profiles/web/cordis.patch.yml
cd /home/igor/.npm-global/lib/node_modules/@deepseek-ai/dsh && pnpm run dev:web

# Parar Tor gateway
systemctl --user stop codium-proxy
```

---

**Última atualização:** 2026-11-20 13:50 (America/Sao_Paulo) — Tor gateway integrado ao DSH, provider `nvidia-nim-tor` adicionado e validado via proxy chain sing-box:18118 → Tor:9050. DSH web GUI reiniciando.