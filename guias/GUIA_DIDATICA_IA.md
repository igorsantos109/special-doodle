# Guia Didático — Gestor de IA (`ia`)

**Data:** 28/10/2026 (atualizado 15/11/2026 — 23 modelos + velocidades) · **Alvo:** `~/.local/bin/ia` · **Host:** `pc-sala` (192.168.1.184)

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

## 3. Modelos — Estado Atual (2026-11-15) com Velocidades

### GPU — Grupo Exclusivo `gpu-slot-1` (Alternância Obrigatória)
| Alias | Modelo | Porta | Engine | Gen tok/s | VRAM | Status |
|---|---|---|---|---|---|---|
| `gyro-s` | qwen38-gyro-s | 8081 | Strata 0.1.55 | ~20-30 | ~21 GB | Parado |
| `ttf-qwen38` | ttf-qwen38-27b | 8108 | ttf-home llama.cpp | ~25-35 | ~7.7 GB | Parado |
| `bonsai` | bonsai-27b | 8080 | llama.cpp (PrismML) | 28-48 | ~15 GB | Parado |

> **Regra dura:** Gyro-S (~21 GB) + TTF (~7.7 GB) = ~29 GB > 23 GB VRAM.
> Use `ia solo <alias>` para alternar. **Nunca dois simultâneos.**

### CPU — Todos Ativos Simultaneamente
| Alias | Modelo | Porta | Engine | Gen tok/s | RAM | Status |
|---|---|---|---|---|---|---|
| `qwen3-30b-a3b` | qwen3-30b-a3b-moe-iq4k | 8109 | ik_llama.cpp | **~8** | ~21 GB | ✅ OPERACIONAL |
| `maple-pro` | maple-pro 20B-A1B | 8193 | llama.cpp YARN x2 | **~15 curto / ~8 longo** | ~1.3 GB | ✅ BENCHMARK |
| `qwen3-1.7b` | qwen3-1.7b | 8103 | llama.cpp | ~40+ | ~1.5 GB | Ativo |
| `qwen2.5-1.5b` | qwen2.5-1.5b | 8105 | llama.cpp | ~45+ | ~1.2 GB | Ativo |
| `lfm2.5-1.2b` | lfm2.5-1.2b | 8104 | llama.cpp | ~50+ | ~1 GB | Ativo |
| `phi35-mini` | phi35-mini | 8106 | llama.cpp | ~60+ | ~0.8 GB | Ativo |
| `bonsai-9b` | bonsai-9b-cpu | 8090 | llama.cpp | ~6 | ~5 GB | Ativo |

> **Destaques CPU:**
> - **Qwen3-30B-A3B MoE IQ4_K (porta 8109):** Requer `ik_llama.cpp` compilado (vanilla llama.cpp NÃO suporta imatrix IQ4_K). Service: `-c 32768 --threads 20 -ngl 0 --parallel 2 --jinja`
> - **Maple-Pro 20B-A1B YARN (porta 8193):** Contexto 32K → 65K via `--rope-scaling yarn --yarn-ext-factor 2.0`. Benchmark agêntrico 5/7 = 71%. Formato DeepSeek-thinking (`reasoning_content` + `content` separados). Bind: `127.0.0.1:8193` (localhost only).

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
ia solo gyro-s      # para ttf-qwen38/bonsai, sobe gyro-s (porta 8081)
ia solo ttf-qwen38  # para gyro-s/bonsai, sobe ttf-qwen38 (porta 8108)
ia solo bonsai      # para gyro-s/ttf-qwen38, sobe bonsai-27b (porta 8080)
```

### Exemplos CPU (independentes)
```bash
ia on qwen3-30b-a3b   # sobe Qwen3-30B CPU (porta 8109)
ia on maple-pro       # sobe Maple-Pro YARN (porta 8193)
ia off qwen3-1.7b     # desliga qwen3-1.7b (porta 8103)
```

---

## 5. Diagnóstico Rápido

```bash
# 1. Verificar modelos ativos e health
ia list
ia doctor

# 2. Verificar systemd
systemctl list-units '*.service' --state=active | grep -E '(qwen|maple|bonsai|gyro|ttf|nemotron|laguna|ornith|phi|lfm)'

# 3. Verificar portas ouvindo
ss -ltnp | grep -E '(8080|8081|8082|8083|8090|8091|8092|8093|8103|8104|8105|8106|8108|8109|8193)'

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
for port in 8081 8108 8109 8193; do
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
   `ia solo <m>` / `ia solo bonsai` para validar a troca nos dois sentidos.

6. **Testes** — actualizar as asserções de conjunto em
   `tests/test_models_laguna.py` e `tests/test_llama_swap.py`.

---

## 7. Ver também

- `guias/GUIA_MESTRE.md` — visão geral da máquina (tabela completa GPU+CPU com velocidades).
- `guias/MANUAL_GESTOR_API.md` — arquitectura do gestor `pcsala`.
- `guias/TUTORIAL_GESTOR.md` — comandos rápidos do `pcsala models`.
- `HANDOFF.md` — estado vivo da máquina (atualizado 2026-11-15).
- `scripts/bench_nemotron.py`, `scripts/bench_contexto_max.py` — medições.
- `scripts/bench_gpu_slot.py` — benchmark GPU slot.