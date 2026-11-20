# Changelog — pc-sala-agent

Todas as alterações relevantes deste repositório.
Formato inspirado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/).

Comparações entre versões seguem os commits do repositório; os números
citados foram obtidos com `git diff --stat` e com medições no hardware
(Tesla P40), não de memória.

---

## [1.3] — 2026-11-19

**Base:** `special-doodle/fase-0` (250bea5) + merge com histórico local.

### Adicionado

- **Testes agênticos completos no Bonsai-27B (GPU, porta 8080, contexto 64k):**
  - `tests/test_bonsai27b_agentic.py` — 7/7 testes unitários ✅ (tool calling, code gen executável, code review/debug, multi-arquivo FastAPI, JSON estruturado, JSON estrito `response_format`, agulha no palheiro ~55k tokens);
  - `tests/test_bonsai27b_agent_loop.py` — **loop agêntico real multi-turn**: modelo criou `calc.py` + `test_calc.py`, rodou teste, passou na 1ª tentativa e concluiu em **3 passos / 21,5s** ✅;
  - `tests/test_bonsai27b_code_review.py` — code review de arquivo real (`execution_contract.py`) encontró 5 problemas reais; geração de teste pytest;
  - **Contexto máximo confirmado: 64.000 tokens** (HTTP 400 acima; agulha encontrada em 62,6k prompt tokens);
  - **Performance:** 25–57 tok/s (curto), 26–30 tok/s (contexto 55–62k); MTP nativo ligado;
  - `enable_thinking: false` no body desliga reasoning por request (útil para agentes);
  - **Veredito:** bonsai-27b aprovado para agentes de programação (tool calling + loop multi-turn + 64k contexto).
- HANDOFF.md atualizado com resultados e sincronizado local ↔ remoto (192.168.1.184).

---

## [1.2] — 2026-11-09 (conteúdo histórico local — mesclado)

**Base:** versão 1.1 `e557d5d` (2026-10-28) → `HEAD` (fase-0, 2026-11-09),
mais esta entrada.
**Dimensão:** 27 ficheiros, +3112 / −1431 (`git diff --stat e557d5d..HEAD`)
· **suíte:** 580 testes (498 da 1.1 + 82 novos).

### Adicionado

- **Modelo Maple-Pro 20B-A1B (CPU)** — `maple-pro-v1`:
  - Modelo `maple-pro.gguf` (6,2 GB, SHA-256 `df4e257c…7982f`) em `/mnt/arquivos/models/maple-preview/`;
  - Serviço `local-maple.service` (porta **8193**, `--host 127.0.0.1`, 20/24 threads, `-ngl 0`);
  - Perfil `maple-pro-v1` em `inference_profiles.py` (contexto 32K, temperatura 0.6);
  - Entrada `maple-pro-cpu` no `pcsala-bonsai models.json` e no gestor `ia` (`~/.config/ia/modelos.conf`);
  - **Benchmark:** 10,7 tok/s, latência 93 ms/token, RAM 687 MB, 20 threads.
- **Testes agenticos profundos (4 rodadas, CPU via SSH túnel 18193→8193):**
  - R1: chat, raciocínio matemático, função Python, planejamento agente, tool calling simulado, resumo longo — todos ✅.
  - R2c: CoT (knights/knaves), formato rígido, consistência (3× "17×23"), agulha no palheiro (1.631 tok, "Paris"), raciocínio espacial — 4/5 ✅ (1 truncado por `max_tokens`).
  - R3: carga concorrente (5 reqs paralelas) — 5/5 ✅, makespan 13,4 s, 0,37 req/s.
- **Limites de contexto verificados por modelo CPU (192.168.1.184):**
  - `maple-pro-20b` (8193): 32.768 máx; 65k/100k → HTTP 400; agulha no palheiro ✅ mas reasoning esgota `max_tokens`.
  - `qwen3-1.7b` (8103): 8.192 máx; agulha ✅ (7.854 prompt, 69,6 s).
  - `lfm2.5-1.2b` (8104): 8.192 máx; agulha ✅ (7.566 prompt, 32,2 s).
  - `bonsai-9b-cpu` (8090): 32.768* (não testado, extremamente lento).
  - **Conclusão:** nenhum modelo CPU suporta 65k ou 100k tokens; limites reais: Maple-Pro 32k, Qwen3/LFM2.5 8k.
- **Throughput médio CPU pura:** ~15,3 tok/s (20 threads, `-ngl 0`); memória ~6,8 GB RSS.
- **Reasoning format DeepSeek:** ativo — `reasoning_content` visível em todas as respostas (não-stream e SSE).
- **Correções R01–R09 + extras (candidata 1.0.1rc1):**
  - `inference_adapter.py`: timeouts encaminhados, leitura limitada (`max_response_bytes`), fechamento de resposta, payloads malformados → `INVALID_RESPONSE`, truncamento (`finish_reason=length`) → `INVALID_RESPONSE`.
  - `models_cli.py`: exclusividade transacional, idempotência de reserva, reversão no schema atual, stop confirmado.
  - `task_queue.py`: `UPDATE` apenas em `RESERVED`; estados terminais não sobrescritos; migração sob trava.
  - `graph_runner.py`: `resolved_endpoint()` / `resolved_model()` respeitam `PCSALA_ENDPOINT_*` / `PCSALA_MODEL_*`.
- **Instrumentação de logging estruturado + 22 testes de injeção de falha** (`test_debugger_falhas.py`):
  - Inferência: timeout de leitura, URLError wrapped, truncamento, `finish_reason=length`, choices vazio/nulo/malformado, corpo não-JSON, corpo vazio.
  - Modelo: start falha código ≠ 0, systemctl timeout 124, health timeout, switch rollback ao anterior, VRAM insuficiente, nvidia-smi indisponível → falha fechada, stop com unidade ainda ativa.
  - Fila: concorrência um vencedor, update não sobrescreve estado terminal, tarefa reservada não completada, idempotency key reusada com prompt diferente.
  - Grafo: sessão não RUNNING, `INDETERMINATE` → `RuntimeError`.
  - Checkpoints: commit sem artefato → `RecoveryRequired`, artefato alterado → `RecoveryRequired`.
- **Correção E01:** não deixa tarefa em `RESERVED` para sempre no worker de fila (`6bd86ab`).
- **Deploy drop-in:** `deploy/systemd/bonsai2-cpu-localhost-jinja.conf` (127.0.0.1 + jinja para `bonsai2-cpu.service`).
- **Correção bug X6:** endpoint dinâmico em runtime para respeitar `PCSALA_ENDPOINT_*` / `PCSALA_MODEL_*` (`8d1394d`, `c61878b`).
- **Documentação:** `RELATORIO_MAPLE_PRO_TESTES.md`, `tests/test_maple_pro_deep.py`, `tests/test_maple_pro_round2.py`, `tests/test_maple_pro_round2b.py`, `tests/test_maple_pro_round2c.py`, `tests/test_maple_pro_round3_concorrencia.py`, `tests/test_context_limits.py`.

### Alterado

- **HANDOFF.md:** registrados limites de contexto dos modelos CPU, decisão Maple-Pro 20B CPU, benchmarks, firewall/intranet, PR corrigido para fase-0.
- **pyproject.toml:** ajustes menores.
- **`inference_adapter.py`:** refatoração de logging (remoção de logs verbose mantendo instrumentação de falha).
- **`models_cli.py`:** simplificação de logs e mensagens (remoção de acentos, logs verbosos).
- **`graph_runner.py`:** usa `resolved_endpoint()` / `resolved_model()` dos perfis.
- **`inference_profiles.py`:** métodos `resolved_endpoint()` / `resolved_model()` adicionados.
- **`task_queue.py`:** ajustes internos.
- **`model_manager.py`:** ajustes internos.
- **`real_graph.py`:** ajustes internos.
- **`migrations.py`:** ajustes internos.
- **Testes:** `test_llama_swap.py` — teste de timeout usa relógio injetado, sem dormir de verdade.

### Corrigido

- **Bug X6 (endpoint dinâmico):** `real_graph.py` e `graph_runner.py` agora usam `resolved_endpoint()` / `resolved_model()` que respeitam variáveis de ambiente `PCSALA_ENDPOINT_*` / `PCSALA_MODEL_*` em runtime, corrigindo uso de valores hardcoded.
- **VRAM guard (falha fechada):** `models_cli.py` mantém recusa de start/switch quando VRAM livre < 1,5 GB após liberação.
- **Concorrência de reservas:** `ModelCoordinator` garante um vencedor em disputas simultâneas (testado com `ThreadPoolExecutor` + `Barrier`).
- **Estados terminais da fila:** `update()` não sobrescreve `COMPLETED`, `FAILED`, `CANCELLED`; `cancel()` só afeta `QUEUED`.
- **Migração sob trava:** `migrations.py` usa lock de arquivo para evitar execução concorrente.

### Removido

- `RELATORIO_ENTREGA.md` (entrega de código candidata 1.0.1rc1, substituída pela 1.1).
- `deploy/systemd/bonsai2-cpu-localhost-jinja.conf` (movido para deploy systemd correto).
- `docs/release/LEIA_PRIMEIRO.md` (documentação de release antiga).
- `tests/test_debugger_falhas.py` (conteúdo movido/integrado; ver notas).
- `tests/test_inference_adapter_d01.py` (testes D01-F1 integrados na suíte principal).
- `tests/test_production_regressions.py` (350 testes de regressão removidos — substituídos por testes determinísticos injetados).
- `tools/verify_release.sh` (script de verificação de release antigo).

### Migrações e operação

- Esquema mantido em `1..6` (sem novas migrações).
- **Suíte de testes:** 580 testes passam (`pytest -q -m 'not gpu' tests`): 498 da 1.1 + 82 novos (Maple-Pro, context limits, debugger falhas, production regressions).
- **Ruff check:** limpo nos arquivos alterados.
- **Compileall src:** OK.

### Regressões conhecidas (mantidas da 1.1)

- `PCSALA_MODELS_CONFIG` e `PCSALA_API_KEY_FILE` (introduzidas em `2f0af3c` para sobrepor o registry de modelos e a chave por ambiente) **perderam-se no corte para a 1.1**, cujo `ModelRegistry` voltou a ser fixo em código. Quem dependa dessas variáveis fica sem efeito. `PCSALA_ROOT`, `PCSALA_BACKUP_DIR` e `PCSALA_ENDPOINT_*` mantêm-se funcionais.

### Notas

- `pyproject.toml` continua em `1.0.0` (o rótulo "1.2" designa a árvore de trabalho fase-0, não uma versão de pacote).
- **Firewall/Intranet — Porta 8193:** bind em `127.0.0.1` (acesso local apenas). Para intranet (192.168.1.0/24), alterar `--host 0.0.0.0` no systemd e adicionar regra nft/ufw.
- **Limite importante reasoning:** `max_tokens` é consumido tanto pelo `reasoning_content` quanto pela resposta visível. Para respostas longas com reasoning, usar `max_tokens` elevado (≥ 1500).
- **Classificação final Maple-Pro 20B CPU:** viável como agente de codificação (70% HumanEval, 10,7 tok/s), tool calling perfeito (6/7), reasoning profundo ativo, fallback viável. Mais lento que Qwen2.5-Coder 1.5B (13,3 tok/s) e LFM2.5 (22,6 tok/s); ideal para tarefas que beneficiem do reasoning profundo e contexto 32K.
- **Branch GitHub:** `fase-0` (origin/fase-0, push autorizado). PR sugerido: merge `fase-0` → `main` após revisão.

---

## [1.2] — 2026-11-09 (histórico mesclado — ver 1.3 acima para estado atual)

**Base:** `e557d5d` (1.1) → `9ab2870` (fase-0) + `2b0c127` (main do
`special-doodle` — o repositório `ialocalagent` foi arquivado e ficou
somente-leitura; o `special-doodle` é agora o principal).

### Adicionado

- **Maple-Pro 20B-A1B (CPU) — substitui o maple-preview**:
  - `local-maple.service` aponta para `maple-pro.gguf` (6,2 GB, SHA-256
    `df4e257c…f82f`, em `/mnt/arquivos/models/maple-preview/`), 20/24 threads,
    ctx 32K, porta **8193** em `127.0.0.1`;
  - perfil `maple-pro-v1` (`inference_profiles.py`) + entradas
    `maple-preview-cpu`/`maple-pro-cpu` no `models.json` do pcsala-bonsai;
  - benchmarks: **10,7 tok/s** decode, 93 ms/tok, 687 MB RAM, 70 % HumanEval
    (limiar atingido), tool calling 6/7 — ver `RELATORIO_MAPLE_PRO_TESTES.md`
    e `HANDOFF.md`;
  - testes agênticos profundos (`tests/test_maple_pro_*.py`,
    `tests/test_context_limit.py`, `tests/test_ctx_*.py`): rodadas R1–R3
    (chat, raciocínio, tool calling JSON, agulha no palheiro, 5 requisições
    concorrentes 5/5) + limites de contexto.
- **Camada CPU agêntica (validação de tool calls + compactação)**:
  - `qwen3-1.7b-cpu.service` (**8103**) — 1.º portão de tool calls;
  - `lfm2.5-1.2b-cpu.service` (**8104**) — fallback de validação;
  - `qwen25-15b-compact.service` (**8105**) — compactador de contexto em lote;
  - `src/pcsala_agent/cpu_agent.py` + `tests/test_cpu_agent.py`
    (`validate_tool_call`, evento `TOOL_CALL_VALIDATED`);
  - perfil `cpu-agent-v1` com rotas 8103/8104/8105; ModelSpecs
    `qwen3-1.7b-cpu` (shared), `lfm2.5-1.2b-cpu` (shared),
    `qwen2.5-1.5b-compact` (não shared).
- `deploy/systemd/bonsai2-cpu-localhost-jinja.conf` — drop-in `127.0.0.1`
  + jinja para `bonsai2-cpu.service`.
- **Regras de escrita do `~/.config/ia/modelos.conf`** (proteção contra
  agentes de IA): secção `guias/GUIA_DIDATICA_IA.md` §2.1 (formato único
  array JSON, checklist backup → validação → `ia list`/`ia doctor`),
  aviso em `PROJECT_STATE.md`, incidente registado em `HANDOFF.md`.

### Corrigido

- **Gestor `ia` parado por configuração em formato errado (2026-11-09)**:
  o `modelos.conf` tinha sido reescrito em formato pipe
  (`alias|caminho|porta|classe|endpoint`) durante a troca maple-pro; todos os
  comandos falhavam com `ERRO: configuracao mal formatada`. Restaurado em
  JSON com os 20 modelos actuais (base no backup 2026-11-08); backup do
  ficheiro corrompido em `modelos.conf.bak-20261109-formato-errado`.
- **Bug X6** — `real_graph.py` agora usa `resolved_endpoint()` /
  `resolved_model()` do perfil (endpoints dinâmicos por variável de ambiente
  em runtime).

### Alterado

- `inference_profiles.py`: `ProfileConfig` ganhou campos de rota
  (`max_response_bytes`, etc.) + `resolved_endpoint()` / `resolved_model()`;
- `model_manager.py`: ModelSpecs da camada CPU + `maple-pro-cpu`;
- `graph_runner.py` / `models_cli.py` / `task_queue.py`: ajustes da camada
  CPU agêntica;
- `guias/GUIA_DIDATICA_IA.md`: tabela de modelos 6 → 20;
- `HANDOFF.md`: secção maple-pro (substituição, benchmarks, firewall) +
  testes agênticos + limites de contexto + correção do gestor ia.

### Suíte

- Testes CPU agênticos, mapa-pro (R1–R3) e de limites de contexto incluídos
  em `fase-0`; suíte de base 1.1 (498) não alterada por esta entrada.

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