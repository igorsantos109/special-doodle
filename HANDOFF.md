# Handoff — Incorporação da P100 e do roteador ao pcsala

## Objetivo
Incorporar futuramente uma Tesla P100 (16 GB) ao pcsala, ao lado da P40, com pools independentes por GPU, roteador de endpoint único, quality gate na CPU e logs estruturados.

## Critérios de conclusão
- Inventário real de GPUs confirmado (nvidia-smi) e índices anotados.
- llama-bench (pp512, tg128) registrado por GPU.
- Roteador testado com falha forçada de um pool.
- Serviço novo iniciado, saudável, parado e revertível.

## Restrições
- A P100 ainda NÃO está instalada; decisão do Igor: será incorporada no futuro.
- Não dividir um mesmo modelo entre as duas GPUs (sem layer split).
- Preservar a configuração protegida do Laguna e os binários existentes; não recompilar sem autorização.
- Divergência a esclarecer: Laguna em 8084/51.200 (configuração protegida) versus 8082/128K (PROJECT_STATE.md).
- Endpoints apenas em 127.0.0.1 até autorização expressa.
- Não registrar segredos.

## Estado resumido
Plano proposto; nada executado na máquina. Repositório lido apenas via GitHub (PROJECT_STATE.md de 2026-10-28, CONTINUITY.md, README.md, listagens).

## Plano e progresso
- F0: Inventário: gestor ia, GPUs, portas, serviços, src/pcsala_agent — PENDENTE.
- F1: Ramo feat/roteador e pytest de base — PENDENTE (exige autorização).
- F2: configs/pools.toml (alvo, porta, GPU, max_inflight) — PENDENTE.
- F3: llama-bench por GPU — PENDENTE (exige autorização para parar modelos).
- F4: router.py com regras simples — PENDENTE.
- F5: Endpoint único /v1/chat/completions em 127.0.0.1 — PENDENTE (exige autorização para nova unidade).
- F6: Concorrência por pool e fallback — PENDENTE (exige autorização).
- F7: Quality gate na CPU (Bonsai 2 4B ou 2B, a decidir por teste) — PENDENTE (exige autorização para download).
- F8: Logs estruturados no SQLite — PENDENTE (nova migração).
- F9: Implantação: unidade independente, sem boot automático — PENDENTE (exige autorização).
- F10: P100: build separada com patches sm60 (condicional à presença física) — BLOQUEADO (placa ainda não instalada).

## Ações executadas
- Nenhuma alteração no pc-sala. Apenas este registro.

## Arquivos alterados
- HANDOFF.md: criado (este ficheiro).

## Evidências
- Leitura de PROJECT_STATE.md (2026-10-28): uma P40; 7 modelos; grupo exclusivo gpu-slot-1.

## Operações em andamento
- Nenhuma.

## Decisões e justificativas
- P100 será incorporada ao pcsala no futuro (decisão do Igor, 2026-10-31).
- Pools independentes por GPU, pela disparidade de largura de banda (cerca de 732 contra 347 GB/s, valores do plano colado, não verificados aqui).
- Alegações de ganho dos patches da P100 não foram verificadas.

## Bloqueios e autorizações
- Nenhuma autorização de escrita no pc-sala concedida.
- Pendente: confirmar se o roteador entra dentro do pcsala ou como processo à parte.

## Próxima ação
F0: Igor executa os comandos de leitura em bash no pc-sala e cola a saída.

## Reversão
Apagar HANDOFF.md ou git revert deste commit. Nenhuma alteração no pc-sala.

## Última atualização
2026-10-31, agente administradora (Perplexity)

## Atualização de desenvolvimento — 2026-11-04

Execução do plano de debugger (PC-SALA Agent 1.0.1rc1):

- Instrumentacao de logging estruturado em `src/pcsala_agent/inference_adapter.py` (`InferenceAdapter.query`: inicio, erros HTTP/URL/timeout/OS, truncamento, corpo nao JSON, sucesso).
- Instrumentacao de logging estruturado em `src/pcsala_agent/models_cli.py` (`_cmd_start`, `_cmd_stop`, `_cmd_switch`: recusa de VRAM, reserva, start/stop, health, rollback, switch bloqueado).
- Novo `tests/test_debugger_falhas.py` com 22 casos de injeção de falha (backends falsos, sem hardware): inferência (timeout de leitura, URLError wrapped, truncamento, finish_reason=length, choices vazio/nulo/nulo, corpo não-JSON, corpo vazio), modelo (start falha código != 0, systemctl timeout 124, health timeout, switch rollback ao anterior, VRAM insuficiente, nvidia-smi indisponível -> falha fechada, stop com unidade ainda ativa), fila (concorrência um vencedor, update não sobrescreve estado terminal, tarefa reservada não completada, idempotency key reusada com prompt diferente), grafo (sessão não RUNNING, INDETERMINATE -> RuntimeError), checkpoints (commit sem artefato -> RecoveryRequired, artefato alterado -> RecoveryRequired).
- Suíte completa: `pytest -q -m 'not gpu' tests` → 562 passou (540 da candidata + 22 novos).
- `ruff check` limpo nos arquivos alterados; `compileall src` OK.

### 1. Resultados da suíte (2026-11-04)

| Item | Resultado |
|---|---|
| pytest -q -m 'not gpu' tests | 562 passou, 0 falhou (câpia de entrega); 565 passou no repositório Git pai após `pip install -e '.[dev]'` no .venv local |
| ruff check (inference_adapter.py, models_cli.py, test_debugger_falhas.py) | limpo |
| compileall src | OK |

### 2. Envio ao GitHub (2026-11-05, autorização explícita do Igor)

- Repositório: `igorsantos109/ialocalagent` (remote origin), branch nova `fix/rc1-correcoes`.
- Commit `64a1736` — correções R01–R09 e extras na candidata 1.0.1rc1 (12 arquivos, staging preexistente).
- Commit `b8807bf` — instrumentação de logging + 22 testes de injeção de falha + este HANDOFF (4 arquivos).
- Push concluído: `origin/fix/rc1-correcoes` criada. PR sugerido: https://github.com/igorsantos109/ialocalagent/pull/new/fix/rc1-correcoes
- Verificação antes do push: 565 testes passaram, ruff limpo, compileall OK no repo pai.
- Não enviados (intencional): `Versão nova/` (cópia de entrega com .venv/dist/evidence) e `src/pc_sala_agent.egg-info/` (artefato do pip install -e).
- Correção de ambiente no repo pai: `.venv` sem o pacote instalado fazia 10 testes de subprocess falharem com ModuleNotFoundError; resolvido com `pip install -e '.[dev]'` (não é mudança de código).

Escopo: cópia na nuvem; envio ao GitHub autorizado pelo Igor (branch fix/rc1-correcoes); sem alteração no pc-sala, sem instalação de serviços ou modelos.
Alterações previstas: adaptador HTTP, coordenação/reservas, guarda CPU/GPU, fila e testes.
Sem interrupção de geração. Reversão: patch/commits locais reversíveis; código original preservado em Git.
Não modificar CLI pública, estados persistidos, schema de banco, unidades, portas ou binários.

| Fase | Entrega | Estado |
|---|---|---|
| FIX-F1 | Leitura e baseline | EM ANDAMENTO |
| HTTP-F1/F2/F3 | Teste vermelho, correção, verificação | PENDENTE |
| MODELS-F1/F2/F3 | Teste vermelho, correção, verificação | PENDENTE |
| QUEUE-F1/F2/F3 | Teste vermelho, correção, verificação | PENDENTE |
| RELEASE-F1 | Suíte, relatório e arquivo de código | PENDENTE |
| LOCAL | GPU real, instalação e operação | PENDENTE-LOCAL |
| REVIEW | Revisão independente por outra família | PENDENTE |

A API/gateway, pools P100 e unificação completa são trabalho futuro, não implicados na correção.

HTTP-F1 — CONCLUÍDO: regressões vermelhas reproduzidas com transportes falsos.
HTTP-F2/F3 — Implementação aplicada; verificação em evidence/http-green.log.
Timeout da configuração do perfil é a autoridade; não foi alterado contrato para criar novo status.
`length` e chamadas de ferramenta não suportadas retornam INVALID_RESPONSE.

## Encerramento da implementação — 2026-11-04

Estado: PARCIAL NO PROJETO GLOBAL; correções R01–R09 implementadas e verificadas em sandbox.
As fases abaixo referem-se à entrega de código, não à implantação F0–F10 anterior.

| Fase | Estado | Evidência |
|---|---|---|
| FIX-F1 | CONCLUÍDO | snapshot b1767c9; baseline 498 passou após configurar .venv temporária |
| HTTP-F1/F2/F3 | CONCLUÍDO | timeouts, leitura limitada, fechamento e payloads; 26 testes focais passaram |
| MODELS-F1/F2/F3 | CONCLUÍDO | exclusividade transacional, idempotência, reversão no schema atual, stop confirmado |
| QUEUE-F1/F2/F3 | CONCLUÍDO | UPDATE apenas RESERVED; estados terminais não sobrescritos; migração sob trava |
| PACKAGE | CONCLUÍDO | SQL distribuído no wheel; smoke de migração/enqueue/list fora da árvore |
| RELEASE | CONCLUÍDO | 540 testes passaram; wheel instalado; entrega de código candidata |
| REVIEW | PENDENTE | requer revisão de família diferente, não disponível nesta sessão |
| LOCAL | PENDENTE | identidade, geração real, memória, desempenho e recuperação na P40 |
| P100/API/STRATA | PENDENTE | não implementados como parte desta correção |

42 casos parametrizados de regressão incluídos; a contagem final está no relatório de entrega.
Não alterados: schema SQL, interfaces CLI, configurações do Laguna, serviços, portas, modelos ou builds.
Reversão: não instalar a candidata; em desenvolvimento, aplicar patch reverso em árvore limpa no SHA base.
A cópia é versionada como 1.0.1rc1 para não confundir o wheel corrigido com a versão 1.0.0.
Limite conhecido: ruff global tem avisos antigos; nenhuma nova ocorrência é aceita; comparação em evidence/.
Próximo: revisão independente, validação no Python 3.11 da CI e inspeção local autorizada; não promover automaticamente.


---

## Atualização T01-F1 — PR corrigido para fase-0 (2026-11-08)

### T01-F1: Corrigir o PR — **EXECUTADO**
Branch `fase-0` criada a partir de `origin/main` com **apenas as correções** (5 commits cherry-picked):
- `64a1736` fix(rc1): correções R01–R09 e extras
- `935b8de` D01-F1: testes falhas InferenceAdapter
- `b8807bf` test(debug): 22 testes injeção falha
- `e127c39` fix(debugger, REV-F1): corrige testes/ruído
- `640a099` E01: não deixa tarefa em RESERVED

### Estado actual
| Branch | Conteúdo |
|--------|----------|
| `origin/main` | 1 commit (38d4644) — sem `src/pcsala_agent` |
| `origin/fase-0` | 18 commits — histórico fase-0 original (PASSOS 1-5, D01-F1) |
| `fase-0` (local + push) | 23 commits — fase-0 + 5 correções R01–R09 + debugger + E01 |
| `fix/rc1-correcoes` | 38 commits — fase-0 + correções + espelho 28/10 + T01-F2/F3 docs |

### Próximo passo (requer acção do Igor no GitHub)
1. **Fechar PR #2** (`fix/rc1-correcoes` → `main`)
2. **Abrir novo PR**: `fix/rc1-correcoes` → `fase-0` (ou `fase-0` → `main` se preferir merge directo)

O diff do novo PR conterá **apenas as 4 alterações funcionais** (inference_adapter, models_cli, task_queue, graph_runner) + testes + docs de entrega — sem os 56 erros ruff legados do espelho 28/10.

### CI esperada
- Python 3.13 ✅ (já alinhado)
- `requirements.lock` regenerado ✅
- Ruff: **deve passar** — apenas ficheiros corrigidos no diff
- Testes: **569 passed** ✅

---

## Última atualização
2026-11-08, agente DSH (sessão pc-sala-agent).
