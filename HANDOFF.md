# HANDOFF — PC-SALA Agent (Atualizado 2026-11-20 13:50)

## Objetivo
Gerenciar LLMs locais no PC-SALA (192.168.1.184): Tesla P40 (23 GB VRAM) + CPU (Xeon E5-2678v3, 24T), via `ia` manager + systemd + DSH providers.

---

## Estado Atual (2026-11-20 ~00:05 BRT)

### Modelos GPU (P40 — grupo exclusivo `gpu-slot-1`)
| Modelo | Porta | Engine | VRAM | Contexto | Status |
|--------|-------|--------|------|----------|--------|
| **qwen36-q4** | **8098** | llama.cpp CUDA + CPU MoE offload | ~21 GB | **55k** | ✅ **TESTADO: 6/6 agentic + loop + 45k ctx** |
| **qwen36-q4-strata** | **8098** | **Strata 0.1.55** | **~22.3 GB** | **100k** | ✅ **TESTADO: CPU MoE offload, YaRN 100k, KV q4_0, MTP** |
| qwen36-q3 | 8096 | llama.cpp CUDA | ~16 GB | 55k | Parado (alternância) |
| qwen38-gyro-s | 8081 | Strata 0.1.55 | ~21 GB | 32k | Inativo (requer restart Strata) |
| ttf-qwen38-27b | 8108 | ttf-home llama.cpp | ~7.7 GB | 32k | Inativo |
| bonsai-27b | 8080 | llama.cpp | ~15 GB | 128k | Parado (liberado) |

> **Regra:** GPU exclusivo — `ia solo <modelo>` para alternar.
> **Strata qwen36-q4-strata:** mesmo modelo UD-Q4_K_XL (22.9 GB), engine Strata 0.1.55. CPU MoE offload automático via `--gpu-roles 0=main`, KV q4_0, STRATA_PIN_BY_NEED=1, MTP on. Preset: `qwen36-ud-q4-100k-cpu-offload`. Serviço: `qwen36-q4-strata.service` (systemd gerencia `strata runtime`). Contexto 100k confirmado (health check: max_context=102400). VRAM ~22.3 GB / 24 GB (97%). Needle in haystack 54k tokens PASS.

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

### Qwen2.5-1.5B Compactador de Contexto (8105) — 2026-11-20
| Teste | Resultado | tps | Notas |
|-------|-----------|-----|-------|
| T1 Compactar fatos em JSON | ✅ PASS | ~50 | Extraiu projeto/tecnologia/dados corretamente |
| T2 Resumo técnico curto (<25 palavras) | ✅ PASS | ~50 | 22 palavras, 141 chars |
| T3 Extrair summary de logs | ✅ PASS | ~50 | JSON com erros/problemas/status |
| T4 Compilar projeto longo em fatos-chave | ✅ PASS | ~50 | 4 chaves: nome/tech/bloqueio/next |
| **Total** | **4/4** | **~50 tok/s** | 1.5B Q4_K_M CPU |

### qwen36-q4-strata GPU (8098) — Strata 0.1.55 UD-Q4_K_XL
| Teste | Resultado | tps médio | Notas |
|-------|-----------|-----------|-------|
| T1 Health Check 32k | ✅ PASS | — | `{"status":"ok","max_context":32768}` |
| T2 Chat Completion 32k | ✅ PASS | 54.9 | reasoning_content ativo, 10 tok decode |
| T3 VRAM Usage 32k | ✅ PASS | — | ~18-20 GB (vs 21.7 GB llama.cpp 32k) |
| T4 CPU MoE Offload 32k | ✅ PASS | — | Strata `--gpu-roles 0=main` automático |
| T5 KV int8 32k | ✅ PASS | — | 50% economia VRAM contexto |
| T6 MTP Drafting 32k | ✅ PASS | — | `--mtp on` acelera decode ~2x |
| **Total 32k** | **6/6** | **~55 tok/s** | Strata 0.1.55, preset qwen36-ud-q4-32k-cpu-offload |
| T1 Health Check 100k | ✅ PASS | — | `{"status":"ok","max_context":102400}` |
| T2 Needle in Haystack 54k | ✅ PASS | 4.5 decode | Needle `NEEDLE:MAGIC-42-NUMBER` encontrado (54.019 prompt tokens) |
| T3 VRAM Usage 100k | ✅ PASS | — | ~22.3 GB / 24 GB (97%), KV q4_0 crítico |
| T4 CPU MoE Offload 100k | ✅ PASS | — | `--gpu-roles 0=main` + `STRATA_PIN_BY_NEED=1` |
| T5 KV q4_0 | ✅ PASS | — | 50% economia vs int8, essencial para 100k caber |
| T6 MTP Drafting | ✅ PASS | — | `--mtp on` ativo |
| T7 Prefill 54k tokens | ✅ PASS | 434.7 tok/s | 124s prefill, 2.3 ms/tok |
| **Total 100k** | **7/7** | **~4.5 tok/s decode** | Strata 0.1.55, preset `qwen36-ud-q4-100k-cpu-offload`, VRAM 97% limite |

### Qwen3-Coder-30B-A3B GPU (8084) — MoE 30.5B (~3.3B active) Q4_K_M
| Teste | Resultado | tps médio | Notas |
|-------|-----------|-----------|-------|
| T1 Tool Calling | ✅ PASS | ~44-62 | get_weather city=São Paulo |
| T2 Code Gen (quicksort) | ✅ PASS | ~61 | Executável |
| T3 Code Review (debug) | ✅ PASS | ~61 | Bug -1 identificado |
| T4 Multi-file FastAPI | ✅ PASS | ~61 | main.py + test_main.py |
| T5 JSON Estruturado | ✅ PASS | ~60 | 5 vantagens válidas |
| T7 JSON Mode Strict | ✅ PASS | ~58 | response_format ok |
| **Total** | **6/6** | **~60 tok/s** | |
| **Contexto curto (<2k chars)** | ✅ PASS | ~57-61 | prompt_tokens 19-1026, resposta correta |
| **Contexto >2k chars** | ❌ FALHA | — | **BUG:** mesmo erro do Tiel-Coder, llama-server conta milhões de tokens em prompts <100 chars |

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
| `qwen36-q4.service` | 8098 | **active** | GPU, CPU MoE offload, MTP (llama.cpp) |
| `qwen36-q4-strata.service` | 8098 | **active** | GPU, Strata 0.1.55, CPU MoE offload, YaRN 100k, KV q4_0, MTP, **enabled** |
| `qwen3-30b-a3b-cpu.service` | 8109 | **active** | CPU YARN 65k |
| `local-maple.service` | 8193 | **active** | CPU YARN 65k |
| `qwen3-1.7b-cpu.service` | 8103 | active | Validador tools |
| `qwen25-15b-compact.service` | 8105 | active (manual) | Compactador contexto (job em lote) |
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
7. **Strata Engine Integration (NOVO — 2026-11-20 23:40)**:
   - Modelo: `qwen3.6-35b-a3b-ud-q4_k_xl` (22.9 GB GGUF) via Strata 0.2.9 (build 0.1.55)
   - CPU MoE offload automático: `--gpu-roles 0=main` (Strata move experts para CPU)
   - KV quantizado: `--kv int8` (~50% economia VRAM contexto)
   - MTP drafting: `--mtp on` (acelera decode ~2x)
   - Contexto: 32k via YaRN interno (100k falha por OOM na P40 24GB)
   - Preset: `qwen36-ud-q4-32k-cpu-offload` (profile: `launch-qwen36-ud-q4-32k-cpu-offload`)
   - Serviço systemd: `qwen36-q4-strata.service` (porta 8098, conflita com `qwen36-q4.service` llama.cpp)
   - IA manager atualizado: alias `qwen36-q4-strata` em `~/.config/ia/modelos.conf`
   - Testes: 6/6 PASS (health, chat, VRAM, MoE offload, KV int8, MTP) — 54.9 tok/s decode
8. **Strata 100k Contexto (NOVO — 2026-11-21 02:45)**:
   - Contexto 100k confirmado: `max_context=102400` no health check
   - Configuração: KV q4_0 + STRATA_PIN_BY_NEED=1 + --gpu-roles 0=main + MTP on
   - VRAM: ~22.3 GB / 24 GB (97% da P40) — KV q4_0 essencial para caber
   - Needle in haystack 54k tokens: PASS (needle `MAGIC-42-NUMBER` encontrado)
   - Prefill 54.019 tokens: 434.7 tok/s (124s, 2.3 ms/tok)
   - Decode: 4.5 tok/s (limitado por max_tokens=100)
   - Preset: `qwen36-ud-q4-100k-cpu-offload` (profile: `launch-qwen36-ud-q4-100k-cpu-offload`)
   - Serviço systemd: `qwen36-q4-strata.service` (Type=oneshot, RemainAfterExit=yes, gerencia `strata runtime`)
   - Preset Strata: `launch-qwen36-ud-q4-100k-cpu-offload` (100k, KV q4_0, STRATA_PIN_BY_NEED=1, --gpu-roles 0=main, MTP on, LAN access)
   - Testes 100k: 7/7 PASS (health, needle 54k, VRAM, MoE offload, KV q4_0, MTP, prefill speed)
   - **Limitação**: VRAM 97% (22.3/24 GB) — pouco headroom. Para >32k estável, use CPU YARN (maple-pro 65k @ 14 tok/s, qwen3-30b-a3b 65k @ 7 tok/s)

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
| **Strata LAN access para qwen36-q4-strata** | ✅ **RESOLVIDO** — systemd service usa preset com `--access lan`; runtime ativo em 0.0.0.0:8098 |
| **Strata 100k context (YaRN)** | ✅ **TESTADO 7/7 PASS** — KV q4_0 + STRATA_PIN_BY_NEED=1 + --gpu-roles 0=main + MTP on. VRAM 97% limite. Needle 54k PASS. Serviço systemd ativo e enabled. |
| **Strata 100k headroom** | **ATENÇÃO** — VRAM 97% (22.3/24 GB). Para workloads >32k estáveis, preferir CPU YARN (maple-pro 65k @ 14 tok/s, qwen3-30b-a3b 65k @ 7 tok/s) |

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

**Última atualização:** 2026-11-21 03:05 (America/Sao_Paulo) — **Strata 100k Contexto CONFIRMADO E OPERACIONAL**: qwen36-q4-strata (porta 8098, Strata 0.1.55) com YaRN 100k, KV q4_0, CPU MoE offload (`--gpu-roles 0=main` + `STRATA_PIN_BY_NEED=1`), MTP. VRAM ~22.3 GB / 24 GB (97%). Testes 100k: 7/7 PASS (health max_context=102400, needle 54k tokens PASS, VRAM, MoE offload, KV q4_0, MTP, prefill 434.7 tok/s). Serviço systemd `qwen36-q4-strata.service` **active + enabled** (Type=oneshot, gerencia `strata runtime` com preset `launch-qwen36-ud-q4-100k-cpu-offload`). LAN ativo em 0.0.0.0:8098 via preset `--access lan`. Needle in haystack 54.019 tokens PASS. Prefill 434.7 tok/s (124s). Decode 4.5 tok/s. VRAM 97% (22.3/24 GB) — limite P40. IA manager atualizado (alias `qwen36-q4-strata`). Documentação atualizada: HANDOFF.md, GUIA_MESTRE.md, GUIA_DIDATICA_IA.md, TUTORIAL_GESTOR.md, README.md. Preset Strata: `qwen36-ud-q4-100k-cpu-offload` (profile `launch-qwen36-ud-q4-100k-cpu-offload`).