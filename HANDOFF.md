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
| Passo | Descrição | Estado | Resultado/verificação |
|---|---|---|---|
| F0 | Inventário: gestor ia, GPUs, portas, serviços, src/pcsala_agent | PENDENTE | aguarda saída dos comandos de leitura |
| F1 | Ramo feat/roteador e pytest de base | PENDENTE | exige autorização |
| F2 | configs/pools.toml (alvo, porta, GPU, max_inflight) | PENDENTE | |
| F3 | llama-bench por GPU | PENDENTE | exige autorização (parar modelos) |
| F4 | router.py com regras simples | PENDENTE | |
| F5 | Endpoint único /v1/chat/completions em 127.0.0.1 | PENDENTE | exige autorização (nova unidade) |
| F6 | Concorrência por pool e fallback | PENDENTE | exige autorização |
| F7 | Quality gate na CPU (Bonsai 2 4B ou 2B, a decidir por teste) | PENDENTE | exige autorização (download) |
| F8 | Logs estruturados no SQLite | PENDENTE | nova migração |
| F9 | Implantação: unidade independente, sem boot automático | PENDENTE | exige autorização |
| F10 | P100: build separada com patches sm60 (condicional à presença física) | BLOQUEADO | placa ainda não instalada |

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
