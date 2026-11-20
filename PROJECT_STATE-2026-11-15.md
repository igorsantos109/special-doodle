# Estado do Projeto — Snapshot 2026-11-15

> **NOTA:** Este é um snapshot técnico do estado atual. O `PROJECT_STATE.md` original (2026-10-28) permanece como registro histórico e NÃO deve ser sobrescrito.

---

## Modelos Operacionais (10 ativos + 3 GPU em alternância)

### GPU — Grupo Exclusivo `gpu-slot-1` (Tesla P40 23 GB)
| Modelo | Porta | Engine | Ctx | Geração | VRAM | Status |
|---|---|---|---|---|---|---|
| qwen38-gyro-s | 8081 | Strata 0.1.55 | 128K | ~20-30 tok/s | ~21 GB | Parado (alternância) |
| ttf-qwen38-27b | 8108 | ttf-home llama.cpp | 32K | ~25-35 tok/s | ~7.7 GB | Parado (alternância) |
| bonsai-27b | 8080 | llama.cpp (PrismML) | 64K | 28-48 tok/s | ~15 GB | Parado (liberado) |

**Regra:** Gyro-S + TTF = ~29 GB > 23 GB. Use `ia solo <modelo>` para alternar.

### CPU — Todos Ativos Simultaneamente (Xeon 24T, 128 GB RAM)
| Modelo | Porta | Engine | Ctx | Geração | RAM | Status |
|---|---|---|---|---|---|---|
| **qwen3-30b-a3b-moe-iq4k** | **8109** | ik_llama.cpp | 32K | **~8 tok/s** | ~21 GB | ✅ OPERACIONAL |
| **maple-pro 20B-A1B** | **8193** | llama.cpp YARN x2 | 65K | **~15 curto / ~8 longo** | ~1.3 GB | ✅ BENCHMARK |
| qwen3-1.7b | 8103 | llama.cpp | 32K | ~40+ tok/s | ~1.5 GB | Ativo |
| qwen2.5-1.5b | 8105 | llama.cpp | 32K | ~45+ tok/s | ~1.2 GB | Ativo |
| lfm2.5-1.2b | 8104 | llama.cpp | 32K | ~50+ tok/s | ~1 GB | Ativo |
| phi35-mini | 8106 | llama.cpp | 4K | ~60+ tok/s | ~0.8 GB | Ativo |
| bonsai-9b-cpu | 8090 | llama.cpp | 32K | ~6 tok/s | ~5 GB | Ativo |

---

## Detalhes Técnicos por Modelo

### Qwen3-30B-A3B-MoE IQ4_K CPU (porta 8109)
- **Modelo:** `Qwen3-30B-A3B-mix-IQ4_K.gguf` (~19 GB) em `/home/igor/models/qwen3-30B-A3B/`
- **Engine:** ik_llama.cpp compilado localmente (`~/ik_llama.cpp-build/build/bin/llama-server`)
- **Service:** `/etc/systemd/system/qwen3-30b-a3b-cpu.service`
- **Flags:** `-c 32768 --threads 20 -ngl 0 --parallel 2 --jinja`
- **Requisito crítico:** ik_llama.cpp (vanilla llama.cpp NÃO suporta imatrix IQ4_K)
- **Performance:** ~8 tok/s decode, ~21 GB RAM

### Maple-Pro 20B-A1B TQ2_0+Q4_K YARN (porta 8193)
- **Modelo:** `maple-pro.gguf` (6.2 GB) em `/mnt/arquivos/models/maple-preview/`
- **Contexto expandido:** 32768 → **65536 tokens** via `--rope-scaling yarn --yarn-ext-factor 2.0`
- **Service:** `/etc/systemd/system/local-maple.service` — `-c 65536 --rope-scaling yarn`
- **Benchmark agêntrico:** 5/7 = 71% (Code gen ✅, Math ✅, Tools ✅, Memory ✅, Prompt ✅, JSON ❌ tipo, Code review ❌ parcial)
- **Formato resposta:** DeepSeek-thinking (`reasoning_content` + `content` separados)
- **Performance:** ~15 tok/s curto, ~8 tok/s longo; RAM 636 MB → 1.3 GB com YARN
- **Bind:** `127.0.0.1:8193` (apenas localhost)

### Modelos CPU Pequenos (portas 8103-8106, 8090)
- Todos rodando llama.cpp vanilla, `-ngl 0 --threads 20` (exceto phi35-mini 4K ctx)
- Iniciados via systemd, health checks em `/health`

---

## Configuração DSH (DeepSeek Harness Web GUI — porta 3080)

- `~/.dsh/profiles/web/cordis.patch.yml` — providers:
  - `ttf-qwen38` → `http://127.0.0.1:8108`
  - `gyro-s` → `http://127.0.0.1:8081`
  - `qwen3-30b-a3b` → `http://127.0.0.1:8109` (header `PCSALA_LOCAL_API_KEY`)
- `~/.dsh/.env` — `PCSALA_LOCAL_API_KEY=pcsala-open-no-auth`, `DSH_LOCAL_API_KEY=sk-strata-...`
- **Reinício GUI necessário:** `pnpm run dev:web`

---

## Serviços systemd Ativos

| Serviço | Porta | Estado |
|---|---|---|
| `qwen3-30b-a3b-cpu.service` | 8109 | active |
| `local-maple.service` | 8193 | active |
| `qwen3-1.7b-cpu.service` | 8103 | active |
| `qwen2.5-1.5b-cpu.service` | 8105 | active |
| `lfm2.5-1.2b-cpu.service` | 8104 | active |
| `phi35-mini-cpu.service` | 8106 | active |
| `bonsai2-cpu.service` | 8090 | active |
| `qwen38-gyro-s.service` | 8081 | inactive |
| `ttf-qwen38.service` | 8108 | inactive |
| `bonsai2-27b.service` | 8080 | inactive |
| `pcsala-worker.service` | — | active |

---

## Repositório Local
- **Path:** `/home/igor/pc-sala-agent` (PC-SALA) / `/home/igor/ia-sh/pc-sala-agent` (local)
- **Branch:** `fase-0`
- **Remote:** `origin` → `https://github.com/igorsantos109/special-doodle.git` (read-only, push 403)
- **Commits recentes:**
  - `1111c84` — docs: organizar documentação e mover legados para LEGADO/
  - `8b147df` — docs: atualizar HANDOFF.md com estado atual 2026-11-15

---

## Documentação Atualizada (esta sessão)
- `HANDOFF.md` — Estado vivo sincronizado (commit 8b147df)
- `guias/GUIA_MESTRE.md` — v9.0 com tabela completa GPU+CPU + velocidades
- `guias/GUIA_DIDATICA_IA.md` — Atualizado com modelos atuais, velocidades, aliases
- `PROJECT_STATE-2026-11-15.md` — Este snapshot (novo, não sobrescreve original)
- `LEGADO/` — 9 arquivos movidos (5 raiz + 4 guias/)

---

## Próximos Passos Pendentes
- [ ] Validar `modelos.conf` no PC-SALA com todos 23 aliases
- [ ] Testar `ia doctor` completo
- [ ] Atualizar `guias/MANUAL_GESTOR_API.md` se necessário
- [ ] Atualizar `guias/TUTORIAL_GESTOR.md` se necessário
- [ ] Commit + push documentação atualizada

---

**Gerado em:** 2026-11-15 23:30 (America/Sao_Paulo)