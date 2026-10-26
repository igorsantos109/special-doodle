# Análise de Pertinência — v8.2

## Ações executadas

- Desabilitado `laguna.service` (libera ~18 GB RAM)
- Ativado `pcsala-bonsai-firewall.service` (nftables persiste no reboot)
- Corrigido `LD_LIBRARY_PATH` no `ornith.service`
- Padronizado contexto `-c 131072` no service e nas tabelas
- Removido `Bearer` dos exemplos de `/tokenize` e `/detokenize`

## Itens pendentes

- Budget de contexto Laguna: preencher orçamentos
- Desambiguar perfis: perfil único para Laguna é suficiente

## Não priorizado

- Unificação dos gestores `ia` vs `pcsala` (arriscada, ambos funcionam)