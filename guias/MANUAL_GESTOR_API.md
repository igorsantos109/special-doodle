# Manual do Gestor de Modelos e APIs — PC-SALA-AGENT

## Visão geral

```
┌──────────────────────────────────────────────────────────┐
│                  CLI ./pcsala models                      │
│  list | status | health | start | stop | switch | op     │
└──────────────────┬───────────────────────────────────────┘
                   │ delega
                   ▼
┌──────────────────────────────────────────────────────────┐
│              ModelCoordinator (model_manager.py)          │
│  Registry → valida modelo, perfil, operações             │
│  systemctl start/stop → gerencia serviço systemd         │
│  HTTP health → endpoint /health do servidor              │
│  Lock file → /tmp/pcsala-gpu-switch.lock (troca GPU)    │
└──────────────────┬───────────────────────────────────────┘
                   │ model_operations (SQLite)
                   ▼
┌──────────────────────────────────────────────────────────┐
│                 Servidores de inferência                   │
│  GPU primário: http://127.0.0.1:8080  (Bonsai 27B + MTP) │
│  GPU altern.:  http://127.0.0.1:8082  (Laguna XS GPU)    │
│  CPU:          http://127.0.0.1:8090  (Bonsai 9B, 32 th) │
│  CPU:          http://127.0.0.1:8091  (Laguna XS CPU)    │
│  GPU altern.:  http://127.0.0.1:8092  (Ornith 35B)       │
└──────────────────────────────────────────────────────────┘
```

---

## 1. Gestor de modelos (CLI)

### 1.1. Listar modelos cadastrados

```bash
./pcsala models list
```

Saída (5 modelos):
```json
[
  {
    "model_id": "bonsai-27b-gpu",
    "class": "GPU",
    "profile": "gpu-triage-v1",
    "unit": "bonsai2-27b.service",
    "shared": false,
    "endpoint": "http://127.0.0.1:8080"
  },
  {
    "model_id": "ornith-35b-gpu",
    "class": "GPU",
    "profile": "gpu-triage-v1",
    "unit": "ornith.service",
    "shared": false,
    "endpoint": "http://127.0.0.1:8092"
  },
  {
    "model_id": "laguna-xs-2.1-gpu",
    "class": "GPU",
    "profile": "laguna-programming-v1",
    "unit": "laguna-gpu.service",
    "shared": false,
    "endpoint": "http://127.0.0.1:8082"
  },
  {
    "model_id": "bonsai-9b-cpu",
    "class": "CPU",
    "profile": "cpu-triage-v1",
    "unit": "bonsai2-cpu.service",
    "shared": true,
    "endpoint": "http://127.0.0.1:8090"
  },
  {
    "model_id": "laguna-xs-2.1-cpu",
    "class": "CPU",
    "profile": "laguna-programming-v1",
    "unit": "laguna.service",
    "shared": true,
    "endpoint": "http://127.0.0.1:8091"
  }
]
```

### 1.2. Gestão via CLI `ia`

```bash
ia list                    # Listar todos os modelos
ia status                  # Estado de todos
ia status bonsai           # Estado detalhado de um modelo
ia on laguna-gpu           # Iniciar Laguna GPU
ia off ornith              # Parar Ornith
ia solo laguna-gpu         # Trocar GPU para Laguna (para o atual, inicia alvo)
ia solo bonsai             # Voltar para Bonsai
ia solo ornith             # Trocar GPU para Ornith
ia health laguna-gpu       # Health check
ia doctor                  # Diagnóstico completo
```

### 1.3. Gestão via `./pcsala models`

```bash
./pcsala models list                               # Listar
./pcsala models switch laguna-xs-2.1-gpu            # Trocar GPU para Laguna
./pcsala models switch ornith-35b-gpu               # Trocar GPU para Ornith
./pcsala models switch bonsai-27b-gpu               # Voltar para Bonsai
./pcsala models status bonsai-27b-gpu               # Estado detalhado
./pcsala models health bonsai-27b-gpu               # Health HTTP
./pcsala models start bonsai-27b-gpu                # Iniciar (idempotente)
./pcsala models stop ornith-35b-gpu                 # Parar GPU
./pcsala models operation <uuid>                    # Consultar operação persistida
```

### 1.4. Trocar GPU — fluxo completo

```text
1. Verifica se o alvo é GPU
2. Encontra GPU atualmente ativa (entre os 3 modelos GPU)
3. Se nenhuma GPU ativa → start no alvo
4. Se a mesma → já está ativa
5. Se GPU atual com tarefa em curso → BUSY
6. Lock de arquivo (/tmp/pcsala-gpu-switch.lock)
7. systemctl stop na unidade atual
8. Aguarda parada
9. systemctl start na unidade alvo
10. Aguarda health 200
11. Libera lock
```

### 1.5. Regras

- GPU é exclusiva (só um por vez, grupo `gpu-slot-1`)
- CPU é compartilhado (vários simultâneos)
- CPU **não pode ser parado** individualmente (rejeitado)
- Nomes inválidos: erro claro, sem alterações

---

## 2. APIs de inferência

### 2.1. Endpoints

| Serviço | Endereço | Porta | Modelo | Autenticação | Threads |
|---|---|---|---|---|---|
| GPU (primário) | `http://0.0.0.0` | **8080** | Bonsai 27B + MTP | Nenhuma | 8 |
| GPU (Laguna) | `http://0.0.0.0` | **8082** | Laguna XS 2.1 GPU | Nenhuma | 8 |
| CPU (auxiliar) | `http://0.0.0.0` | **8090** | Bonsai 9B | **API Key** | **32** |
| CPU (experimental) | `http://0.0.0.0` | **8091** | Laguna XS 2.1 CPU | Nenhuma | 10 |
| GPU (Ornith) | `http://0.0.0.0` | **8092** | Ornith 35B | Nenhuma | 8 |

> Bonsai CPU (8090) é o único endpoint que exige autenticação (--api-key-file).

### 2.2. Health check

```bash
# Sem autenticação (todos os endpoints, política 2026-10-23)
curl -s http://192.168.1.150:8080/health
curl -s -o /dev/null -w "%{http_code}" http://192.168.1.150:8080/health

# Um header Authorization continua aceite mas é ignorado pelo servidor
curl -s -H "Authorization: Bearer $DSH_LOCAL_API_KEY" \
  http://192.168.1.150:8090/v1/models
```

### 2.3. Geração de texto (completion)

```bash
# Bonsai GPU (sem auth)
curl -s -X POST http://192.168.1.150:8080/completion \
  -H "Content-Type: application/json" \
  -d '{"prompt":"<|im_start|>user\nOla<|im_end|>\n<|im_start|>assistant\n","n_predict":50}'

# Laguna GPU (sem auth, se ativo na porta 8082)
curl -s -X POST http://192.168.1.150:8082/completion \
  -H "Content-Type: application/json" \
  -d '{"prompt":"def fibonacci(n):\n    ","n_predict":50,"temperature":0.1}'

# Ornith GPU (sem auth, se ativo na porta 8092)
curl -s -X POST http://192.168.1.150:8092/completion \
  -H "Content-Type: application/json" \
  -d '{"prompt":"def hello","n_predict":50}'

# Bonsai CPU (com auth)
KEY=$(cat /home/igor/.config/pcsala-bonsai/api.key)
curl -s -X POST http://192.168.1.150:8090/completion \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"<|im_start|>user\nOla<|im_end|>\n<|im_start|>assistant\n","n_predict":50}'

# Laguna CPU (sem auth, sempre ativo na 8091)
curl -s -X POST http://192.168.1.150:8091/completion \
  -H "Content-Type: application/json" \
  -d '{"prompt":"def hello","n_predict":50}'
```

### 2.4. Resposta da geração

```json
{
  "content": "texto gerado...",
  "tokens_predicted": 30,
  "tokens_evaluated": 2,
  "timings": {
    "prompt_per_second": 18.6,
    "predicted_per_second": 11.9,
    "draft_n": 88,
    "draft_n_accepted": 10
  },
  "generation_settings": {
    "speculative.types": "none,draft-mtp"
  }
}
```

O campo `speculative.types` indica se MTP está ativo: `none,draft-mtp` com MTP, `none,none` sem.

---

## 3. MTP nos modelos

### Bonsai 27B GPU (ativo)
- `--spec-type draft-mtp --spec-draft-n-max 2 --spec-draft-p-min 0.4`
- Drafter separado: `mtp-bonsai2-native-v5b-dv64k.gguf` (1.055.253.344 bytes)
- Aceitação medida (2026-10-23): 0,60-0,87, mean len 2,12-2,65
- Geração: 48,4 tok/s (ctx 27) → 35,1 (ctx 10K) → mediana 32,85 (ctx 10-16K)

### Bonsai 9B CPU (sem MTP)
- **Impossível**: não existe cabeça MTP para 9B publicada; o build CPU `73bfe6c`
  não tem o caminho NEXTN/Hadamard do patch Pascal

### Laguna GPU (não tem MTP)
- Arquitetura Laguna não suporta MTP neste backend

### Ornith GPU (experimental no llama.cpp oficial)
- O GGUF `ornith-1.0-35b-MTP-graft-Q4_K_M.gguf` contém cabeça MTP integrada
- Runtime preferencial (PrismML): ignora nextn.*, faz 40 tok/s sem MTP
- Experimental (llama.cpp oficial): `--spec-type draft-mtp` depth 2, 74% aceitação
- Build experimental: `/home/igor/opt/llama-cuda-official/`

---

## 4. Infraestrutura de serviços

### 4.1. Serviços systemd

| Serviço | Função | Porta | Threads | Auto-início | Status |
|---|---|---|---|---|---|
| `bonsai2-27b.service` | Bonsai 27B GPU + MTP | 8080 | 8 | enabled | active |
| `bonsai2-cpu.service` | Bonsai 9B CPU | 8090 | **32** | enabled | active |
| `laguna.service` | Laguna XS 2.1 CPU | 8091 | 10 | enabled | active |
| `pcsala-worker.service` | Worker LangGraph | — | — | enabled | active |
| `pcsala-bonsai-firewall.service` | Regras nftables | — | — | disabled | active |
| `laguna-gpu.service` | Laguna XS 2.1 GPU | 8082 | 8 | disabled | inactive |
| `ornith.service` | Ornith 35B GPU | 8092 | 8 | disabled | inactive |

### 4.2. Drop-in MTP

```
/etc/systemd/system/bonsai2-27b.service.d/mtp.conf
```

Reversão:
```bash
sudo rm /etc/systemd/system/bonsai2-27b.service.d/mtp.conf
sudo systemctl daemon-reload && sudo systemctl restart bonsai2-27b.service
```

---

## 5. Orçamento de contexto

| Modelo | Contexto | Budget input | Reserva | Margem |
|---|---|---|---|---|
| GPU 27B | 55.000 tok | 47.452 tok | 2.048 tok | 10% |
| CPU 9B | 32.768 tok | 27.443 tok | 2.048 tok | 10% |
| Laguna GPU | 131.072 tok | (pendente) | (pendente) | (pendente) |
| Laguna CPU | 16.384 tok | (pendente) | (pendente) | (pendente) |

---

## 6. Modelos cadastrados

| model_id | Classe | Perfil | Porta | Shared | Runtime | Geração |
|---|---|---|---|---|---|---|
| `bonsai-27b-gpu` | GPU | `gpu-triage-v1` | 8080 | não | PrismML Pascal | **28-48 tok/s** (MTP, ctx-dependente) |
| `laguna-xs-2.1-gpu` | GPU | `laguna-programming-v1` | 8082 | não | PrismML Pascal | **~47 tok/s** |
| `ornith-35b-gpu` | GPU | `gpu-triage-v1` | 8092 | não | PrismML GPU | **~40 tok/s** |
| `bonsai-9b-cpu` | CPU | `cpu-triage-v1` | 8090 | sim | llama.cpp CPU | 6,08 tok/s |
| `laguna-xs-2.1-cpu` | CPU | `laguna-programming-v1` | 8091 | sim | llama.cpp CPU | ~2.6 tok/s |

---

## 7. Segurança

- APIs sem autenticação na LAN (portas 8080,8082,8090,8091,8092)
- Firewall UFW + nftables: apenas LAN (192.168.0.0/16), `INPUT policy DROP`
- **API key removida dos serviços em 2026-10-23** (política: API sim, chave não).
  Um header `Authorization` continua a ser aceite mas é ignorado.
  Backups: `mtp.conf.bak-20261023-165825-with-apikey`, `bonsai2-cpu.service.d/no-apikey.conf`

---

## 8. Resolução de problemas

| Problema | Comando |
|---|---|
| Modelo não inicia | `sudo journalctl -u bonsai2-27b.service -n 30` |
| Laguna/Ornith GPU não inicia | `sudo journalctl -u laguna-gpu.service -n 30` |
| Auth 401 | Não deve acontecer — API sem chave; se aparecer, restaure/remova `--api-key-file` no drop-in |
| Health 503 | Modelo carregando (esperar 30-60s) |
| GPU ocupada | `nvidia-smi` |
| Lock do banco | Worker processando → aguardar |
| MTP não ativo (Bonsai) | Verificar drop-in: `systemctl cat bonsai2-27b.service` |
| MTP não ativo (Ornith) | Usar build experimental em `/home/igor/opt/llama-cuda-official/`