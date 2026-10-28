# Manual do Gestor de Modelos e APIs

## Arquitetura

```
CLI ./pcsala models ──► ModelCoordinator (model_manager.py)
                              │
                              ├─ systemctl start/stop → serviços systemd
                              ├─ HTTP health → /health do servidor
                              └─ Lock /run/pcsala/pcsala-gpu-switch.lock (troca GPU)
```

## Comandos

```bash
./pcsala models list                          # listar modelos
./pcsala models status <id>                   # estado de um modelo
./pcsala models health <id>                   # saúde HTTP
./pcsala models start <id>                    # iniciar serviço
./pcsala models stop <id>                     # parar serviço
./pcsala models switch <id>                   # trocar GPU (exclusivo)
```

## Modelos registrados

| model_id | classe | perfil | unidade | endpoint |
|---|---|---|---|---|
| bonsai-27b-gpu | GPU | gpu-triage-v1 | bonsai2-27b.service | 127.0.0.1:8080 |
| laguna-xs-2.1-gpu | GPU | laguna-programming-v1 | laguna-gpu.service | 127.0.0.1:8082 |
| ornith-35b-gpu | GPU | gpu-triage-v1 | ornith.service | 127.0.0.1:8092 |
| nemotron-3.5-30b-gpu | GPU | nemotron-ternary-v1 | nemotron.service | 127.0.0.1:8083 |
| bonsai-4b-gpu | GPU (llama-swap, residente) | gpu-triage-v1 | bonsai-4b-gpu.service | 127.0.0.1:8093 |
| bonsai-9b-cpu | CPU | cpu-triage-v1 | bonsai2-cpu.service | 127.0.0.1:8090 |
| laguna-xs-2.1-cpu | CPU | laguna-programming-v1 | laguna.service | 127.0.0.1:8091 |

Os modelos GPU grandes (`bonsai-27b-gpu`, `laguna-xs-2.1-gpu`,
`ornith-35b-gpu`, `nemotron-3.5-30b-gpu`) partilham
`exclusive_group="gpu-slot-1"`: apenas um fica carregado de cada vez.

## Troca de GPU

A GPU é exclusiva (`shared: false` para modelos GPU). `switch` para o Bonsai, inicia o modelo desejado (~1 minuto) e para o anterior.

```bash
./pcsala models switch laguna-xs-2.1-gpu
./pcsala models switch ornith-35b-gpu
./pcsala models switch nemotron-3.5-30b-gpu
./pcsala models switch bonsai-27b-gpu
```

O `switch` para o modelo desejado, para o anterior e espera o novo
responder `/health` (com guarda de VRAM: recusa abaixo de 1,5 GB). O
equivalente diário, sem guarda e com confirmação, é o `ia solo <alias>`
(ver `guias/GUIA_DIDATICA_IA.md`).

## API HTTP

- `GET /health` → saúde do servidor
- `POST /completion` → inferência
- `POST /tokenize`, `POST /detokenize` → utilitários

Exemplo:
```bash
curl -s http://127.0.0.1:8080/health
```

## Persistência

Operações do gestor são registradas em SQLite (tabela `model_operations`), migração `005_model_operations.sql`.