# Permissões do usuário igor — pc-sala-agent

## Visão geral

O usuário `igor` inicia e para as units do registro de modelos via `systemctl`
**sem senha sudo**, limitado a um conjunto restrito de unidades. Todas as
outras operações de systemd exigem autenticação administrativa.

## Unidades gerenciáveis pelo usuário igor

| Unidade | Modelo/Componente | Porta |
|---|---|---|
| `pcsala-worker.service` | Worker contínuo (LangGraph) | — |
| `bonsai2-27b.service` | Bonsai 27B GPU + MTP (exclusivo, gpu-slot-1) | 8080 |
| `bonsai-4b-gpu.service` | Bonsai 4B GPU (residente, compartilhado) | 8093 |
| `bonsai2-cpu.service` | Bonsai 9B CPU | 8090 |
| `laguna.service` | Laguna XS 2.1 CPU | 8091 |
| `laguna-gpu.service` | Laguna XS 2.1 GPU (exclusivo, gpu-slot-1) | 8082 |
| `ornith.service` | Ornith 35B GPU (exclusivo, gpu-slot-1) | 8092 |

Os modelos do grupo `gpu-slot-1` (27B, Laguna GPU, Ornith) são mutuamente
exclusivos: apenas um fica carregado na GPU por vez. O `pcsala models switch`
faz a troca entre eles. O Bonsai 4B é residente e permanece carregado.

## Regra polkit

Arquivo: `deploy/polkit/50-pcsala.rules`

Instalação (executar como root):

```bash
sudo install -o root -g root -m 0644 \
    deploy/polkit/50-pcsala.rules \
    /etc/polkit-1/rules.d/50-pcsala.rules
```

A regra concede `polkit.Result.YES` apenas para `org.freedesktop.systemd1.manage-units`
quando o usuário é `igor` e a unidade está na lista permitida.

## Testes manuais (como igor)

Deve funcionar sem senha:

```bash
systemctl start bonsai2-27b.service
systemctl status bonsai2-27b.service
systemctl stop bonsai2-27b.service
systemctl start pcsala-worker.service
systemctl stop pcsala-worker.service
```

Deve ser NEGADO (unidade não está na lista permitida):

```bash
systemctl start ssh.service      # falha com "Not authorized"
systemctl stop nginx.service     # falha com "Not authorized"
systemctl start postgresql.service  # falha com "Not authorized"
```

## Alternativa: units de usuário (systemctl --user)

Em vez da regra polkit system-wide, as units podem ser executadas no escopo do
usuário (`systemctl --user`). Nesse caso, copiar os arquivos `.service` para
`~/.config/systemd/user/`, executar `systemctl --user daemon-reload` e gerenciar
com `systemctl --user start|stop <unit>`. A regra polkit acima seria desnecessária.

## Não escalar privilégios

O agente nunca roda como root. Nenhum executor privilegiado está habilitado.
Os planos do orquestrador não devem ser executados diretamente como root.
