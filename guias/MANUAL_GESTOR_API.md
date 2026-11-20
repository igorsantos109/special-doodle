# Manual do Gestor de Modelos e APIs (pcsala models)

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
./pcsala models vram                          # VRAM por modelo e folga
```

## Modelos registrados (2026-11-20)

| model_id | classe | perfil | unidade | endpoint |
|---|---|---|---|---|
| qwen36-q4 | GPU | gpu-triage-v1 | qwen36-q4.service | 192.168.1.184:8098 |
| qwen36-q3 | GPU | gpu-triage-v1 | qwen36-q3.service | 192.168.1.184:8096 |
| qwen38-gyro-s | GPU | gpu-triage-v1 | qwen38-gyro-s.service | 127.0.0.1:8081 |
| ttf-qwen38 | GPU | gpu-triage-v1 | ttf-qwen38-27b.service | 127.0.0.1:8108 |
| bonsai-27b-gpu | GPU | gpu-triage-v1 | bonsai2-27b.service | 127.0.0.1:8080 |
| qwen3-30b-a3b-cpu | CPU | cpu-triage-v1 | qwen3-30b-a3b-cpu.service | 127.0.0.1:8109 |
| local-maple | CPU | cpu-triage-v1 | local-maple.service | 127.0.0.1:8193 |
| qwen3-1.7b-cpu | CPU | cpu-triage-v1 | qwen3-1.7b-cpu.service | 127.0.0.1:8103 |
| qwen2.5-1.5b-cpu | CPU | cpu-triage-v1 | qwen25-15b-compact.service | 127.0.0.1:8105 |
| lfm2.5-1.2b-cpu | CPU | cpu-triage-v1 | lfm2.5-1.2b-cpu.service | 127.0.0.1:8104 |
| phi35-mini-cpu | CPU | cpu-triage-v1 | phi35-mini-cpu.service | 127.0.0.1:8106 |
| bonsai2-cpu | CPU | cpu-triage-v1 | bonsai2-cpu.service | 127.0.0.1:8090 |

Os modelos GPU grandes (`qwen36-q4`, `qwen36-q3`, `qwen38-gyro-s`, `ttf-qwen38`, `bonsai-27b-gpu`) partilham
`exclusive_group="gpu-slot-1"`: apenas um fica carregado de cada vez.

## Troca de GPU

A GPU é exclusiva (`shared: false` para modelos GPU). `switch` para o modelo desejado (~1-2 minutos) e para o anterior.

```bash
./pcsala models switch qwen36-q4     # GPU + CPU MoE offload (secundário, testado)
./pcsala models switch qwen36-q3     # GPU primário
./pcsala models switch qwen38-gyro-s # Strata
./pcsala models switch ttf-qwen38    # ttf-home llama.cpp
./pcsala models switch bonsai-27b-gpu # PrismML
```

O `switch` para o modelo desejado, para o anterior e espera o novo
responder `/health` (com guarda de VRAM: recusa abaixo de 1,5 GB). O
equivalente diário, sem guarda e com confirmação, é o `ia solo <alias>`
(ver `guias/GUIA_DIDATICA_IA.md`).

## Configurações Especiais (2026-11-20)

### qwen36-q4 — CPU MoE Offload
```bash
--cpu-moe              # Offload experts MoE para CPU/RAM
-c 55000               # Contexto 55K
--spec-type draft-mtp  # MTP ativo
```

### qwen3-30b-a3b-cpu — YARN 65K
```bash
-c 65536
--rope-scaling yarn
--yarn-ext-factor 2.0
--yarn-orig-ctx 32768
```

### local-maple — YARN 65K
```bash
-c 65536
--rope-scaling yarn
--yarn-ext-factor 2.0
```

## API HTTP

- `GET /health` → saúde do servidor
- `POST /v1/chat/completions` → inferência (OpenAI compatible)
- `POST /v1/completions` → inferência (legacy)
- `POST /tokenize`, `POST /detokenize` → utilitários

Exemplo:
```bash
curl -s http://192.168.1.184:8098/health
curl -s http://127.0.0.1:8098/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3.6-35b-a3b-q4-xl","messages":[{"role":"user","content":"Olá"}]}'
```

## Persistência

Operações do gestor são registradas em SQLite (tabela `model_operations`), migração `005_model_operations.sql`.