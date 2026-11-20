# PROMPT PARA IA DEV — Atualização de Documentação do PC-SALA Agent

## Contexto do Projeto

**PC-SALA** = Máquina de inferência local (192.168.1.184) com:
- **GPU:** Tesla P40 (23 GB VRAM) — grupo exclusivo `gpu-slot-1`
- **CPU:** Xeon E5-2678v3 (24 threads) — 128 GB RAM
- **Gestores:** `ia` (diário, `~/.local/bin/ia`) + `./pcsala models` (auditado, SQLite)
- **DSH Providers:** DeepSeek Harness Web GUI (porta 3080) integrado aos modelos locais

## Estado Atual dos Modelos (2026-11-15)

### GPU — Alternância Obrigatória (`gpu-slot-1`)
| Modelo | Porta | Engine | VRAM | Status |
|--------|-------|--------|------|--------|
| qwen38-gyro-s | 8081 | Strata 0.1.55 | ~21 GB | Parado |
| ttf-qwen38-27b | 8108 | ttf-home llama.cpp | ~7.7 GB | Parado |
| bonsai-27b | 8080 | llama.cpp | ~15 GB | Parado |

> **Regra dura:** Gyro-S + TTF = ~29 GB > 23 GB. Use `ia solo <modelo>` para alternar. Nunca dois simultâneos.

### CPU — Todos Ativos Simultaneamente
| Modelo | Porta | Engine | Memória | Destaque |
|--------|-------|--------|---------|----------|
| qwen3-30b-a3b-moe-iq4k | **8109** | ik_llama.cpp | ~21 GB RAM | **OPERACIONAL** — Requer ik_llama.cpp (imatrix IQ4_K) |
| maple-pro 20B-A1B | **8193** | llama.cpp YARN x2 | ~1.3 GB RAM | **Benchmark 71%** — Contexto 65536 tokens |
| qwen3-1.7b | 8103 | CPU | - | Ativo |
| qwen2.5-1.5b | 8105 | CPU | - | Ativo |
| lfm2.5-1.2b | 8104 | CPU | - | Ativo |
| phi35-mini | 8106 | CPU | - | Ativo |
| bonsai-9b-cpu | 8090 | CPU | - | Ativo |

## Arquivos-Chave para Atualizar

### 1. `HANDOFF.md` (raiz) — **Estado vivo da máquina**
- Atualizar tabela de modelos, portas, status
- Registrar mudanças de configuração DSH
- Data/hora da última atualização (America/Sao_Paulo)

### 2. `PROJECT_STATE.md` — **Snapshot técnico congelado** (data 2026-10-28)
- **NÃO SOBRESCREVER** — é registro histórico
- Criar novo `PROJECT_STATE-2026-11-15.md` se necessário

### 3. `guias/GUIA_DIDATICA_IA.md` — **Manual do gestor `ia`**
- §2.1: Regras JSON do `modelos.conf` (obrigatório para agentes IA)
- Adicionar novos modelos no formato array JSON com comentários `#`
- Validar: `python3 -c "import json; ..."` antes de salvar

### 4. `guias/GUIA_MESTRE.md` — **Visão geral da máquina**
- Tabela consolidada GPU + CPU
- Políticas de acesso, firewall, ports

### 5. `docs/expansao-gpu-2026-11.md` — **Plano P100 (futuro)**
- Manter como referência; não executado

### 6. `CONTINUITY.md` — **Recuperação pós-reboot**
- Comandos de restore: `systemctl start`, `./pcsala reconcile`, `./pcsala backup`

## Regras de Escrita Obrigatórias

### `~/.config/ia/modelos.conf` — **Formato Único**
```jsonc
[
  {
    "alias": "qwen3-30b-a3b",
    "model_id": "qwen3-30b-a3b-cpu",
    "name": "Qwen3-30B-A3B-MoE IQ4_K CPU",
    "unit": "qwen3-30b-a3b-cpu.service",
    "endpoint": "http://127.0.0.1:8109",
    "class": "CPU",
    "exclusive_group": null,
    "profile": "qwen3-30b-a3b-cpu",
    "shared": false,
    "startup_timeout": 180
  }
]
```
- **Array JSON puro** + comentários `#` em linha inteira
- Parser faz `json.loads()` após remover linhas `#`
- **NUNCA** usar pipe `|`, INI, YAML, lista crua
- Backup antes: `cp modelos.conf modelos.conf.bak-$(date +%Y%m%d)-motivo`

### Systemd Services
- GPU: `/etc/systemd/system/<model>.service` — `-ngl 99` (offload total)
- CPU: `/etc/systemd/system/<model>.service` — `-ngl 0 --threads 20`
- Validar: `systemctl cat <unit> | grep -- --port` = endpoint no `modelos.conf`

## Tarefas para Esta Atualização

1. **Sincronizar `HANDOFF.md`** com estado real acima (já feito no commit 8b147df)
2. **Atualizar `guias/GUIA_DIDATICA_IA.md`** — adicionar qwen3-30b-a3b e maple-pro na tabela de modelos, confirmar portas/units
3. **Criar `PROJECT_STATE-2026-11-15.md`** — snapshot técnico atual (não sobrescrever o de 2026-10-28)
4. **Atualizar `guias/GUIA_MESTRE.md`** — tabela consolidada GPU+CPU
5. **Verificar `CONTINUITY.md`** — comandos de recovery ainda válidos?
6. **Commit + push** para `origin/fase-0` (remote: `https://github.com/igorsantos109/special-doodle.git`)

## Comandos de Validação (executar no PC-SALA)

```bash
# 1. Verificar modelos ativos
ia list
ia doctor

# 2. Verificar systemd
systemctl list-units '*.service' --state=active | grep -E '(qwen|maple|bonsai|nemotron|gyro|ttf|laguna|ornith)'

# 3. Verificar portas
ss -ltnp | grep -E '(8080|8081|8082|8083|8090|8091|8092|8093|8103|8104|8105|8106|8108|8109|8193)'

# 4. Validar modelos.conf
python3 - <<'EOF'
import json, pathlib
raw = pathlib.Path('/home/igor/.config/ia/modelos.conf').read_text()
body = '\n'.join(l for l in raw.splitlines() if not l.strip().startswith('#'))
data = json.loads(body)
print(f"OK: {len(data)} modelos")
for m in data:
    print(f"  {m['alias']:20s} -> {m['endpoint']} ({m['class']})")
EOF

# 5. Testar health checks
for port in 8081 8108 8109 8193; do
  curl -s "http://127.0.0.1:$port/health" | head -c 80; echo "  (porta $port)"
done
```

## Entrega Esperada

- Todos os arquivos acima atualizados e consistentes entre si
- `git status` limpo (apenas modificações intencionais)
- Commit message convencional: `docs: atualizar documentação 2026-11-15 - ...`
- Push para `origin/fase-0` confirmado

## Referências Rápidas

- Repositório local: `/home/igor/ia-sh/pc-sala-agent` (esta máquina) / `/home/igor/pc-sala-agent` (PC-SALA)
- Branch: `fase-0`
- Handoff anterior: `HANDOFF.md` (commit 8b147df)
- Guias legados movidos para: `LEGADO/` e `guias/LEGADO/`

---

**Use este prompt como base** — adapte conforme gaps que encontrar ao rodar os comandos de validação.