# HANDOFF — PC-SALA Agent (Atualizado 2026-11-15)

## Objetivo
Gerenciar LLMs locais no PC-SALA (192.168.1.184): Tesla P40 (23 GB VRAM) + CPU (Xeon E5-2678v3, 24T), via `ia` manager + systemd + DSH providers.

---

## Estado Atual (2026-11-15 ~23:15 BRT)

### Modelos GPU (P40 — grupo exclusivo `gpu-slot-1`)
| Modelo | Porta | Engine | VRAM | Status |
|--------|-------|--------|------|--------|
| qwen38-gyro-s | 8081 | Strata 0.1.55 | ~21 GB | Parado (alternância) |
| ttf-qwen38-27b | 8108 | ttf-home llama.cpp | ~7.7 GB | Parado (alternância) |
| bonsai-27b | 8080 | llama.cpp | ~15 GB | Parado (liberado para TTF/Gyro-S) |

> **Regra:** Gyro-S + TTF = ~29 GB > 23 GB. Use `ia solo <modelo>` para alternar.

### Modelos CPU (ativos)
| Modelo | Porta | Engine | Memória | Status |
|--------|-------|--------|---------|--------|
| **qwen3-30b-a3b-moe-iq4k** | **8109** | ik_llama.cpp | ~21 GB RAM | ✅ OPERACIONAL |
| **maple-pro 20B-A1B** | **8193** | llama.cpp YARN x2 | ~1.3 GB RAM | ✅ BENCHMARK + YARN |
| qwen3-1.7b | 8103 | CPU | - | Ativo |
| qwen2.5-1.5b | 8105 | CPU | - | Ativo |
| lfm2.5-1.2b | 8104 | CPU | - | Ativo |
| phi35-mini | 8106 | CPU | - | Ativo |
| bonsai-9b-cpu | 8090 | CPU | - | Ativo |

---

## Configuração DSH (DeepSeek Harness)
- `~/.dsh/profiles/web/cordis.patch.yml` — providers `ttf-qwen38` (8108), `gyro-s` (8081), **`qwen3-30b-a3b` (8109, PCSALA_LOCAL_API_KEY)**
- `~/.dsh/.env` — `PCSALA_LOCAL_API_KEY=pcsala-open-no-auth`, `DSH_LOCAL_API_KEY=sk-strata-...` (Gyro-S)
- **Reinício GUI necessário:** `pnpm run dev:web` para ver modelos no seletor

---

## Qwen3-30B-A3B-MoE IQ4_K CPU (ik_llama.cpp) — OPERACIONAL (porta 8109)
- Modelo: `Qwen3-30B-A3B-mix-IQ4_K.gguf` (~19 GB) em `/home/igor/models/qwen3-30B-A3B/`
- Engine: ik_llama.cpp compilado (`~/ik_llama.cpp-build/build/bin/llama-server`)
- Service: `/etc/systemd/system/qwen3-30b-a3b-cpu.service` — `-c 32768 --threads 20 -ngl 0 --parallel 2 --jinja`
- Requer ik_llama.cpp (vanilla llama.cpp NÃO suporta imatrix IQ4_K)
- Performance: ~8 tok/s decode, ~21 GB RAM

---

## Maple-Pro 20B-A1B TQ2_0+Q4_K — BENCHMARK + YARN (porta 8193)
- Modelo: `maple-pro.gguf` (6.2 GB) em `/mnt/arquivos/models/maple-preview/`
- **Contexto expandido:** 32768 → **65536 tokens** via `--rope-scaling yarn --yarn-ext-factor 2.0`
- Service: `/etc/systemd/system/local-maple.service` — `-c 65536 --rope-scaling yarn`
- **Benchmark agêntrico:** 5/7 = 71% (Code gen ✅, Math ✅, Tools ✅, Memory ✅, Prompt ✅, JSON ❌ tipo, Code review ❌ parcial)
- Formato resposta: DeepSeek-thinking (`reasoning_content` + `content` separados)
- Performance: ~15 tok/s curto, ~8 tok/s longo; RAM 636 MB → 1.3 GB com YARN
- Bind: `127.0.0.1:8193` (apenas localhost)

---

## Repositório Local (`/home/igor/ia-sh/pc-sala-agent`)
- Branch: `fase-0` | Commits locais: 6 (incl. organização docs) | Remotes: todos read-only (push 403)

---

## Última atualização
2026-11-15 23:15 (America/Sao_Paulo) — Documentação organizada: HANDOFF.md sincronizado com estado real, LEGADO/ criados, push GitHub concluído.
