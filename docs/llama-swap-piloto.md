# Piloto llama-swap — apenas Bonsai 4B (PR B)

**Contexto:** o gestor atual (pcsala_agent) fica como camada de política:
registro de modelos, guarda de VRAM (folga mínima 1,5 GB), lock de troca,
reservas de motor e auditoria em `model_operations`. A EXECUÇÃO (carregar,
descarregar, esperar o modelo ficar pronto) passa a ser feita pelo
llama-swap (https://github.com/mostlygeek/llama-swap), proxy compatível com
OpenAI que troca o servidor llama.cpp conforme o campo "model".

**Adoção GRADUAL:** primeiro só o Bonsai 4B (piloto). Os demais modelos
continuam nas units atuais até aprovação explícita.

## B1 — Levantamento da unit Bonsai 4B (sem alterar código)

| Item | Valor |
|---|---|
| Unidade | `bonsai-4b-gpu.service` |
| Porta | 8093 |
| Binário llama-server | `/home/igor/opt/prism-pascal-build/install/bin/llama-server` |
| LD_LIBRARY_PATH | `/home/igor/opt/prism-pascal-build/install/lib` |
| Modelo | `/home/igor/models/bonsai-4b/Ternary-Bonsai-2-4B-Q4_K_M.gguf` |
| Flags da unit | `-c 64000 -t 8 -ngl 99 --flash-attn on -n 2048 --parallel 1 --no-jinja --threads-http 4 --slot-save-path /var/lib/pcsala-worker/slots` |
| Backend no registro | `llama-swap` |
| Habilitado no boot | NÃO (iniciar manualmente) |

O script `pcsala models gen-llama-swap` gera `deploy/llama-swap/config.yaml`
a partir do registro, usando `${PORT}` no lugar da porta fixa e copiando os
argumentos EXATOS da unit. Nunca editar à mão.

O serviço `deploy/systemd/llama-swap.service` roda como `igor`, escuta em
`127.0.0.1`, com `Restart=on-failure`, `NoNewPrivileges=yes`, `PrivateTmp=yes`,
`ProtectSystem=full`, `ProtectHome=read-only`. Não é habilitado no boot por
padrão.

## Fluxo híbrido (PR B3)

- `start`/`switch` para modelo com `backend="llama-swap"`: a CLI continua
  tomando o lock, conferindo a VRAM, gravando `model_operations` e a reserva;
  a execução é um pedido mínimo (`max_tokens=1`) ao llama-swap; a espera de
  saída é a própria resposta da API (timeout configurável); `stop` = endpoint
  de descarga do llama-swap.
- O resultado é registrado em `model_operations` (`COMPLETED`/`FAILED`,
  campo `error`).
- Modelos com `backend="systemd"` seguem exatamente como hoje.

## Critério de parada (B6)

Se o llama-swap piorar qualquer número (carga a frio, tempo até primeiro
token, tok/s, VRAM/RAM) em mais de 10% vs a unit atual do Bonsai 4B, PARE e
reporte. Não inicie a migração dos demais modelos (PR C) sem aprovação.

## Comandos de exemplo (bash e fish)

```bash
# Gerar config do llama-swap a partir do registro
./pcsala models gen-llama-swap --output deploy/llama-swap/config.yaml

# Iniciar o proxy llama-swap
sudo systemctl start llama-swap.service

# Iniciar o Bonsai 4B via llama-swap
./pcsala models start bonsai-4b-gpu
```

```fish
# Gerar config do llama-swap a partir do registro
./pcsala models gen-llama-swap --output deploy/llama-swap/config.yaml

# Iniciar o proxy llama-swap
sudo systemctl start llama-swap.service

# Iniciar o Bonsai 4B via llama-swap
./pcsala models start bonsai-4b-gpu
```
