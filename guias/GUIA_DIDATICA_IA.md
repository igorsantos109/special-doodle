# Guia Didático — Gestor de IA (`ia`)

**Data:** 28/10/2026 · **Alvo:** `~/.local/bin/ia` (6 modelos) · **Host:** `pc-sala`

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
    "alias": "nemotron",                 // nome curto usado nos comandos
    "model_id": "nemotron-3.5-30b-gpu",  // id igual ao do pcsala models
    "name": "Nemotron 3.5 Ternary 30B GPU",  // texto de saída
    "unit": "nemotron.service",          // unidade systemd
    "endpoint": "http://127.0.0.1:8083", // health check
    "class": "GPU",                      // GPU | CPU
    "exclusive_group": "gpu-slot-1",     // slot exclusivo (só GPU)
    "profile": "nemotron-ternary-v1",    // perfil de inferência
    "shared": false,                     // true = modelo residente
    "startup_timeout": 180               // segundos à espera do /health
  }
]
```

| Campo | Porque é que importa |
|---|---|
| `alias` | o nome curto que escreves no terminal (`ia on nemotron`) |
| `model_id` | deve coincidir com o `ModelRegistry` do `pcsala models` |
| `unit` | `ia` só sabe actuar na unidade systemd que lhe indicas |
| `endpoint` | se o serviço subir mas não responder, `ia on` avisa |
| `class` | `ia solo` só funciona em `GPU` |
| `exclusive_group` | quem partilha o mesmo slot **não** pode estar carregado ao mesmo tempo |
| `shared` | `ia off` recusa parar modelos partilhados isoladamente |
| `startup_timeout` | tempo de tolerância antes de dizer "iniciado mas sem health" |

### Modelos registados (6)

| alias | model_id | classe | porta | unidade | slot |
|---|---|---|---|---|---|
| `bonsai` | bonsai-27b-gpu | GPU | 8080 | bonsai2-27b.service | gpu-slot-1 |
| `bonsai-cpu` | bonsai-9b-cpu | CPU | 8090 | bonsai2-cpu.service | — |
| `laguna` | laguna-xs-2.1-cpu | CPU | 8091 | laguna.service | — |
| `laguna-gpu` | laguna-xs-2.1-gpu | GPU | 8082 | laguna-gpu.service | gpu-slot-1 |
| `ornith` | ornith-35b-gpu | GPU | 8092 | ornith.service | gpu-slot-1 |
| `nemotron` | nemotron-3.5-30b-gpu | GPU | 8083 | nemotron.service | gpu-slot-1 |

---

## 3. Comandos, um a um

```bash
ia help          # esta ajuda
ia list          # tabela de modelos cadastrados
ia status        # estado de todos (GPU e CPU)
ia status <m>    # estado de um
ia health <m>    # testa o /health do endpoint
ia on <m>        # liga (systemd + espera do health)
ia off <m>       # desliga (GPU exclusivos)
ia restart <m>   # reinicia
ia solo <m>      # troca exclusiva na GPU (com confirmação)
ia doctor        # diagnóstico completo, só leitura
```

### 3.1 Listar

```bash
$ ia list
Alias        Modelo                         Classe Porta   Servico
------------------------------------------------------------------------------------
bonsai       Bonsai 2 27B GPU               GPU   8080    bonsai2-27b.service
bonsai-cpu   Bonsai 2 9B CPU                CPU   8090    bonsai2-cpu.service
laguna       Laguna XS 2.1 CPU              CPU   8091    laguna.service
laguna-gpu   Laguna XS 2.1 GPU              GPU   8082    laguna-gpu.service
ornith       Ornith 1.0 35B GPU             GPU   8092    ornith.service
nemotron     Nemotron 3.5 Ternary 30B GPU   GPU   8083    nemotron.service
```

### 3.2 Ver estado

```bash
$ ia status
=== GPU ===
  bonsai       bonsai2-27b.service    running    funcional    http://127.0.0.1:8080
  laguna-gpu   laguna-gpu.service     stopped    configurado  http://127.0.0.1:8082
  ornith       ornith.service         stopped    configurado  http://127.0.0.1:8092
  nemotron     nemotron.service       stopped    configurado  http://127.0.0.1:8083
=== CPU ===
  bonsai-cpu   bonsai2-cpu.service    running    funcional    http://127.0.0.1:8090
  laguna       laguna.service         stopped    configurado  http://127.0.0.1:8091
```

Significado das colunas:

- **`running` / `stopped`** — estado do serviço systemd.
- **`funcional`** — serviço ligado **e** `GET /health` a devolver 200.
- **`configurado`** — serviço parado (ou a responder mal); pronto a ligar.
- **`só-leitura`** — o `status` não muda nada no sistema.

### 3.3 Saúde de um modelo

```bash
$ ia health nemotron
Nemotron 3.5 Ternary 30B GPU: servico parado (stopped)
```

Quando está ligado devolve `pronto (…)`. Útil para confirmar que a
troca terminou antes de mandares tarefas.

### 3.4 Ligar / desligar

```bash
ia on nemotron        # systemd start + espera até startup_timeout (180 s)
ia off ornith         # stop (só para não-partilhados)
ia restart bonsai
```

`on` só considera sucesso quando **a unidade está ativa E o /health
responde**. Se o serviço subir sem responder, imprime um aviso a dizer
isso mesmo — não confies só no `systemctl is-active`.

### 3.5 `ia solo` — a troca exclusiva da GPU

A Tesla P40 (23 GB) não comporta dois modelos grandes ao mesmo tempo,
por isso `bonsai`, `laguna-gpu`, `ornith` e `nemotron` partilham o slot
`gpu-slot-1`: **só um de cada vez**.

```bash
$ ia solo nemotron
ATENCAO: os seguintes servicos serao interrompidos:
  - Bonsai 2 27B GPU (bonsai2-27b.service)
Confirmar troca exclusiva? (s/N): s
Parando Bonsai 2 27B GPU...
Iniciando Nemotron 3.5 Ternary 30B GPU...
OK: Nemotron 3.5 Ternary 30B GPU pronto (http://127.0.0.1:8083)
```

- Sempre confirma antes; responde `N` (ou Enter) para abortar.
- Só lista quem estiver realmente `running`.
- Se escreveres `solo` para um modelo `CPU`, recusa (`solo` só GPU).
- Variante equivalente: `./pcsala models switch <id>` — essa tem guarda
  de VRAM e regista a operação em SQLite.

### 3.6 `ia doctor` — diagnóstico

```bash
$ ia doctor
=== DIAGNOSTICO ia ===
[nemotron] Nemotron 3.5 Ternary 30B GPU
  servico:   nemotron.service -> stopped
  endpoint:  http://127.0.0.1:8083 -> ...      (só se estiver ligado)
```

Por modelo valida: estado do serviço, resposta do endpoint, se o
**binário** do `ExecStart` existe e se o **GGUF** (`-m …`) existe.
A última execução desta máquina devolveu **0 ocorrências**.

---

## 4. Exemplo completo: usar o Nemotron

```bash
ia status nemotron                     # 1. ver como está
ia solo nemotron                       # 2. trocar a GPU (confirma 's')
ia health nemotron                     # 3. confirmar 'pronto'
ia solo bonsai                         # 4. voltar ao primário
```

Medições (28/10/2026, Tesla P40, `-c 262144 -fa on kv=q8_0`):

| contexto | 8K | 16K | 32K | 66K | 134K | 200K |
|---|---|---|---|---|---|---|
| geração tok/s | 90,8 | 85,1 | 73,3 | 56,2 | 41,4 | 24,9 |
| prefill tok/s | 1454 | 1315 | 1098 | 817 | 537 | 399 |
| prefill | 5,6 s | 12,4 s | 29,8 s | 81,7 s | 248,6 s | 501,7 s |

VRAM constante a **11253 MiB** (o KV de 262144 é pré-alocado) → a
memória aguenta o máximo; o limite é **tempo**: prefill a 262144
estimado em 13–15 min e geração 15–25 tok/s. Recomendação: **≤32K
interactivo**, 64–128K para ingestão de fundo.
Repetir: `python3 scripts/bench_nemotron.py` e `bench_contexto_max.py`.

---

## 5. O que muda para o worker

O serviço do worker arranca com `--profile gpu-triage-v1` (endpoint
8080). Se trocares a GPU para o Nemotron, o perfil **`gpu-triage-v1`
fica sem servidor**: tarefas enfileiradas com esse perfil falham com
`servidor de inferencia indisponivel`.

Antes de trocar, olha para a fila:

```bash
./pcsala list --status QUEUED   # 0 = podes trocar sem prejuízo
./pcsala status <id>
```

Para processar tarefas no Nemotron, submete-as com o perfil dele:

```bash
./pcsala enqueue --prompt "…" --profile nemotron-ternary-v1
```

---

## 6. Problemas frequentes

| Sintoma | Causa | Correcção |
|---|---|---|
| `PermissionError: '/run/pcsala'` em `pcsala models switch` | o directório não existe | `sudo install -D deploy/tmpfiles/pcsala.conf /etc/tmpfiles.d/pcsala.conf && sudo systemd-tmpfiles --create /etc/tmpfiles.d/pcsala.conf` |
| `Access denied … interactive authentication` no `systemctl` | regra polkit ausente ou não compilada | instalar `deploy/polkit/50-pcsala.rules` (comentários **`//`**, nunca `#`) e `sudo systemctl restart polkit`; a unidade tem de estar na `allowed_units` |
| `ERRO: modelo desconhecido` | alias mal escrito ou falta no `modelos.conf` | `ia list`; validar o JSON do `~/.config/ia/modelos.conf` |
| `iniciado mas nao responde health check` | modelo a carregar ou porta errada | `ia health <m>`, `journalctl -u <unit> -n 50`, conferir `endpoint` no config |
| `off` recusa modelo partilhado | `shared: true` (CPU) | esperado; use `pcsala models stop` se precisar |
| `solo` não faz nada | modelo é CPU | `solo` só se aplica a `class: GPU` |

Requisitos para qualquer unidade ser gerida sem sudo: estar instalada em
`/etc/systemd/system/`, **incluída na `allowed_units`** da regra polkit
e o directório do lock existir (ponto 1).

---

## 7. Adicionar um novo modelo (passo a passo)

1. **Binário + pesos** — compilar `llama.cpp` para a GPU (`-DCMAKE_CUDA_ARCHITECTURES=61`)
   e ter o GGUF em `/home/igor/models/…`.
2. **Unidade** — criar `<modelo>.service` (ver `nemotron.service`) com
   `ExecStart`, porta livre e `Restart=on-failure`; `sudo install` +
   `daemon-reload` + `enable`.
3. **Regra polkit** — acrescentar `<modelo>.service` às `allowed_units`
   de `deploy/polkit/50-pcsala.rules` e reinstalar (`restart polkit`).
4. **Config do `ia`** — novo objeto em `~/.config/ia/modelos.conf`
   (secção 2), `alias` único e porta livre.
5. **Registo do `pcsala`** — `ModelSpec` em `model_manager.py` + perfil
   em `inference_profiles.py` (mesmo id, porta e perfil) para o worker.
6. **Testar** — `ia list`, `ia status <m>`, `ia doctor`, e depois
   `ia solo <m>` / `ia solo bonsai` para validar a troca nos dois sentidos.
7. **Testes** — actualizar as asserções de conjunto em
   `tests/test_models_laguna.py` e `tests/test_llama_swap.py`.

---

## 8. Ver também

- `guias/GUIA_MESTRE.md` — visão geral da máquina.
- `guias/MANUAL_GESTOR_API.md` — arquitectura do gestor `pcsala`.
- `guias/TUTORIAL_GESTOR.md` — comandos rápidos do `pcsala models`.
- `guias/DIAGNOSTICO_LAGUNA_ORINTH.md` — diagnóstico específico.
- `scripts/bench_nemotron.py`, `scripts/bench_contexto_max.py` — medições.