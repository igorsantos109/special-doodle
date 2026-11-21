# Guia Didático — Gestor de IA (`ia`)

**Data:** 20/11/2026 (atualizado — qwen36-q4 GPU MoE offload, qwen3-30b-a3b YARN, maple-pro YARN, **Strata qwen36-q4-strata**) · **Alvo:** `~/.local/bin/ia` · **Host:** `pc-sala` (192.168.1.184)

Este guia explica o gestor de IA actual de ponta a ponta: o que é, como
lê a configuração, o que cada comando faz, como trocar de modelo na GPU
e como diagnosticar problemas. Não substitui o `TUTORIAL_GESTOR`
(focado em `./pcsala models`): o sistema tem **dois gestores** e este é
o de uso diário.

---

## 1. O que é

`ia` é um script Python (std-lib, sem dependências) que actua sobre os
modelos locais de linguagem do PC-SALA: liga, desliga, reinicia e
diagnostica os serviços `llama-server` e verifica os endpoints HTTP.

```
ia  ──►  ~/.config/ia/modelos.conf   (lista de modelos)
      ──►  systemctl start|stop|status|restart <unit>
      ──►  GET <endpoint>/health
```

### `ia` vs `./pcsala models`

| | `ia` | `./pcsala models` |
|---|---|---|
| Onde está | `~/.local/bin/ia` | repositório (`./pcsala`) |
| Configuração | `~/.config/ia/modelos.conf` | `src/pcsala_agent/model_manager.py` |
| Guarda de VRAM | não (liga directo) | **sim** — recusa abaixo de 1,5 GB |
| Registo em BD | não | sim (`model_operations`) |
| Perfil/worker | não | liga-se aos perfis de inferência |
| Uso típico | operação diária rápida | operações auditadas, trocas com guardas |

Ambos funcionam e **não estão unificados** (ver `ANALISE_PROMPT_v8.2.md`).
Os dois tocam nos mesmos serviços systemd, por isso operem por um só de
cada vez.

---

## 2. Configuração

Ficheiro: **`~/.config/ia/modelos.conf`** — array JSON com comentários `#`
(linhas iniciadas por `#` são ignoradas; o resto é JSON puro).

```jsonc
[
  {
    "alias": "qwen3-30b-a3b",                // nome curto usado nos comandos
    "model_id": "qwen3-30b-a3b-cpu",         // id igual ao do pcsala models
    "name": "Qwen3-30B-A3B-MoE IQ4_K CPU",   // texto de saída
    "unit": "qwen3-30b-a3b-cpu.service",     // unidade systemd
    "endpoint": "http://127.0.0.1:8109",     // health check
    "class": "CPU",                          // GPU | CPU
    "exclusive_group": null,                 // slot exclusivo (só GPU)
    "profile": "qwen3-30b-a3b-cpu",          // perfil de inferência
    "shared": false,                         // true = modelo residente
    "startup_timeout": 180                   // segundos à espera do /health
  }
]
```

### 2.1 Regras de escrita — OBRIGATÓRIO para agentes de IA

**Formato único aceite:** array JSON, com comentários `#` em linhas inteiras
(uma linha `#` é ignorada; o resto é JSON puro). O parser (`_load_config` em
`~/.local/bin/ia`) faz `json.loads` depois de remover as linhas `#`. Escrever o
ficheiro em **qualquer outro formato** (pipe `a|b|c`, INI, YAML, lista crua)
quebra **todo** o gestor: todos os comandos falham com
`ERRO: configuracao mal formatada: Expecting value: ...`.

**Incidente 2026-11-09 (não repetir):** na substituição maple-preview →
maple-pro, o `modelos.conf` foi reescrito em formato pipe
(`alias|caminho|porta|classe|endpoint`) e com apenas 5 entradas; o `ia`
deixou de funcionar por completo (list/status/doctor). Correção: restaurado em
JSON com os 20 modelos, base no backup anterior (detalhe em `HANDOFF.md`,
secção "Correção do gestor ia — 2026-11-09").

**Checklist obrigatório para CRIAR/EDITAR o `modelos.conf`:**

1. **Backup antes de tocar:**
   `cp ~/.config/ia/modelos.conf ~/.config/ia/modelos.conf.bak-$(date +%Y%m%d)-<motivo>`
2. **Editar apenas dentro do array JSON**, preservando as entradas existentes.
   Campos por entrada: `alias`, `model_id`, `name`, `unit`, `endpoint`,
   `class` (`GPU`|`CPU`), `exclusive_group` (apenas GPU, `gpu-slot-1`),
   `profile`, `shared` (bool), `startup_timeout` (segundos).
3. **`unit` tem de existir** (`systemctl cat <unit>`) e **`endpoint` tem de
   coincidir com a porta do unit** (`systemctl cat <unit> | grep -- --port`).
4. **Validar antes de fechar a edição:**
   ```bash
   python3 - <<'EOF'
   import json
   raw = open('/home/igor/.config/ia/modelos.conf').read()
   body = '\n'.join(l for l in raw.splitlines() if not l.strip().startswith('#'))
   d = json.loads(body)
   print(f"OK: {len(d)} modelos")
   for m in d:
       print(f"  {m['alias']:20s} -> {m['endpoint']} ({m['class']})")
   EOF
   ```

---

## 3. Modelos — Estado Atual (2026-11-20) com Velocidades Testadas

### GPU — Grupo Exclusivo `gpu-slot-1` (Alternância Obrigatória)

| Alias | Modelo | Porta | Engine | Gen tok/s | VRAM | Status |
|---|---|---|---|---|---|---|
| `qwen36-q4` | qwen36-q4 | 8098 | llama.cpp CUDA + **CPU MoE offload** | **~5.5** (agentic) | ~21 GB | ✅ **TESTADO 6/6 + loop + 45k ctx** |
| `qwen36-q4-strata` | qwen3.6-35b-a3b-q4-xl | 8098 | **Strata 0.1.55** | **~55 curto / ~4.5 longo** | **~22.3 GB** | ✅ **TESTADO: CPU MoE offload, YaRN 100k, KV q4_0, MTP** |
| `qwen36-q3` | qwen36-q3 | 8096 | llama.cpp CUDA | ~35-40 | ~16 GB | Parado (primário GPU) |
| `gyro-s` | qwen38-gyro-s | 8081 | Strata 0.1.55 | ~20-30 | ~21 GB | Inativo |
| `bonsai` | bonsai-27b | 8080 | llama.cpp (PrismML) | 28-48 | ~15 GB | Parado (liberado) |

> **Regra dura:** GPU exclusivo — `ia solo <alias>` para alternar. **Nunca dois simultâneos.**
> **qwen36-q4** usa `--cpu-moe` (offload experts MoE para CPU/RAM) — libera VRAM, mantém performance agentic.
> **qwen36-q4-strata:** mesmo modelo UD-Q4_K_XL (22.9 GB), engine Strata 0.1.55. CPU MoE offload automático via `--gpu-roles 0=main` + `STRATA_PIN_BY_NEED=1`, KV q4_0 (`--kv q4_0`), MTP on. Preset: `qwen36-ud-q4-100k-cpu-offload`. Serviço: `qwen36-q4-strata.service`. Contexto **100k confirmado** (health check: max_context=102400). VRAM ~22.3 GB / 24 GB (97%). Needle in haystack 54k tokens PASS. Prefill 434.7 tok/s. Decode 4.5 tok/s.

### CPU — Todos Ativos Simultaneamente

| Alias | Modelo | Porta | Engine | Gen tok/s | RAM | Status |
|---|---|---|---|---|---|---|
| `maple-pro` | maple-pro 20B-A1B | 8193 | llama.cpp YARN x2 | **~15 curto / ~8 longo** | ~1.3 GB | ✅ **TESTADO 5/5 agentic** |
| `qwen3-30b-a3b` | qwen3-30b-a3b-moe-iq4k | 8109 | ik_llama.cpp + YARN | **~7** | ~21 GB | ✅ **TESTADO 5/5 agentic** |
| `qwen3-1.7b` | qwen3-1.7b | 8103 | llama.cpp | ~40+ | ~1.5 GB | Ativo (validador tools) |
| `qwen2.5-1.5b` | qwen2.5-1.5b | 8105 | llama.cpp | ~45+ | ~1.2 GB | Ativo |
| `lfm2.5-1.2b` | lfm2.5-1.2b | 8104 | llama.cpp | ~50+ | ~1 GB | Ativo (fallback) |
| `phi35-mini` | phi35-mini | 8106 | llama.cpp | ~60+ | ~0.8 GB | Ativo (LAN 192.168.1.170) |
| `bonsai-9b` | bonsai-9b-cpu | 8090 | llama.cpp | ~6 | ~5 GB | Ativo |

> **Destaques CPU (testados 2026-11-20):**
> - **Maple-Pro 20B-A1B YARN (porta 8193):** Contexto 32K → 65K via `--rope-scaling yarn --yarn-ext-factor 2.0`. 5/5 testes agênticos PASS (~14 tok/s). Formato DeepSeek-thinking. Bind: `127.0.0.1:8193` (localhost only).
> - **Qwen3-30B-A3B MoE IQ4_K (porta 8109):** Requer `ik_llama.cpp` compilado. YARN: `-c 65536 --rope-scaling yarn --yarn-ext-factor 2.0 --yarn-orig-ctx 32768`. 5/5 testes agênticos PASS (~7 tok/s).

---

## 4. Comandos

| Comando | Descrição |
|---|---|
| `ia list` | Lista todos os modelos do `modelos.conf` |
| `ia status <alias>` | Status do serviço + health check |
| `ia health <alias>` | Apenas `GET /health` no endpoint |
| `ia on <alias>` | `systemctl start <unit>` |
| `ia off <alias>` | `systemctl stop <unit>` |
| `ia restart <alias>` | `systemctl restart <unit>` |
| `ia solo <alias>` | **GPU:** para modelo atual no `gpu-slot-1` e sobe o solicitado |
| `ia doctor` | Diagnóstico completo (systemd, portas, VRAM, health, modelos.conf) |

### Exemplos GPU (alternância)

```bash
ia solo qwen36-q4        # para qwen36-q3/gyro-s/ttf/bonsai, sobe qwen36-q4 (8098, llama.cpp CPU MoE)
ia solo qwen36-q4-strata # para qwen36-q3/gyro-s/ttf/bonsai, sobe qwen36-q4 Strata (8098, Strata 0.1.55)
ia solo qwen36-q3        # para qwen36-q4/gyro-s/ttf/bonsai, sobe qwen36-q3 (8096, primário)
ia solo gyro-s           # para qwen36-q4/q3/ttf/bonsai, sobe gyro-s (8081, Strata)
ia solo bonsai           # para gyro-s/ttf/qwen36/bonsai, sobe bonsai-27b (8080, PrismML)
```

> **Nota:** `qwen36-q4` e `qwen36-q4-strata` usam a mesma porta (8098) e o mesmo modelo GGUF. O `ia solo` para o serviço ativo antes de subir o solicitado (via `Conflicts=` no systemd). Não rode ambos simultaneamente.

### Exemplos CPU (independentes)

```bash
ia on qwen3-30b-a3b   # sobe Qwen3-30B CPU YARN (porta 8109)
ia on maple-pro       # sobe Maple-Pro YARN (porta 8193)
ia off qwen3-1.7b     # desliga qwen3-1.7b (porta 8103)
ia restart lfm2.5-1.2b # reinicia fallback (porta 8104)
```

---

## 5. Diagnóstico Rápido

```bash
# 1. Verificar modelos ativos e health
ia list
ia doctor

# 2. Verificar systemd
systemctl list-units '*.service' --state=active | grep -E '(qwen|maple|bonsai|gyro|ttf|phi|lfm)'

# 3. Verificar portas ouvindo
ss -ltnp | grep -E '(8080|8081|8096|8098|8103|8104|8105|8106|8108|8109|8193)'

# 4. Validar modelos.conf (JSON)
python3 - <<'EOF'
import json, pathlib
raw = pathlib.Path('/home/igor/.config/ia/modelos.conf').read_text()
body = '\n'.join(l for l in raw.splitlines() if not l.strip().startswith('#'))
data = json.loads(body)
print(f"OK: {len(data)} modelos")
for m in data:
    print(f"  {m['alias']:20s} -> {m['endpoint']} ({m['class']})")
EOF

# 5. Health checks diretos
for port in 8098 8096 8109 8193 8103 8104 8105 8106; do
  curl -s "http://127.0.0.1:$port/health" | head -c 80; echo "  (porta $port)"
done
```

---

## 6. Adicionar Novo Modelo (Checklist)

1. **Service systemd** — `/etc/systemd/system/<model>.service`
   - GPU: `-ngl 99` (offload total), porta livre
   - CPU: `-ngl 0 --threads 20`, porta livre
   - `systemctl daemon-reload && systemctl enable <unit>`

2. **Permissões (sem sudo)** — instalar se novo:
   - `/etc/tmpfiles.d/pcsala.conf` — cria `/run/pcsala` (`igor:igor`)
   - `/etc/polkit-1/rules.d/50-pcsala.rules` — autoriza `igor` a `start|stop`
   - `systemctl restart polkit`

3. **Config do `ia`** — novo objeto em `~/.config/ia/modelos.conf`
   (secção 2), `alias` único e porta livre.

4. **Registo do `pcsala`** — `ModelSpec` em `model_manager.py` + perfil
   em `inference_profiles.py` (mesmo id, porta e perfil) para o worker.

5. **Testar** — `ia list`, `ia status <m>`, `ia doctor`, e depois
   `ia solo <m>` / `ia solo qwen36-q4` para validar a troca nos dois sentidos.

6. **Testes** — actualizar as asserções de conjunto em
   `tests/test_models_laguna.py` e `tests/test_llama_swap.py`.

---

## 7. Ver também

- `guias/GUIA_MESTRE.md` — visão geral da máquina (tabela completa GPU+CPU com velocidades testadas).
- `guias/MANUAL_GESTOR_API.md` — arquitectura do gestor `pcsala`.
- `guias/TUTORIAL_GESTOR.md` — comandos rápidos do `pcsala models`.
- `HANDOFF.md` — estado vivo da máquina (atualizado 2026-11-20).
- `scripts/bench_contexto_max.py` — medições de contexto.
- `scripts/bench_gpu_slot.py` — benchmark GPU slot.