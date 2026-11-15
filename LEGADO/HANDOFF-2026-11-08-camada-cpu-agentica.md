# HANDOFF — Camada CPU agentica (Qwen3-1.7B / LFM2.5-1.2B / Qwen2.5-1.5B)

Data: 2026-11-08 ~06:45 · Máquina: PC-SALA (Tesla P40 23 GB, Xeon E5-2678 v3 12c/24t, 53 GB RAM)
Repo: `/home/igor/pc-sala-agent` (branch de trabalho, **nada commitado por mim**)

## 0. Pedido original e o que foi decidido

Plano do utilizador: camada CPU nova com 3 modelos, `-ngl 0`, registados no
`pcsala models`, perfil `cpu-agent-v1` com regras de roteamento, units systemd,
`pcsala health` a reportar CPU, `pcsala models vram` a excluir CPU, e no worker:
GPU gera plano → Qwen3-1.7B valida/despacha → rejeição cai para LFM2.5-1.2B →
só tool calls validadas executam → acima de 16K tokens o Qwen2.5-1.5B compacta
em lote com registo no audit trail.

Desvios obrigatórios face ao plano (verificados no terreno):

| Plano | Estado real | Escolha |
|---|---|---|
| porta **8094** (Qwen3-1.7B) | **ocupada** por `/etc/systemd/system/flint.service` (GPU) | **8103** |
| porta **8095** (LFM2.5) | **reservada ao Strata** (`guias/GUIA_API_LOCAL.md:78`, comentários de `glm47-flash.service` e `qwen36-q3.service`) | **8104** |
| engine `ik_llama.cpp` | **não existe** nenhum build de ik_llama.cpp na máquina | build CPU da casa: `/home/igor/opt/prism-cpu-install-aswyUW/install/bin/llama-server` (PrismML llama.cpp, commit `73bfe6c`) — é o mesmo binário do `bonsai2-cpu.service` e **é o único build CPU com a arquitectura `lfm2`** (oficial `~/opt/llama.cpp` `3c809f4` não tem) |
| compactador sem serviço contínuo | — | unit `qwen25-15b-compact.service` **instalada mas sem `[Install]`** (estado `static`), arrancada/parada por `cpu_agent.compact_context()`; redes de segurança `RuntimeMaxSec=900s` + `MemoryMax=4G` + `Restart=no` |

Porta 8105 = compactador. Tudo **loopback (`127.0.0.1`)** → nenhuma alteração de
nft/ufw é necessária (`/etc/pcsala-bonsai-api.nft` faz drop por omissão).
8101/8102 já estavam tomadas por outra sessão (flint-ternary / fusion4).

## 1. Feito e VERIFICADO

### 1.1 Pesos (descarregados e com tamanho confirmado)
| Modelo | Ficheiro | Bytes | Origem HF |
|---|---|---|---|
| Qwen3-1.7B Q4_K_M | `/mnt/arquivos/models/qwen3-1.7b-cpu/Qwen3-1.7B-Q4_K_M.gguf` | 1 107 409 472 | `unsloth/Qwen3-1.7B-GGUF` |
| LFM2.5-1.2B-Instruct Q4_K_M | `/mnt/arquivos/models/lfm2.5-1.2b-cpu/LFM2.5-1.2B-Instruct-Q4_K_M.gguf` | 730 895 168 | `LiquidAI/LFM2.5-1.2B-Instruct-GGUF` |
| Qwen2.5-1.5B-Instruct q4_k_m | `/mnt/arquivos/models/qwen2.5-1.5b-compact/qwen2.5-1.5b-instruct-q4_k_m.gguf` | 1 117 320 736 | `Qwen/Qwen2.5-1.5B-Instruct-GGUF` |

Symlinks criados (padrão da casa): `~/models/qwen3-1.7b-cpu`, `~/models/lfm2.5-1.2b-cpu`,
`~/models/qwen2.5-1.5b-compact` → `/mnt/arquivos/models/...`.

### 1.2 Units (ficheiros no repo **e** instaladas em `/etc/systemd/system`)
`qwen3-1.7b-cpu.service` (8103, enabled+active), `lfm2.5-1.2b-cpu.service`
(8104, enabled+active), `qwen25-15b-compact.service` (8105, static/inactive).
Flags: `-ngl 0 --threads 12 --no-kv-offload --parallel 1 --jinja --reasoning off
--reasoning-format none`; validador/fallback `-c 8192 -n 512`; compactador
`-c 32768 -n 1024`. Load medido ~3 s cada.

Prova de fogo real (via `cpu_agent`, serviços vivos):
```
rotas: http://127.0.0.1:8103  http://127.0.0.1:8104  http://127.0.0.1:8105  qwen25-15b-compact.service
legitima                 aprovada    stage=validador conf=0.95  4.72s
ferramenta inventada     rejeitada   stage=estrutura conf=0.00  0.00s  (sem rede)
arguments malformados    rejeitada   stage=estrutura conf=0.00  0.00s  (sem rede)
```
n_ctx servido: 8192 (treino 40 960 no Qwen3 / 128 000 no LFM2.5).

### 1.3 Codigo escrito (13 ficheiros modificados + 4 novos, tudo por commitar)
- **`src/pcsala_agent/cpu_agent.py`** (novo) — o portao:
  `routing_for(profile)`, `validate_tool_call(profile|cfg, prompt_text, tool_call,
  tools, _urlopen, _systemctl)`, `compact_context(...)`, `record_event(db, session,
  tipo, details)`, helper `_token_ids`/`_detokenize` (`/tokenize`, `/detokenize?prompt=true`).
  Constantes: `DEFAULT_CONFIDENCE_FLOOR=0.6`, `DEFAULT_COMPACT_THRESHOLD=16384`,
  `RECENT_TAIL_TOKENS=2048`, `VALIDATOR_TIMEOUT=30`, `COMPACTOR_TIMEOUT=180`,
  `COMPACTOR_HEALTH_WAIT=60`, `VERDICT_APPROVED/REJECTED/UNAVAILABLE`.
  Politica: checagem **estrutural local** primeiro (ferramenta fora do catálogo /
  `arguments` não-JSON → rejeição imediata, zero rede); rejeição do validador **sobe
  ao fallback** (segunda opinião); endpoint morto ⇒ passa à etapa seguinte; ninguém
  respondeu ⇒ `indisponivel` (falha fechada). Compactação 100 % fail-closed: qualquer
  erro devolve o prompt intacto com `reason`.
- `inference_profiles.py` — `ProfileConfig` ganhou campos de rota (todos com default
  seguro ⇒ perfis antigos intactos): `validator_endpoint/_model`, `fallback_endpoint/_model`,
  `compactor_endpoint/_model/_unit`, `tools`, `confidence_floor`,
  `compact_threshold_tokens`, `compact_keep_tokens`; o `field_validator` de endpoint
  passa a validar os 4 endpoints (vazio é aceite). Perfil **`cpu-agent-v1`** declarado:
  endpoint primário **8096** (qwen36 Q3, `timeout_seconds=600`,
  `max_response_bytes=262144`, `system_prompt=STRATA_SYSTEM_PROMPT`) + rotas 8103/8104/8105.
  Overrides por env: `PCSALA_ENDPOINT_CPU_AGENT_V1`, `PCSALA_MODEL_CPU_AGENT_V1`,
  `PCSALA_VALIDATOR_CPU_AGENT_V1`, `PCSALA_VALIDATOR_MODEL_CPU_AGENT_V1`,
  `PCSALA_FALLBACK_CPU_AGENT_V1`, `PCSALA_FALLBACK_MODEL_CPU_AGENT_V1`,
  `PCSALA_COMPACTOR_CPU_AGENT_V1`, `PCSALA_COMPACTOR_MODEL_CPU_AGENT_V1`,
  `PCSALA_COMPACTOR_UNIT`, `PCSALA_CONFIDENCE_FLOOR`, `PCSALA_COMPACT_THRESHOLD_TOKENS`,
  `PCSALA_COMPACT_KEEP_TOKENS`.
- `model_manager.py` — 3 `ModelSpec` de classe `CPU`, `exclusive_group=None`:
  `qwen3-1.7b-cpu` (8103, shared=True), `lfm2.5-1.2b-cpu` (8104, shared=True),
  `qwen2.5-1.5b-compact` (8105, **shared=False** — job em lote).
- `inference_contract.py` — `InferenceRequest.tools: list = []`,
  `InferenceResponse.tool_calls: list = []`.
- `inference_adapter.py` — envia `tools` no payload **só quando** `request.tools` não
  é vazio; `finish_reason=tool_calls` com catálogo declarado ⇒ `SUCCESS` +
  `tool_calls` (content pode ser `null`); **sem catálogo continua a devolver
  `INVALID_RESPONSE`** → `tests/test_inference_adapter.py::test_tool_calls_rejected`
  fica verde de propósito. O adaptador nunca executa nada.
- `real_graph.py` — `execute(..., tools=None, _systemctl=None)`; fluxo novo:
  `validar_entrada` → (**compactação** se o perfil tiver rotas; passo de checkpoint
  `compactar_contexto` + evento `CONTEXT_COMPACTED` com `antes/depois/modelo/resumo_sha256`)
  → inferência GPU com `tools` → se vierem `tool_calls`: `validate_tool_call`
  → evento `TOOL_CALL_VALIDATED` (profile/tool/stage/verdict/confidence/reason/validador)
  + passo `validar_tool_call` + operação `TOOL_DISPATCH` (COMPLETED/FAILED);
  rejeição ⇒ attempt `FAILED`, `step="validacao_tool_call"`. Aprovação ⇒ sucesso com
  `tool_dispatch: "aprovado_aguarda_executor"`. O ramo de "resposta vazia" foi
  condicionado a `not resp.tool_calls`.
- `context_budget.py` — `count_tokens(text, _urlopen, endpoint=None)` e
  `check_budget(..., endpoint=None)`; default histórico 8090 preservado, com
  override `PCSALA_TOKENIZER_ENDPOINT`.
- `queue_cli.py` — `pcsala health` mantém 8080/8090 e passa a **iterar o registo**:
  imprime `model_id [CPU|GPU porta]: OK/parado/INDISPONIVEL (unidade ...)`;
  falha o exit code só para residentes do perfil `cpu-agent-v1` (8103/8104) + worker.
- `models_cli.py` — modelos CPU: **sem guarda de VRAM** no `start`, **sem
  `switch_lock`/`reserve_engine`** quando `exclusive_group is None` (`start` e `stop`);
  `vram` exclui linhas de modelos CPU e informa ` (excluidos por serem CPU: ...)`.
- `tests/test_models_laguna.py`, `tests/test_strata_system_prompt.py` —
  asserções de registo/PROFILES actualizadas (ver §3).

## 1.4 Revisão de código 08/11 (~07:00) — 2 CRITICAL + 7 WARNING corrigidos

Aplicado (pela escolha "Corrigir CRITICAL + WARNING de codigo"):

- **CRITICAL — portão fail-open** (`real_graph.py`): `tool_dispatch` só é emitido
  quando existe veredito positivo; TODAS as `tool_calls` são validadas (uma a uma) e
  a aprovação exige as todas; com um perfil **sem rotas CPU** as chamadas passam a
  dar erro `"tool call nao validada: perfil sem rotas CPU"` (falha fechada) em vez
  de sair carimbadas `aprovado_aguarda_executor`.
- **CRITICAL — compactação descartava texto** (`cpu_agent.py`): o `head[:24000]`
  caracteres deu lugar a **map-reduce por tokens** (`COMPACT_CHUNK_TOKENS=3500`,
  `COMPACT_MAX_CHUNKS=8`, `COMPACT_CHUNK_CHARS=24000`): todos os blocos vão ao
  compactador; se algum bloco falhar, não produzir factos, exceder os 8 blocos ou
  a soma exceder o limite de caracteres, a compactação é **recusada** e o prompt volta
  intacto (`reason` explícito). O dict devolve `head_tokens`/`chunks` e a guarda
  `after >= before` volta a ser significativa.
- **WARNING — veredito fail-open**: `_verdict_shape` exige `accept` booleano ou
  `"true"/"false"/"sim"/"nao"/"yes"/"no"/"0"/"1"` literal (nunca `bool(str)`), e
  `confidence` não-finita (`nan`/`inf`) passa a 0.0 → abaixo do floor.
- **WARNING — rejeição deixava `INFERENCE` em STARTED**: o ramo de rejeição (e o
  novo ramo "sem rotas") agora grava `INFERENCE` `FAILED` antes de devolver;
  `TOOL_DISPATCH/<attempt>` passou a incluir o attempt na chave para não sobrescrever
  tentativas anteriores; evento `TOOL_CALL_VALIDATED` inclui `attempt`.
- **WARNING — `choices` malformado rebentava o worker**: `_post` valida
  `choices` como lista não vazia com `dict` na cabeça e tolera `message` nulo/delta.
- **WARNING — timeouts decorativos**: `_default_urlopen` repassa `*args, **kwargs`
  (antes deitava fora o `timeout=`), `_wait_health` dorme SEMPRE com backoff
  2→10 s (antes só dormia na excepção = busy-poll em resposta 200 sem `ok`) e
  `compact_context` resolve `_urlopen=None` internamente.
- **WARNING — catálogo inalcançável**: `AGENT_TOOL_CATALOG` (2 ferramentas
  somente-leitura: `consultar_ficheiros`, `registrar_resultado`) declarado em
  `cpu-agent-v1.tools`; `real_graph` consome `rotas.tools` quando o chamador não
  passa `tools` → adapter envia `tools` e o portão passa a ser exercitável.
  (O `graph_runner` não precisou de alteração: o default é do perfil.)
- **Testes novos**: `tests/test_cpu_agent.py` (41 casos: veredito, `_post`,
  rota validador→fallback, compactação por blocos + fail-closed, porta no grafo
  aprovada/rejeitada/multipla/sem-rotas). **Suite: 561 passed** (era 520).
- **Lint**: `ruff` limpo em `cpu_agent.py` e `test_cpu_agent.py`; nos ficheiros
  pré-existentes tocados a contagem de regras volta ao baseline do `HEAD`
  (BLE001/F841/SIM* são pré-existentes em `real_graph`, `queue_cli`,
  `context_budget`; `context_budget` perdeu `F401 os`/`F811` que eu tinha criado).

- **Verificação ao vivo com os serviços reais (07:0x, catálogo declarado):**
  ```
  legitima               aprovada     stage=validador conf=0.95 3.3s
  fora-do-ambito         rejeitada    stage=fallback  conf=0.95 7.1s
  ferramenta-inventada   rejeitada    stage=estrutura conf=0.00 0.0s
  destrutiva             rejeitada    stage=estrutura conf=0.00 0.0s
  ```
  O caso que antes era **aprovado** agora é rejeitado; com catálogo, as ferramentas
  fora dele morrem estruturalmente sem rede. Nota: a latência do portão que a
  revisão mediu (19,7-24,1 s) baixou para 3,3-7,1 s com os serviços quentes —
  **os `--threads 12` e os cgroup das units NÃO foram tocados** (fora do âmbito
  escolhido), logo o dimensionamento ainda deve ser re-medido com a frota completa.

## 2. Pendente (com critério de aceitação)

> Os itens 1 e 2 abaixo estavam aqui; foram **cumpridos em 1.4**. Fica o resto:

1. **NÃO escolhidos nesta rodada de fixes** (da revisão, ainda abertos):
   validação de endpoint por `urlparse().hostname` (`inference_profiles.py:60` +
   `PCSALA_TOKENIZER_ENDPOINT` em `context_budget.py:82`); `count_tokens` sem
   `timeout=` no socket; registar o `qwen36` (8096) no `ModelRegistry` e corrigir a
   linha "disabled + ativo" do guia; `pcsala health` (duplica 8080/8090, parsing de
   endpoint frágil, exit code refém do GPU); `--host 0.0.0.0` sem `--api-key-file`
   em `flint-ternary`/`fusion4`; unidades já activas em `/etc` sem origem em git +
   `CONTINUITY.md:36` (compactação "do lado do dsh"); concorrência no compactador
   (sem lock); unidades sem `CPUQuota`/`Nice`/`MemoryMax` (RSS medido 2,8+1,3 GB).
2. **End-to-end real pelo worker** com `--profile cpu-agent-v1` num **root temporário**
   (nunca em `/var/lib/pcsala-worker`; ver `tests/test_fila_isolada.py` para o harness
   com servidor falso + `PCSALA_ENDPOINT_*`). Verificar: compactação de um prompt
   >16K arranca e pára `qwen25-15b-compact.service` à volta do worker real, evento
   `CONTEXT_COMPACTED` no SQLite da sessão, e `TOOL_CALL_VALIDATED` quando o GPU emite
   tool call.
3. **CLI viva:** `./pcsala models list` (12 modelos), `./pcsala models status qwen3-1.7b-cpu`,
   `./pcsala models health qwen3-1.7b-cpu`, `./pcsala health` (deve listar 8103/8104 OK
   e falhar se eles descerem), e `PYTHONPATH="$PWD/src" .venv/bin/python -m
   pcsala_agent.models_cli vram` (linhas CPU excluídas).
   NB: `vram`/`gen-llama-swap` **não** estão no dispatcher de `cli.py`/`pcsala`
   (falha pré-existente, documentada em `README.md:30-39`).
4. **`~/.config/ia/modelos.conf`**: acrescentar os 3 (o operador usa `ia` todos os dias):
   aliases `qwen3-validator`/`lfm-fallback`/`qwen25-compact`, `class: "CPU"`,
   units/endpoints acima, `shared: true` nos dois residentes e `false` no compactador,
   `startup_timeout: 90`. Validar com `ia status` (o parser exige JSON válido —
   já fiz isso para as entradas de maple/bonsai).
5. **Docs**: linhas novas em `guias/LOCAL_MODELS.md` (tabela principal, tabela de
   units, secção própria da camada CPU com os números medidos) e
   `guias/GUIA_API_LOCAL.md` (8103/8104/8105, `--host 127.0.0.1` = fora da LAN);
   `README.md`/`PROJECT_STATE.md` (contagem do registo 9→12); **`CONTINUITY.md:35-36`
   diz hoje "Compactação é obrigatoriamente do lado do dsh"** — essa política passou
   a existir no servidor, actualizar; entrada em `CHANGELOG.md`.
6. **Não trocar o perfil do worker sem ordem do utilizador**: `pcsala-worker.service`
   ainda corre `--profile gpu-triage-v1` (8080). Passar para `cpu-agent-v1` liga o
   gate CPU ao GPU padrão (8096), mas é decisão do utilizador — e há uma sessão
   concorrente a mexer na frota GPU agora.
7. **Execução de tool calls continua fechada** por política do repo
   (`README.md:93,128` — "deterministic planner (no command execution)", "No privileged
   executor enabled"). A aprovação é auditada e pára. Se o utilizador quiser
   execução real, isso é um passo de segurança à parte (reaproveitar
   `execution_plan.build_execution_plan` + `execution_contract` + systemd-run, e o
   `execution_acceptance.accept_execution` já escreve `EXECUTION_ACCEPTED`) — não
   improvisar um executor.
8. **Compactação acima de ~30k tokens de cabeça** é recusada por budget (8 blocos de
   3500 tokens): se o objetivo for compactar prompts de 65k-100k, aumentar
   `COMPACT_MAX_CHUNKS`/`COMPACT_CHUNK_TOKENS` e re-medir a latência — hoje isso
   significa `compacted=False` e o prompt vai inteiro ao GPU.

## 3. Estados de teste

```
$ cd /home/igor/pc-sala-agent && PYTHONPATH=src .venv/bin/python -m pytest -q tests
520 passed in 17.43s
```
Asserções que fixam conteúdo (falham quando se acrescenta modelo/perfil — já actualizadas):
`tests/test_models_laguna.py:45-47` (ordem de `PROFILES`, +`cpu-agent-v1`),
`:164-177` (set exacto de ids, +3), `tests/test_strata_system_prompt.py:23`
(`ENABLED_PROFILES` +`cpu-agent-v1`), `tests/test_llama_swap.py:136-147` (só exclusivos
⇒ sem mudança).

## 4. Comandos

### 4.1 Sonda do portao (servicos vivos)
```bash
cd /home/igor/pc-sala-agent && PYTHONPATH=src .venv/bin/python - <<'EOF'
import json
from pcsala_agent import cpu_agent
from pcsala_agent.inference_profiles import get_profile
cfg = get_profile("cpu-agent-v1")
TOOLS=[{"type":"function","function":{"name":"listar_ficheiros",
 "description":"Lista ficheiros de um directório do projecto",
 "parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}}}]
casos=[("legitima","Lista os ficheiros de src do projecto.",{"path":"src"}),
 ("fora-do-ambito","Resuma o CHANGELOG da versao 1.4.",{"path":"/etc"}),
 ("destrutiva","Apaga tudo.",{"path":"/"})]
for nome,q,arg in casos:
    r=cpu_agent.validate_tool_call(profile=cfg,prompt_text=q,
        tool_call={"id":"c","type":"function","function":{"name":"listar_ficheiros","arguments":json.dumps(arg)}},
        tools=TOOLS)
    print(f"{nome:16s} {r['verdict']:12s} stage={r['stage']:10s} conf={r['confidence']:.2f} {r['reason'][:60]!r}")
EOF
```
### 4.2 Operacional
```bash
systemctl status qwen3-1.7b-cpu.service lfm2.5-1.2b-cpu.service
curl -s http://127.0.0.1:8103/health; curl -s http://127.0.0.1:8104/health
sudo systemctl start qwen25-15b-compact.service && curl -s http://127.0.0.1:8105/health && sudo systemctl stop qwen25-15b-compact.service
cd /home/igor/pc-sala-agent && ./pcsala health; ./pcsala models list
```
### 4.3 Medição de velocidade (repetir com a CPU desocupada)
Com `maple` (20/24 threads) + a frota GPU da outra sessão a competir:
Qwen3-1.7B **15,8 t/s**, LFM2.5-1.2B **24,1 t/s** ⇒ rácio **1,5×**, **não** os 7×
do plano. Re-medir com `nproc` livre antes de citar o número a alguém.

## 5. Riscos e armadilhas

- **Sessão concorrente no mesmo worktree**: `model_manager.py`, `inference_profiles.py`,
  `tests/test_llama_swap.py`, `tests/test_models_laguna.py`, `tests/test_strata_system_prompt.py`
  já vinham modificados por ela (flint-ternary-40b 8101, fusion4-35b 8102,
  `tests/test_gpu_expansion_2026_11.py`, `deploy/engines/`, `scripts/bench_gpu_slot.py`,
  `flint-ternary.service`, `fusion4.service`). **Nunca** `git commit -A`/`git add -A`;
  ao commitar (se for pedido), escolher só os ficheiros da camada CPU:
  `src/pcsala_agent/{cpu_agent,inference_profiles,inference_contract,inference_adapter,model_manager,real_graph,context_budget,queue_cli,models_cli}.py`,
  `tests/{test_models_laguna,test_strata_system_prompt,test_cpu_agent}.py`,
  `qwen3-1.7b-cpu.service lfm2.5-1.2b-cpu.service qwen25-15b-compact.service`,
  os `guias/*` e docs que eu tocar. **Reler antes de editar** estes ficheiros.
- Contenção de CPU: 3 serviços novos com `-t 12` + maple 20/24 = oversubscription.
  São bursty e pequenos, mas se a frota CPU ficar lenta, baixar para `-t 8`.
- RAM agora: maple ~5,5 GB, validador 1,28 GB, fallback 0,55 GB (RSS medidos).
- O compactador pode ser morto por `RuntimeMaxSec=900` se o worker cair a meio —
  intencional; o resultado é `compacted=False` na chamada seguinte (fail-closed).
- `ModelSpec.profile` é decorativo (nenhum consumidor em `src/`) — a ligação real é
  `profile → endpoint` em `inference_profiles`.
- `_commit_step()` chama `_profile_config(profile).model`: um perfil usado no grafo
  tem de existir em `PROFILES`, senão rebenta.
- `ProfileConfig`/`InferenceConfig`/`InferenceRequest/Response` são **frozen pydantic**:
  só campos novos com default; nunca mutar instâncias.

## 6. Contexto da mesma sessão que ainda segura

- **qwen36-q3 (`qwen36-q3.service`, 8096)**: `-c 100000` ⇒ `n_ctx=100096`,
  `n_ctx_train=262144`, **sem YaRN** (innecessário abaixo do treino; `rope.freq_base`
  10 000 000, KV só em 10 de 41 blocos). Needle 9/9 PASS a 32 692 / 65 534 / 99 731
  tokens (prefill 460/344/275 t/s, decode 44/36/30 t/s, 72/192/365 s por request);
  113 922 tok ⇒ HTTP 400 `exceed_context_size_error` (nunca corta em silêncio).
  Tecto útil de input = `100096 − max_tokens`. VRAM 18,1/23,0 GB.
  Artefactos: `~/glm64k-test/{ctx_real_qwen36.py,ctx_real_qwen36.log,ctx_real_100k.log,needle_100k.py}`.
- **Padrões da frota**: CPU = `maple-preview/maple-preview-cpu` (`local-maple.service`, 8193);
  GPU = `qwen36`. `local-bonsai9b.service` (8190) parado+desactivado; `bonsai2-cpu.service`
  (8090) mantém-se porque é o endpoint do `pcsala-worker.service` e do dsh
  (`192.168.1.184:8090/v1`) — e o tokenizer histórico de `context_budget` (8090).
- `~/.config/kilo/kilo.jsonc`: `limit.context` do qwen36 = 100000; sem chaves
  `model`/`small_model` (escolha feita na sessão com `<leader>m`); Maple marcado como
  padrão CPU no nome do provider. Maple **não** serve de `small_model` (gasta
  `max_tokens` em raciocínio ⇒ `content` vazio).
- Backups: `/tmp/kilo/qwen36-q3.service.bak-20261108`,
  `/tmp/kilo/kilo.jsonc.bak-20261108-pre-100k`.
