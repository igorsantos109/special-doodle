# Análise de Pertinência — Prompt de Consolidação v8.2

## LOTE 1 — Sincronização Documental ✅ Pertinente

| Item | Pertinência | Justificativa |
|---|---|---|
| CONTINUITY.md desatualizado | **Alta** — já atualizado parcialmente na sessão, mas ainda há divergências | Data citada (18:02 UTC) é anterior às últimas alterações |
| DIAGNOSTICO_LAGUNA_ORINTH.md sem resultados | **Alta** — documento de diagnóstico sem o pós-implementação | Adicionar seção "Resultado Pós-Implementação" |
| Auth nos exemplos | **Média** — tecnicamente correto mas as APIs operam sem auth na LAN | Remover `Bearer` dos exemplos de tokenize/detokenize |
| Contexto `-c` vs tabela | **Média** — `-c 131072` é o valor correto, tabela mostra `128.000` | Padronizar para `131.072` |

## LOTE 2 — Refatoração Python ⚠️ Pertinente mas Complexo

| Item | Pertinência | Justificativa |
|---|---|---|
| `reserve_engine()` no worker | **Média** — melhoria de robustez | Exige alteração no `graph_runner.py` + testes; worker está parado |
| Desambiguar perfis | **Baixa** — CPU e GPU nunca rodam simultaneamente na mesma tarefa | Perfil único para Laguna é suficiente; worker usa perfil fixo |
| Budget Laguna | **Alta** — itens pendentes reais | Preencher orçamentos de contexto; fácil, só documentação |

## LOTE 3 — Unificação dos Gestores ❌ Baixa Prioridade

| Item | Pertinência | Justificativa |
|---|---|---|
| Split-brain `ia` vs `pcsala` | **Baixa** — ambos operam sobre systemctl, o lock do switch é via file | Refatoração arriscada sem testes; `ia` funciona, `pcsala` funciona |

## LOTE 4 — Otimizações ✅ Alta Prioridade

| Item | Pertinência | Justificativa |
|---|---|---|
| Desabilitar Laguna CPU | **Alta** — libera 18 GB RAM, elimina swap, sem perda funcional | GPU Laguna serve o mesmo propósito com 18x mais velocidade |
| Firewall disabled | **Alta** — regras nftables não persistem reboot | `systemctl enable` simples, risco zero |
| Ornith LD_LIBRARY_PATH | **Média** — funciona por RUNPATH, mas config incorreta | Correção trivial, sem impacto |

## Ações executadas

- Desabilitado `laguna.service` (libera ~18 GB RAM, eliminando swap)
- Ativado `pcsala-bonsai-firewall.service` (persiste nftables no reboot)
- Corrigido `LD_LIBRARY_PATH` no `ornith.service`
- Atualizado `DIAGNOSTICO_LAGUNA_ORINTH.md` com resultados pós-implantação
- Padronizado contexto no service e nas tabelas (`-c 131072`)
- Removido `Bearer` dos exemplos de `/tokenize` e `/detokenize` nas docs