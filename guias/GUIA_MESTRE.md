# GUIA MESTRE — PC-SALA-AGENT (v9.0 — 2026-11-15)

**Data:** 15/11/2026 · **Host:** `pc-sala` (192.168.1.184) · **GPU:** Tesla P40 23 GB

## Arquitetura

```
CLI pcsala / ia  →  Worker (LangGraph) / ModelCoordinator
                     →  llama-server / Strata / ttf-home (inferencia)
```

## Hardware

| Componente | Especificação |
|---|---|
| CPU | Xeon E5-2678 v3, 24 threads @ 2.50 GHz |
| RAM | 128 GiB |
| GPU | Tesla P40 23.040 MiB, CC 6.1 (Pascal), driver 580.x |
| CUDA | 12.4.x |

---

## Modelos — Estado Atual (2026-11-15)

### GPU — Grupo Exclusivo `gpu-slot-1` (Alternância Obrigatória)
| Modelo | Porta | Engine | Ctx | Gen tok/s | VRAM | Status |
|---|---|---|---|---|---|---|
| **qwen38-gyro-s** | **8081** | Strata 0.1.55 | 128K | ~20-30 | ~21 GB | Parado (alternância) |
| **ttf-qwen38-27b** | **8108** | ttf-home llama.cpp | 32K | ~25-35 | ~7.7 GB | Parado (alternância) |
| **bonsai-27b** | **8080** | llama.cpp (PrismML) | 64K | 28-48 | ~15 GB | Parado (liberado) |

> **Regra dura:** Gyro-S (~21 GB) + TTF (~7.7 GB) = ~29 GB > 23 GB VRAM.
> Use `ia solo <modelo>` para alternar. **Nunca dois simultâneos.**

### CPU — Todos Ativos Simultaneamente
| Modelo | Porta | Engine | Ctx | Gen tok/s | RAM | Status |
|---|---|---|---|---|---|---|
| **qwen3-30b-a3b-moe-iq4k** | **8109** | ik_llama.cpp | 32K | **~8** | ~21 GB | ✅ OPERACIONAL |
| **maple-pro 20B-A1B** | **8193** | llama.cpp YARN x2 | 65K | **~15 curto / ~8 longo** | ~1.3 GB | ✅ BENCHMARK |
| qwen3-1.7b | 8103 | llama.cpp | 32K | ~40+ | ~1.5 GB | Ativo |
| qwen2.5-1.5b | 8105 | llama.cpp | 32K | ~45+ | ~1.2 GB | Ativo |
| lfm2.5-1.2b | 8104 | llama.cpp | 32K | ~50+ | ~1 GB | Ativo |
| phi35-mini | 8106 | llama.cpp | 4K | ~60+ | ~0.8 GB | Ativo |
| bonsai-9b-cpu | 8090 | llama.cpp | 32K | ~6 | ~5 GB | Ativo |

> **Destaques CPU:**
> - **Qwen3-30B-A3B MoE IQ4_K:** Requer `ik_llama.cpp` (vanilla llama.cpp NÃO suporta imatrix IQ4_K). Service: `-c 32768 --threads 20 -ngl 0 --parallel 2 --jinja`
> - **Maple-Pro 20B-A1B YARN:** Contexto expandido 32K → 65K via `--rope-scaling yarn --yarn-ext-factor 2.0`. Benchmark agêntrico 5/7 = 71%. Formato DeepSeek-thinking (`reasoning_content` + `content` separados). Bind: `127.0.0.1:8193` (localhost only).

---

## Modelos Desativados / Legado (Referência)
| Modelo | Porta | Motivo |
|---|---|---|
| Bonsai 27B GPU + MTP | 8080 | Substituído por Gyro-S/TTF |
| Bonsai 4B GPU | 8093 | Residente, não no boot |
| Laguna XS 2.1 CPU | 8091 | Desativado (libera RAM) |
| Laguna XS 2.1 GPU | 8082 | Desativado, exclusivo |
| Ornith 35B GPU | 8092 | Desativado, exclusivo |
| Nemotron 3.5 Ternary 30B | 8083 | Desativado, exclusivo |

---

## Comandos

```bash
# Gestor auditado (SQLite + guarda VRAM)
./pcsala models list
./pcsala models status <id>
./pcsala models health <id>
./pcsala models start <id>
./pcsala models stop <id>
./pcsala models switch <id>   # apenas modelos GPU exclusivos
./pcsala models vram          # VRAM por modelo e folga
./pcsala health
./pcsala enqueue --prompt "texto" [--profile <perfil>]
./pcsala status <id>
./pcsala cancel <id>
./pcsala reconcile
./pcsala backup

# Gestor diário (rápido, sem guardas VRAM) — ver guias/GUIA_DIDATICA_IA.md
ia list
ia status <m>
ia health <m>
ia on|off|restart <m>
ia solo <m>          # troca GPU (para atual, sobe solicitado)
ia doctor
```

---

## Serviços systemd — Estado Atual

| Serviço | Porta | Estado | Notas |
|---|---|---|---|
| `qwen3-30b-a3b-cpu.service` | 8109 | **active** | ik_llama.cpp, 20 threads |
| `local-maple.service` | 8193 | **active** | YARN 65K ctx, localhost only |
| `qwen3-1.7b-cpu.service` | 8103 | active | |
| `qwen2.5-1.5b-cpu.service` | 8105 | active | |
| `lfm2.5-1.2b-cpu.service` | 8104 | active | |
| `phi35-mini-cpu.service` | 8106 | active | |
| `bonsai2-cpu.service` | 8090 | active | Bonsai 9B CPU |
| `qwen38-gyro-s.service` | 8081 | inactive | Strata, GPU |
| `ttf-qwen38.service` | 8108 | inactive | ttf-home, GPU |
| `bonsai2-27b.service` | 8080 | inactive | PrismML, GPU |
| `pcsala-worker.service` | — | active | Worker contínuo |

> Lock de troca GPU: `/run/pcsala/pcsala-gpu-switch.lock`

---

## Configuração DSH (DeepSeek Harness Web GUI — porta 3080)

- `~/.dsh/profiles/web/cordis.patch.yml` — providers:
  - `ttf-qwen38` → `http://127.0.0.1:8108`
  - `gyro-s` → `http://127.0.0.1:8081`
  - `qwen3-30b-a3b` → `http://127.0.0.1:8109` (header `PCSALA_LOCAL_API_KEY`)
- `~/.dsh/.env` — `PCSALA_LOCAL_API_KEY=pcsala-open-no-auth`, `DSH_LOCAL_API_KEY=sk-strata-...`
- **Reinício GUI necessário após mudanças:** `pnpm run dev:web`

---

## Permissões (sem sudo)

```bash
# 1. /etc/tmpfiles.d/pcsala.conf — cria /run/pcsala (igor:igor) no boot
sudo install -D -m 0644 deploy/tmpfiles/pcsala.conf /etc/tmpfiles.d/pcsala.conf
sudo systemd-tmpfiles --create /etc/tmpfiles.d/pcsala.conf

# 2. /etc/polkit-1/rules.d/50-pcsala.rules — autoriza igor a start/stop units
#    IMPORTANTE: comentários em // (não #), action.lookup("unit")
sudo install -m 0644 deploy/polkit/50-pcsala.rules /etc/polkit-1/rules.d/
sudo systemctl restart polkit

# Verificação:
systemctl --no-ask-password stop qwen3-30b-a3b-cpu.service   # permitido
systemctl --no-ask-password stop ssh.service                 # deve negar
```

Firewall: `pcsala-bonsai-firewall.service` (nftables, `pcsala_api` permite apenas 192.168.0.0/16).

---

## API

- API obrigatória, **API key não** (aceita header `Authorization` mas ignora).
- DSH providers usam `PCSALA_LOCAL_API_KEY=pcsala-open-no-auth`.

---

## Slot save/restore KV (Documentos Longos)

- Serviços GPU com `--slot-save-path` (Bonsai 27B, Gyro-S, TTF).
- Worker chama `POST /slots/<id>?action=save|restore` em tarefas "document".
- **Desativado por default** (`PCSALA_SLOT_SAVE_RESTORE=1` para ativar).
- Validar em slot descartável antes de ativar (MROPE pode não aceitar restauro).

---

## Limites Conhecidos

- Nenhum executor privilegiado; preparação segura de diretórios pendente.
- Tetos de saída/armazenamento apenas declarados no perfil.
- Checkpoints/arquivos/Git não formam transação conjunta.
- Não executar planos do orquestrador como root.
- Gyro-S + TTF não cabem juntos na P40 (29 GB > 23 GB).
- Qwen3-30B IQ4_K requer ik_llama.cpp compilado localmente.
- Maple-Pro YARN bind localhost only (8193) — não exposto via firewall.

---

## Referências Rápidas

- `guias/GUIA_DIDATICA_IA.md` — Gestor `ia` detalhado, `modelos.conf` JSON
- `guias/MANUAL_GESTOR_API.md` — Arquitetura do `pcsala models`
- `guias/TUTORIAL_GESTOR.md` — Comandos rápidos `pcsala`
- `HANDOFF.md` — Estado vivo da máquina (atualizado 2026-11-15)
- `docs/expansao-gpu-2026-11.md` — Plano P100 (futuro)
- `CONTINUITY.md` — Recuperação pós-reboot
- `PROJECT_STATE.md` — Snapshot histórico 2026-10-28 (não sobrescrever)