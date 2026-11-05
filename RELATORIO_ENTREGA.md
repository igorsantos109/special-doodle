# Entrega de código — PC-SALA 1.0.1rc1

Estado: **correções implementadas; candidata para revisão e validação local**.
Não confundir com unificação completa ou implantação final de produção.

## Origem e autorização

Base Git: b1767c9560b22e36d46284cef1a8814d33016580 (`igorsantos109/special-doodle`).
Igor solicitou implementar as correções e entregar o projeto. Trabalho realizado em cópia de desenvolvimento na nuvem. Sem push, sem pc-sala, sem alteração de serviços, arquivos GGUF, portas ou builds.

## Implementação

| ID | Estado | Implementação | Prova |
|---|---|---|---|
| R01 | CONCLUÍDO | Timeout de config encaminhado em ambos os transportes | test_timeout_forwarded; test_default_transport_preserves_timeout |
| R02 | CONCLUÍDO | Timeout de leitura e URLError encapsulado classificados; fechamento | test_read_timeout_is_classified_and_closed; test_wrapped_timeout |
| R03 | CONCLUÍDO | choices e message validados antes do acesso | test_malformed_payload_is_invalid, parametrizado |
| R04 | CONCLUÍDO | finish_reason=length rejeitado como INVALID_RESPONSE | test_truncation_is_not_success |
| R05 | CONCLUÍDO | BEGIN IMMEDIATE na reserva; conflito por grupo e idempotência | test_reservation_conflict; test_concurrent_reservations_have_one_winner |
| R06 | CONCLUÍDO | Estado FAILED e outcome em confirmed_status, sem migrar schema | test_rollback_outcome_uses_existing_operation_states |
| R07 | CONCLUÍDO | Reserva só liberada ao confirmar parada; reversão segura | test_failed_stop_keeps_reservation e testes switch |
| R08 | CONCLUÍDO | Guarda VRAM somente para modelos GPU | test_cpu_start_without_gpu |
| R09 | CONCLUÍDO | UPDATE condicionado a RESERVED, estados terminais preservados | test_cancelled_task_is_terminal; test_completed_task_is_terminal |
| EXTRA-01 | CONCLUÍDO | Leitura de corpo limitada a max_response_bytes + 1 | test_response_read_is_bounded_and_closed |
| EXTRA-02 | CONCLUÍDO | Migrações incluídas no wheel e fallback para pacote instalado | wheel-smoke.log, migrações 1–6 e enqueue/list |
| EXTRA-03 | CONCLUÍDO | Migração da fila dentro da mesma trava de escrita | suíte de fila/isolamento |
| EXTRA-04 | CONCLUÍDO | Teste de 1 ms deixou de depender de tempo de rede real | test_timeout_injected_clock_no_sleep |
| EXTRA-05 | CONCLUÍDO | Import Path ausente na CLI do grafo corrigido | comparação lint (F821 resolvido) |
| EXTRA-06 | CONCLUÍDO | Código 124 para timeout de systemctl; estado desconhecido não libera GPU | regressões de estado/timeout |

## Verificação real

- Base, após criar ambiente de teste esperado: **498 testes passaram**.
- Bateria inicial de regressão: **21 falharam**, comprovando os cenários antes das correções.
- Candidata: **540 testes passaram**, `pytest -q -m 'not gpu' tests`.
- Testes novos: **42 casos**, incluindo parametrização e disputa concorrente de reserva.
- Build wheel: concluído. Instalado em segundo ambiente, fora da árvore fonte.
- Smoke instalado: versão 1.0.1rc1, migrações 1–6, repetição idempotente, enqueue/list com exit 0.
- compileall: passou. git diff --check: passou.
- Lint dos arquivos novos de teste/adaptador: passou.
- Lint global: **56 diagnósticos preexistentes permanecem**, contra 57 na base. Nenhum diagnóstico novo; F821 ausente foi corrigido. Não declarar CI global verde.
- Python executado: 3.12.8. CI histórica usa 3.11, ainda não validada aqui.

Antes da passagem final houve falhas de preparação de ambiente, uma integração de resposta vazia e instabilidade de um teste legado com timeout de 1 ms. Elas foram diagnosticadas; logs de etapas vermelhas e provas finais acompanham a entrega. Somente resultados finais aprovados são usados para aceitar as correções.

## Limites e pendências

| Área | Estado |
|---|---|
| Modelo em GPU real / benchmark / geração real | NÃO TESTADO |
| P40 em produção, inventário e recuperação local | PENDENTE |
| Revisão de família diferente | PENDENTE |
| Unificação com ialocalagent | PENDENTE — origem pública inacessível na auditoria anterior |
| STRATA integrado como runner | NÃO IMPLEMENTADO |
| Gateway/API externa autenticada e streaming | NÃO IMPLEMENTADO |
| Pools P100 e roteamento multi-GPU | NÃO IMPLEMENTADO; P100 futura |
| Lease de fila/fencing/reexecução distribuída | NÃO IMPLEMENTADO; estados existentes preservados |
| Orçamento completo de VRAM/capacidades de build | PENDENTE |
| Dependências fixas/lock validado na CI | PENDENTE; versões medidas incluídas |

O código herdado de readiness usa teste TCP em alguns caminhos; HTTP 200/TCP não provam identidade ou qualidade. A candidata não transforma esses sinais em validação de produção. Não alterar builds Prism/Pascal ou Laguna para instalar esta correção.

## Arquivos alterados

- HANDOFF.md (apenas acréscimos, histórico preservado)
- pyproject.toml (versão rc1 e SQL no wheel)
- src/pcsala_agent/inference_adapter.py
- src/pcsala_agent/model_manager.py
- src/pcsala_agent/models_cli.py
- src/pcsala_agent/task_queue.py
- src/pcsala_agent/migrations.py (localização dos arquivos; schema inalterado)
- src/pcsala_agent/real_graph.py (import Path)
- tests/test_llama_swap.py (teste determinístico)
- tests/test_production_regressions.py (novo)
- tools/verify_release.sh (novo)
- docs/release/LEIA_PRIMEIRO.md e este relatório

## Reversão

Nada foi instalado no pc-sala: não há mudança local a reverter. Em desenvolvimento, retornar ao SHA base ou aplicar patch reverso após `git apply --reverse --check`, sempre em árvore limpa e preservando alterações próprias. Não executar reset destrutivo. A correção não muda o schema SQL; o banco continua na versão 6.

## Próxima ação concreta

Revisão independente da candidata entregue, suíte em Python 3.11 e resolução de lint legado antes de promover. Depois, inventário somente leitura no pc-sala e autorização separada para implantação. Não tratar o arquivo de entrega como autorização para interromper modelos.
