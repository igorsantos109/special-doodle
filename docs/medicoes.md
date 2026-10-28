# Medições de desempenho — Tesla P40 (23 GB VRAM)

**Nota:** Estas medições devem ser executadas no hardware real (pc-sala, Tesla P40).
Este documento registra o modelo para preenchimento após os testes.

## Bonsai 2 27B — -c 64000 + flash-attn

| Configuração | VRAM usada | Prompt eval (tok/s) | Gen tok/s | MTP aceitação | Cabe em 1,5 GB folga? |
|---|---|---|---|---|---|
| Sem MTP, sem --no-kv-offload | — | — | — | n/a | — |
| Com MTP (draft-mtp, n-max 2, p-min 0.4) | — | — | — | — | — |

### Decisão: retirada de --no-kv-offload

A unit original incluía `--no-kv-offload`, que impede o offload do cache KV para a RAM. Removido para permitir que o cache KV flua para a memória do sistema quando a VRAM estiver cheia, desde que haja folga de pelo menos 1,5 GB para o slot ativo.

## Bonsai 4B — piloto llama-swap (PR B)

| Via | Tempo de carga a frio | Tempo até primeiro token | tok/s | VRAM/RAM |
|---|---|---|---|---|
| Unit systemd atual | — | — | — | — |
| llama-swap (config.yaml) | — | — | — | — |

**Regra de parada:** se o llama-swap piorar qualquer número em mais de 10% vs a unit atual, não prosseguir com a migração.

## Critério de aceitação

- VRAM livre >= 1,5 GB após carregar o modelo ativo.
- start/switch recusados quando folga < 1,5 GB (guarda fechada).
- Slot save/restore de KV desativado por padrão (MROPE não validado).
