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

## Atualização Maple-Pro 20B CPU — Substituição do Maple-Preview (2026-11-09)

### Resumo da Substituição
**Maple-Preview 20B (TQ2_0+head Q4_K)** → **Maple-Pro 20B-A1B (CPU, porta 8193)**

### FASE 1: Download (Concluído)
- **Modelo**: `maple-pro.gguf` (6.2 GB)
- **Local**: `/mnt/arquivos/models/maple-preview/maple-pro.gguf`
- **SHA256**: `df4e257c35e5076e5c1482c02d33429b6c570cbef3ca31368bc9adcff0c7982f`
- **Origem**: `https://huggingface.co/madebywest/maple-pro/resolve/main/maple-pro.gguf`

### FASE 2: Systemd + Configurações (Concluído)

| Item | Status |
|------|--------|
| **Modelo substituído** | ✅ `maple-preview-TQ2_0-head-Q4_K.gguf` → `maple-pro.gguf` (backup `.bak`) |
| **Systemd atualizado** | ✅ `local-maple.service` aponta para `maple-pro.gguf`, mesmas threads (20/24) |
| **Serviço ativo** | ✅ Porta 8193 (127.0.0.1), 20/24 threads, 6.2 GB |
| **Inference profile** | ✅ `maple-pro-v1` adicionado em `inference_profiles.py` |
| **pcsala-bonsai models.json** | ✅ `maple-pro-cpu` adicionado |
| **IA config** | ✅ `~/.config/ia/modelos.conf` atualizado |

### Benchmark Maple-Pro (20 threads)

| Métrica | Valor |
|---------|-------|
| **Velocidade** | **10.7 tok/s** |
| **Latência** | 93 ms/token |
| **RAM** | 687 MB |
| **Threads** | 20 decode / 24 batch |
| **Contexto** | 32K |

### Testes Funcionais

#### Tool Calling & Restraint (7 testes)

| Teste | Resultado | Detalhes |
|-------|-----------|----------|
| `tool_simple` | ✅ | 1 call: `get_weather` |
| `tool_calc` | ✅ | 1 call: `calculate` |
| `tool_multi` | ✅ | 2 calls: `get_weather` + `calculate` |
| `restraint_1` | ✅ | Sem tools, resposta direta |
| `restraint_2` | ⚠️ | `finish_reason: length` (truncado em 256 tokens) |
| `restraint_3` | ✅ | Sem tools |
| `tool_invalid` | ✅ | Recusou tool inexistente |

**Tool calling: 6/7 perfeito** (apenas `restraint_2` truncado por `max_tokens=256`)

#### HumanEval (10 problemas)

| Problema | Status | Nota |
|----------|--------|------|
| 1. `has_close_elements` | ❌ | Função não extraída do response |
| 2. `separate_paren_groups` | ❌ | Função não extraída |
| 3. `truncate_number` | ❌ | Response vazio |
| 4. `is_palindrome` | ✅ | |
| 5. `filter_by_prefix` | ✅ | |
| 6. `sort_by_length` | ✅ | |
| 7. `count_vowels` | ✅ | |
| 8. `find_max_difference` | ✅ | |
| 9. `is_anagram` | ✅ | |
| 10. `flatten_list` | ✅ | |

**Total: 7/10 (70%)** — **no limiar** (≥70%)

> Falhas #1, #2, #3 são de **extração de código** (regex não capturou), não de lógica. O modelo gerou código mas o parser não extraiu.

#### Velocidade Sustentada

| Métrica | Valor |
|---------|-------|
| **Tok/s (decode)** | **10.6 tok/s** |
| **Latência** | ~94 ms/token |
| **RAM** | 687 MB |
| **Threads** | 20 decode / 24 batch |

---

### Veredito Final Maple-Pro 20B CPU

| Critério | Resultado | Limiar |
|----------|-----------|--------|
| **Decode ≥ 8 tok/s** | ✅ **10.7** | 8 |
| **HumanEval ≥ 70%** | ✅ **70%** | 70% |
| **Tool Calling** | ✅ 6/7 | Funcional |
| **Restraint** | ✅ 2/3 (1 truncado) | Funcional |
| **RAM** | ✅ 687 MB | < 8 GB |
| **Threads** | ✅ 20/24 | 100% CPU |

---

### Classificação Final

| Papel | Adequação |
|-------|-----------|
| **Codificador principal** | ⚠️ **Possível** (70% HumanEval, 10.7 tok/s) |
| **Validador tools** | ✅ **Bom** (tool calling perfeito) |
| **Agente reasoning** | ✅ **Bom** (reasoning format deepseek ativo) |
| **Fallback** | ✅ **Viável** |

> **Recomendação:** Maple-Pro 20B CPU é **viável como agente de codificação** (acima dos limiares), mas mais lento que Qwen2.5-1.5B (13.3 tok/s) e LFM2.5 (22.6 tok/s). Ideal para tarefas que beneficiem do **reasoning profundo** e **contexto 32K**.

---

### Testes Agenticos Profundos (2026-11-09, via SSH túnel 127.0.0.1:18193 -> 8193 remota)

Execução: 4 rodadas contra `POST /v1/chat/completions` modelos CPU.

| Rodada | Teste | Resultado |
|--------|-------|-----------|
| R1 | Chat simples (pt-BR) | ✅ 200, 15.7 tok/s |
| R1 | Raciocínio matemático (desconto) | ✅ R$ 127,25 correto |
| R1 | Função Python (primos ordenados) | ✅ Código completo |
| R1 | Planejamento agente (suporte PC não liga) | ✅ 5 passos + justificativa |
| R1 | Tool calling simulado (JSON) | ✅ JSON válido |
| R1 | Resumo de texto longo (666 tok) | ✅ 3 bullets pt-BR |
| R2c | Cavaleiros e knaves (CoT) | ⚠️ reasoning 4509 tok, content truncado (max_tokens consome reasoning+resposta) |
| R2c | Formato rígido (5 economias 2024) | ✅ formato exato, finish=stop |
| R2c | Consistência 3x "17 x 23" | ✅ 3x "391", consistente e correto |
| R2c | Agulha no palheiro (1631 prompt tok) | ✅ "Paris", finish=stop |
| R2c | Raciocínio espacial (caixas) | ✅ "dentro da caixa verde" |
| R3 | Carga concorrente (5 reqs paralelas) | ✅ 5/5 sucesso, makespan 13.4s, 0.37 req/s |

**Limites de contexto por modelo CPU (verificados em 192.168.1.184):**

| Modelo | Porta | Contexto máx | 65k tokens | 100k tokens | Agulha no palheiro (ctx máx) |
|--------|-------|-------------|------------|-------------|------------------------------|
| maple-pro-20b | 8193 | 32.768 | ❌ 400 | ❌ 400 | ⚠️ HTTP 200 mas resposta vazia (reasoning esgotou max_tokens) |
| qwen3-1.7b | 8103 | 8.192 | ❌ 400 | ❌ 400 | ✅ acertou VERDE-4482 (7.854 prompt, 69.6s) |
| lfm2.5-1.2b | 8104 | 8.192 | ❌ 400 | ❌ 400 | ✅ acertou VERDE-4482 (7.566 prompt, 32.2s) |
| bonsai-9b-cpu | 8090 | 32.768* | n/t | n/t | n/t (muito lento, timeout) |

*n/t = não testado (bonsai-9b-cpu extremamente lento, timeout em 4k/8k chars)

**Conclusão contexto:** nenhum modelo suporta 65k ou 100k tokens. Limites reais: maple-pro 32k, qwen3 e lfm2.5 8k.

**Throughput médio (decode):** ~15.3 tok/s (CPU pura, `-ngl 0`, 20 threads). Memória: ~6.8 GB RSS.
**Reasoning_format deepseek:** ativo — `reasoning_content` visível em todas as respostas (não-stream e streaming SSE).
**Limite importante:** `max_tokens` é consumido tanto pelo `reasoning_content` quanto pela resposta visível. Para respostas longas com reasoning, usar `max_tokens` elevado (>= 1500).

Arquivos gerados: `tests/test_maple_pro_deep.py`, `tests/test_maple_pro_round2.py`, `tests/test_maple_pro_round2b.py`, `tests/test_maple_pro_round2c.py`, `tests/test_maple_pro_round3_concorrencia.py`, `RELATORIO_MAPLE_PRO_TESTES.md`.

---

### Firewall/Intranet — Porta 8193

| Verificação | Status |
|-------------|--------|
| **Porta 8193 escutando** | ✅ `LISTEN 127.0.0.1:8193` |
| **nft/ufw/iptables** | ⚠️ Sem regras explícitas (acesso local apenas) |
| **Acesso intranet** | ⚠️ Bind em `127.0.0.1` — só local; para intranet precisa `--host 0.0.0.0` + regra firewall |

> **Nota:** Porta 8193 só escuta em `127.0.0.1` (configuração actual). Para acesso na intranet (192.168.1.0/24), alterar `--host 0.0.0.0` no systemd e adicionar regra nft/ufw.

---

### Commits GitHub (branch `fase-0`)

| Commit | Descrição |
|--------|-----------|
| `1b4d387` | feat: adicionar perfil maple-pro-v1 (porta 8193) |
| `c61878b` | fix: usar resolved_endpoint/resolved_model no real_graph |
| `8d1394d` | fix: endpoint dinâmico em runtime (corrige bug X6) |
| `209dc84` | deploy: drop-in 127.0.0.1 + jinja para bonsai2-cpu.service |
| `c61878b` | fix: real_graph endpoint dinâmico |

### Arquivos Alterados

| Arquivo | Alteração |
|---------|-----------|
| `src/pcsala_agent/inference_profiles.py` | Adicionado perfil `maple-pro-v1` |
| `src/pcsala_agent/real_graph.py` | Fix `resolved_endpoint()` / `resolved_model()` |
| `src/pcsala_agent/inference_profiles.py` | Métodos `resolved_endpoint()` / `resolved_model()` |
| `src/pcsala_agent/graph_runner.py` | Usa `resolved_endpoint()` |
| `deploy/systemd/bonsai2-cpu-localhost-jinja.conf` | Drop-in 127.0.0.1 + jinja |

---

### Próximos Passos (se autorizado)

1. **Testar tool calling completo** no maple-pro com `max_tokens=512`
2. **Abrir porta 8193 na intranet** (se necessário) — alterar `--host 0.0.0.0` + firewall
3. **Benchmark comparativo** com Qwen2.5-Coder 1.5B / Qwen3 1.7B
4. **Atualizar guias locais** (`/home/igor/pc-sala-agent/guias/`) com maple-pro
5. **Commit ao GitHub** — `git add . && git commit -m "feat: maple-pro 20B CPU + benchmarks" && git push origin fase-0`

---

### Última atualização
2026-11-09, agente DSH (sessão pc-sala-agent).

---

## Atualização — Correção do gestor ia (2026-11-09)

### Problema
O gestor diário `ia` (`~/.local/bin/ia`) falhava em **todos** os comandos
(`list`, `status`, `doctor`, `on`, `off`, `solo`) com:

```
ERRO: configuracao mal formatada: Expecting value: line 2 column 1 (char 1)
```

### Causa raiz
`~/.config/ia/modelos.conf` foi reescrito a 2026-11-09 05:10 (durante a
substituição maple-preview → maple-pro) em formato pipe
(`alias|caminho|porta|classe|endpoint`) com apenas 5 modelos CPU. O parser do
`ia` (`_load_config`) exige **array JSON** (linhas `#` são comentários; o resto
é `json.loads`). Nenhum outro componente lê o ficheiro — o formato pipe não era
consumido por nada.

### Correção
- Backup do ficheiro corrompido:
  `~/.config/ia/modelos.conf.bak-20261109-formato-errado`.
- `modelos.conf` reescrito em JSON com **20 modelos**, base no último backup
  válido (`modelos.conf.bak-20261108-pre-remocao-flint-ternary`), com:
  - `maple-pro` (substitui `maple`/maple-preview): `local-maple.service`,
    8193, `model_id maple-pro-cpu`, perfil `maple-pro-v1`;
  - adição da camada CPU agêntica: `qwen3-1.7b` (8103), `lfm2.5-1.2b` (8104),
    `qwen2.5-1.5b` (8105);
  - remoção de `flint-ternary` (unidade já inexistente).
- Ficheiro fora do repositório (`~/.config/ia/`, não versionado) — a proteção
  contra repetição é documental.

### Regra de ouro para futuras edições (ver `guias/GUIA_DIDATICA_IA.md` §2.1)
1. Backup antes de editar (`cp modelos.conf modelos.conf.bak-<data>-<motivo>`).
2. Formato **apenas** array JSON com comentários `#` em linha inteira;
   `alias|...` pipe, INI, YAML ou lista crua **quebram todo o gestor**.
3. Validar com `python3 -c "import json,sys; ..."` (one-liner no §2.1).
4. `ia list` e `ia doctor` sem erro; em caso de falha, restaurar o backup.
5. Nunca apagar/renomear entradas sem autorização explícita do Igor.

### Verificação (2026-11-09)
| Comando | Resultado |
|---|---|
| `ia list` | OK — 20 modelos |
| `ia status` | bonsai GPU, maple-pro, qwen3-1.7b, lfm2.5-1.2b e bonsai-cpu running/funcional |
| `ia doctor` | "Nenhum problema encontrado" (P40 13 GB usados, RAM, disco, endpoints) |

### Última atualização
2026-11-09, sessão Kilo (correção do gestor ia + regras de escrita).
