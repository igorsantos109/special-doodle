# Changelog — pc-sala-agent

Todas as alterações relevantes deste repositório.
Formato inspirado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/).

Comparações entre versões seguem os commits do repositório; os números
citados foram obtidos com `git diff --stat` e com medições no hardware
(Tesla P40), não de memória.

---

## [1.1] — 2026-10-28

**Base:** versão anterior `8cb6269` (2026-10-24) → `e557d5d` (2026-10-28),
mais esta entrada.
**Dimensão:** 95 ficheiros, +6502 / −6853 (`git diff --stat 8cb6269..e557d5d`)
· **suíte:** 498 testes.

### Adicionado

- **Modelo Ternary-Nemotron-3.5-Lightning-30B-A3B (Q2_0)** — `nemotron_h_moe`,
  8,82 GiB, SHA-256 `38854de6…4f3`:
  - `nemotron.service` (porta **8083**, `--host 0.0.0.0`, `-c 262144`,
    `-fa on`, KV `q8_0`, `--reasoning off`), `exclusive_group gpu-slot-1`;
  - perfil `nemotron-ternary-v1` em `inference_profiles.py`;
  - entrada `nemotron-3.5-30b-gpu` no `ModelRegistry` (`model_manager.py`);
  - registo no gestor diário `ia` (`~/.config/ia/modelos.conf`, não versionado);
  - testes `tests/test_model_nemotron.py`.
- **`deploy/tmpfiles/pcsala.conf`** — cria `/run/pcsala` (directório do lock
  de troca de GPU) no arranque; sem ele o `switch` falhava com
  `PermissionError: '/run/pcsala'`.
- **`deploy/polkit/50-pcsala.rules`** — permite a `igor` gerir as unidades
  de modelo sem `sudo` (ficheiro novo; não existia).
- **`scripts/bench_nemotron.py`** e **`scripts/bench_contexto_max.py`** —
  medições de tk/s por tarefa/contexto, com a baseline da P40 documentada.
- **`guias/GUIA_DIDATICA_IA.md`** — guia didático do gestor `ia`
  (config campo a campo, todos os comandos com saída real, troca exclusiva,
  diagnóstico, problemas frequentes, como adicionar um modelo).
- **`migrations/006_model_vram_reservations.sql`** — tabelas `model_vram` e
  `model_reservations` (esquema passa a `1..6`).
- Módulos vindos da árvore 1.1: `cli.py`, `gpu_monitor.py`, `model_vram.py`,
  `models/client.py` (llama-swap).
- `deploy/llama-swap/config.yaml`, `deploy/systemd/llama-swap.service`,
  `docs/llama-swap-piloto.md`, `docs/medicoes.md`, `docs/permissoes.md`,
  `DIAGNOSTICO.md`, `pyproject.toml`, `.github/workflows/ci.yml`,
  unidades `bonsai-4b-gpu.service` / `bonsai2-4b-gpu.service`.
- Testes novos: `test_fila_isolada.py` (515 linhas — percurso da fila com
  CLI/worker em subprocesso e servidor falso), `test_vram.py`,
  `test_llama_swap.py`, `tests/conftest.py`.
- Comando **`pcsala models vram`** e **`pcsala models gen-llama-swap`**.

### Alterado

- **Base de código substituída pela árvore 1.1** (`ialocalagent` `8f8f9b1`):
  `src/` e `tests/` espelhados. `model_manager.py` 726→428 linhas,
  `graph_runner.py` 333→244, e reescrita de `real_graph.py`,
  `inference_adapter.py`, `context_budget.py`, `sessions.py`, etc.
- **Worker de fila reimplementado sobre a 1.1** (a 1.1 só tinha executores
  one-shot):
  - `graph_runner.py`: `--queue-mode` + `QueuePollCycle` + `_ensure_scope()`
    (a 1.1 validava o escopo em vez de o criar);
  - `task_queue.py`: `reconcile` adaptado ao formato de artefacto da 1.1
    (`step="concluir"`, chave `model`) e **sem re-inferência**;
  - `queue_cli.py`: substituído pelo da produção — saída JSON,
    `cancel` apenas de `QUEUED`, `reconcile` a partir do grafo.
- **Perfis por ambiente**: `inference_profiles.py` 37→83 linhas, com
  `PCSALA_ENDPOINT_*` / `PCSALA_MODEL_*` (default intacto) — necessários para
  o teste isolado não tocar no endpoint real.
- **`nemotron.service` alinhado com a produção** (o bonsai faz o mesmo):
  `--host 127.0.0.1` → `0.0.0.0` (LAN), `--no-jinja` removido e
  `--reasoning off` acrescentado — ver *Corrigido*.
- Documentação: `GUIA_MESTRE` v8.2→v8.3, `MANUAL_GESTOR_API.md`,
  `TUTORIAL_GESTOR.md`, `README.md`, `PROJECT_STATE.md`.

### Corrigido

- **A regra polkit nunca compilava.** Usava comentários `#` (estilo shell) —
  o polkit compila JavaScript e registava
  `SyntaxError: invalid token (line 1)`, ignorando o ficheiro em silêncio —
  e usava `action.subject` (o processo) em vez de `action.lookup("unit")`.
  Resultado: `systemctl stop/start` como `igor` devolvia
  "Access denied … requires interactive authentication". Corrigido
  (`//`, `action.lookup("unit")`) e `nemotron.service` acrescentada à
  `allowed_units`.
- **`/run/pcsala` não existia** → `pcsala models switch` morria com
  `PermissionError`. Criado por tmpfiles (acima).
- **Nemotron inacessível da LAN**: só escutava em `127.0.0.1` → corrigido
  para `0.0.0.0` e **porta 8083 acrescentada ao firewall** (`nft inet
  pcsala_api`, 3 regras, e `ufw allow from 192.168.0.0/16`). Antes:
  `192.168.1.184:8083` → `000`; depois → `200`, inclusive forçando
  `--interface enp6s0`.
- **`tools` devolvia HTTP 500** `"tools param requires --jinja flag"`
  (a unidade tinha `--no-jinja`) → removido; agora devolve
  `finish_reason=tool_calls` com `tool_calls` preenchidos.
- **Thinking comia todo o `maxTokens`** (`content=''`,
  `finish_reason=length`) → `--reasoning off`; respostas voltam a trazer
  `message.content` por omissão, e o thinking liga-se pontualmente com
  `chat_template_kwargs.enable_thinking=true` (verificado, 200).
- **Testes dependentes do ambiente**: o health check assumia a 8080 livre
  (nesta máquina está a servir) e `test_vram` falava com o `systemctl`
  **real** — com a polkit já activa, a suíte teria **parado a unidade da
  produção**. Ambos tornados deterministas (recusa explícita de `urlopen`,
  `systemctl` falso injectado).

### Removido

- `src/pcsala_agent/controlled_real.py`
- `src/pcsala_agent/execution_runner.py`
- `src/pcsala_agent/inference_profiles.py.bak`
- `tests/test_controlled.py`
- `tests/test_execution_acceptance.py`
- `tests/test_models_laguna.py.bak`

### Migrações e operação

- Esquema `1..6`; a 006 foi aplicada a `/var/lib/pcsala-worker/state.sqlite`
  com backup automático (`state.sqlite.bak`).
- `.venv` reconstruído a partir de `requirements.lock` (45 pacotes, hashes
  válidos) — estava vazio.
- Fila **preservada** no corte: `COMPLETED 10`, `RESERVED 3` (ids 6/14/15),
  `FAILED 2`, `CANCELLED 1`, `QUEUED 0`.
- O modelo por omissão continua o `bonsai-27b-gpu` (8080). `bonsai` e
  `nemotron` são **mutuamente exclusivos**: VRAM 12 899 + 11 189 = 24 088 MiB
  > 23 040 MiB da P40, além do `exclusive_group="gpu-slot-1"`. Não é
  conflito de portas (8080 ≠ 8083).
- Troca de modelo: `ia solo <alias>` (diário, com confirmação) ou
  `./pcsala models switch <id>` (auditado, com guarda de VRAM).

### Regressões conhecidas

- `PCSALA_MODELS_CONFIG` e `PCSALA_API_KEY_FILE` (introduzidas em `2f0af3c`
  para sobrepor o registry de modelos e a chave por ambiente) **perderam-se
  no corte para a 1.1**, cujo `ModelRegistry` voltou a ser fixo em código.
  Quem dependa dessas variáveis fica sem efeito. `PCSALA_ROOT`,
  `PCSALA_BACKUP_DIR` e `PCSALA_ENDPOINT_*` mantêm-se funcionais.

### Desempenho medido (Nemotron, P40, `-c 262144`, `kv q8_0`)

| contexto | curto | 8K | 32K | 66K | 134K | 200K |
|---|---|---|---|---|---|---|
| geração tok/s | 100,2 | 90,8 | 73,3 | 56,2 | 41,4 | 24,9 |
| prefill tok/s | — | 1454 | 1098 | 817 | 537 | 399 |

VRAM constante a 11 253 MiB (KV pré-alocado). Extrapolado a 262 144:
prefill 13–15 min, geração 15–25 tok/s → **recomendado ≤32K para uso
interactivo**, 64–128K para ingestão de fundo. Qualidade: boa em leitura,
RAG, síntese e dedução; **instável em aritmética** (a mesma conta deu 176
numa execução e 191 noutra) e validação espontânea de restrições.

### Notas

- `pyproject.toml` continua em `1.0.0` (o rótulo "1.1" designa a árvore de
  trabalho, não uma versão de pacote).
- Rollback: `git revert` dos commits desta entrada; o estado anterior está
  preservado em `pc-sala-preserve/` (bundle de `3f57029` + `state.sqlite`
  pré-006).

---

## [1.0] — 2026-10-24

Versão anterior em produção, base `8cb6269`: fila persistente com worker
contínuo, CLI `pcsala` (enqueue/list/status/cancel/reconcile/health/backup/
models), modelo `bonsai-27b-gpu` em 8080 como principal do perfil
`gpu-triage-v1`, gestor de modelos com troca exclusiva de GPU.
