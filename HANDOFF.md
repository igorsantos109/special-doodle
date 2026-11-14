# HANDOFF — PC-SALA Agent (Compactado)

## Objetivo
Gerenciar LLMs locais no PC-SALA (192.168.1.184): Tesla P40 (23 GB VRAM) + CPU (Xeon E5-2678v3, 24T), via `ia` manager + systemd + DSH providers.

---

## Estado Atual (2026-11-14)

### Modelos GPU (P40 — grupo exclusivo `gpu-slot-1`)
| Modelo | Porta | Engine | VRAM | Contexto | Status |
|--------|-------|--------|------|----------|--------|
| **qwen38-gyro-s** | 8081 | Strata 0.1.55 | ~21 GB | 32k | Ativo, MTP+Cache |
| **ttf-qwen38-27b** | 8108 | ttf-home llama.cpp | ~7.7 GB | 65k | Ativo, Q1 ternary |
| **bonsai-27b** | 8080 | llama.cpp | ~15 GB | 128k | Parado (liberado para TTF) |

> **Regra:** Gyro-S + TTF = ~29 GB > 23 GB. Use `ia solo <modelo>` para alternar.

### Modelos CPU (ativos)
| Modelo | Porta | Threads | Uso |
|--------|-------|---------|-----|
| maple-pro | 8193 | 20/24 | Reasoning deep, 10.7 tok/s |
| qwen3-1.7b | 8103 | 24 | Validador tools, 15.7 tok/s |
| qwen2.5-1.5b | 8105 | 24 | Codificador, 13.3 tok/s |
| lfm2.5-1.2b | 8104 | 24 | Fallback ultra-rápido, 22.6 tok/s |
| phi35-mini | 8106 | 24 | LAN liberada (192.168.1.170) |
| smollm2-1.7b | 8107 | 24 | Sob demanda |
| bonsai-9b-cpu | 8090 | 24 | Batch/triagem, 6.4 tok/s |

---

## Configuração DSH (DeepSeek Harness)

**Arquivos alterados:**
- `~/.dsh/profiles/web/cordis.patch.yml` — providers `ttf-qwen38` (porta 8108) + `gyro-s` (porta 8081)
- `~/.dsh/.env` — `DSH_LOCAL_API_KEY=sk-strata-zhmxMe6u9RcjJmmI4ykiZ2meu7L5-H2J` (Gyro-S)

**Reinício necessário:** `pnpm run dev:web` ou recarregar GUI DSH.

---

## Repositório Local (`/home/igor/ia-sh/pc-sala-agent`)

| Item | Estado |
|------|--------|
| Branch | `fase-0` |
| Commits não enviados | 5 (repos GitHub **arquivados/read-only** — push falha com 403) |
| Working tree | Limpo |
| Remotes | `origin` (ialocalagent), `pc-sala-agent`, `special-doodle` — todos read-only |

---

## Próxima Ação Concreta

```bash
# 1. Push BLOQUEADO — repos GitHub arquivados (read-only)
#    Alternativa: criar novo repo ou desarquivar no GitHub

# 2. Validar no pc-sala via SSH
ssh igor@192.168.1.184 '~/.local/bin/ia list'
ssh igor@192.168.1.184 '~/.local/bin/ia doctor'

# 3. Testar alternância GPU
ssh igor@192.168.1.184 'ia solo ttf-qwen38'
ssh igor@192.168.1.184 'ia solo qwen38-gyro-s'
```

---

## Pendências / Bloqueios

| Item | Status |
|------|--------|
| Push `origin/fase-0` | **BLOQUEADO** — repos GitHub arquivados (403 read-only) |
| Teste real TTF (chat/code/math) | Pendente |
| Gyro-S 128k + MCP memory-writer | Precisa restart Strata com `--set mcp_config=...` |
| Hy-Memory-30B-A3B | Não suportado no Strata (arquitetura `hy_v3`) |
| Firewall LAN para portas 8081/8108 | Já liberado via nft/ufw para 192.168.1.170 |

---

## Reversão Rápida (GPU)

```bash
ssh igor@192.168.1.184 'sudo systemctl stop ttf-qwen38-27b qwen38-gyro-s'
ssh igor@192.168.1.184 'sudo systemctl disable ttf-qwen38-27b qwen38-gyro-s'
ssh igor@192.168.1.184 'sudo rm /etc/systemd/system/{ttf-qwen38-27b,qwen38-gyro-s}.service && sudo systemctl daemon-reload'
# Editar ~/.config/ia/modelos.conf para remover entradas
```

---

**Última atualização:** 2026-11-14 16:10 (America/Sao_Paulo) — sessão compactada