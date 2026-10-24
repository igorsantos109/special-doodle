# PLANO MTP — Bonsai 2 27B GPU (P40)

## 1. Estado atual inspecionado (22/10/2026 17:43 UTC)

### GPU
| Item | Valor |
|---|---|
| GPU | Tesla P40 (23.040 MiB) |
| Ocupante | Ornith (PID 5915, 20.800 MiB VRAM) |
| Bonsai2-27b service | enabled, inactive |
| Bonsai2-27b binary | `/home/igor/opt/prism-gpu-build/install/bin/llama-server` |
| Commit | `73bfe6c` (build 1, v0.2.0-dev) |
| GPU util. | 0 % |

### Serviço Bonsai (backup confere com o atual)
```
ExecStart=.../llama-server \
    -m /home/igor/models/bonsai-2-27b/Ternary-Bonsai-2-27B-PQ2_0.gguf \
    --host 127.0.0.1 --port 8080 \
    -c 55000 -t 8 -ngl 99 --no-kv-offload -n 2048 \
    --parallel 1 --no-jinja --threads-http 4 \
    --api-key-file /home/igor/.config/pcsala-bonsai/api.key
```
Backup em `/home/igor/models/ornith/backup-bonsai2-27b.service.bak` — confere com o atual.

### Binário atual já oferece `--spec-type draft-mtp` e `--model-draft`
O binário `73bfe6c` já possui suporte ao protocolo MTP no server. Porém:
- Foi compilado sem `GGML_CUDA_FORCE_MMQ=ON` (OFF no cache)
- Não contém o patch Pascal (row-lane PQ2_0, Hadamard path, NEXTN arch)
- A base PrismML `73bfe6c` pode ser diferente da base alvo `5d80cff`

Implicação: o binário atual pode carregar o drafter e iniciar, mas a rota Hadamard para os pesos da cabeça MTP pode falhar na P40 sem as otimizações do patch Pascal.

### Gestor de modelos
- `reserve_engine()` e `release_engine()` estão implementados no `ModelCoordinator`
- **Não são chamados pelo worker** (`graph_runner.py` chama apenas `ensure_model_ready`)
- Reservas são um dict em memória — não sobrevivem a reinício
- GPU switch usa lock de arquivo (`/tmp/pcsala-gpu-switch.lock`)
- CUDA_VISIBLE_DEVICES **não é gerenciado** — o gestor não controla qual GPU o processo usa

### Tarefa 6
- `id=6`, status `RESERVED`, attempt `9ffcf4dd9f4be5a02b2059d23206582e`
- Preservada, não modificada

### Drafter
- Não baixado (`/home/igor/models/bonsai-2-27b/` contém apenas o GGUF principal)
- SHA-256 esperado: `9d11de22b83258b1b16ea7c73b0148d9c38a96f0cc0c077c55b9ce676ba287e7`
- Tamanho: ~1.055.253.344 bytes (~1 GB)

### Disco e compilação
| Recurso | Disponível |
|---|---|
| Disco livre | 150 GB (raiz `/`) |
| RAM | 30 GB (27 GB available) |
| cmake | 4.2.3 |
| gcc | 15.2.0 |
| CUDA toolkit | 12.4.131 (nvcc) |
| Driver NVIDIA | 580.178.04 |
| GPU arch target (build atual) | não especificado no CMakeCache → default |

## 2. Referências fixadas

### Repositório do patch
- **URL**: https://github.com/killy-netsphere/bonsai2-1080ti
- **Commit que contém o patch**: `712c505d35c8db1fc62d47a83b2dfda22030fff3`
- **Arquivo do patch**: `bonsai2-pascal.patch`
- **Commits posteriores** (README.md apenas): `ec4f822`, `8cb56e7`
- **Base PrismML exigida**: `5d80cff0b8cb9f2bf823cfc4e71e3abb97f290d6`
- **Link da base**: https://github.com/PrismML-Eng/llama.cpp/commit/5d80cff0b8cb9f2bf823cfc4e71e3abb97f290d6

### Variáveis de ambiente necessárias (runtime)
```
GGML_CUDA_ROWLANE=1     → ativa kernel row-lane PQ2_0 para Pascal
GGML_CUDA_RL_N4_LONG=1  → ativa variante N=4 long-row do kernel row-lane
```

Ambas são obrigatórias para o kernel row-lane PQ2_0 na P40 (sm_61). Sem elas, a mul_mat para pesos PQ2_0 no drafter pode cair em fallback lento ou falhar.

### Opções CMake para P40
```
-DCMAKE_CUDA_ARCHITECTURES=61
-DGGML_CUDA_FORCE_MMQ=ON
-DGGML_CUDA_GRAPHS=ON
-DGGML_CUDA_FA=ON
-DGGML_NATIVE=OFF
-DLLAMA_CURL=OFF
-DLLAMA_BUILD_TESTS=OFF
-DLLAMA_BUILD_EXAMPLES=ON
-DLLAMA_BUILD_SERVER=ON
-DCMAKE_BUILD_TYPE=Release
```

## 3. Procedimento de compilação (comandos completos)

### 3.1 Preparar diretórios
```bash
mkdir -p /home/igor/opt/prism-pascal-build/source
mkdir -p /home/igor/opt/prism-pascal-build/build
```

### 3.2 Obter fonte na revisão fixada
```bash
git -c core.autocrlf=false clone \
  https://github.com/PrismML-Eng/llama.cpp \
  /home/igor/opt/prism-pascal-build/source
cd /home/igor/opt/prism-pascal-build/source
git checkout 5d80cff0b8cb9f2bf823cfc4e71e3abb97f290d6
```

### 3.3 Obter e verificar o patch
```bash
cd /home/igor/opt/prism-pascal-build
git clone https://github.com/killy-netsphere/bonsai2-1080ti patch-source
# Alternativa sem clone extra:
# curl -L -o bonsai2-pascal.patch \
#   https://raw.githubusercontent.com/killy-netsphere/bonsai2-1080ti/712c505d35c8db1fc62d47a83b2dfda22030fff3/bonsai2-pascal.patch
```

### 3.4 Aplicar patch
```bash
cd /home/igor/opt/prism-pascal-build/source
git apply --check /home/igor/opt/prism-pascal-build/bonsai2-pascal.patch
git apply /home/igor/opt/prism-pascal-build/bonsai2-pascal.patch
```

### 3.5 CMake configure
```bash
cmake -S /home/igor/opt/prism-pascal-build/source \
      -B /home/igor/opt/prism-pascal-build/build \
      -G "Unix Makefiles" \
      -DCMAKE_BUILD_TYPE=Release \
      -DGGML_CUDA=ON \
      -DCMAKE_CUDA_ARCHITECTURES=61 \
      -DGGML_CUDA_FORCE_MMQ=ON \
      -DGGML_CUDA_GRAPHS=ON \
      -DGGML_CUDA_FA=ON \
      -DGGML_NATIVE=OFF \
      -DLLAMA_CURL=OFF \
      -DLLAMA_BUILD_TESTS=OFF \
      -DLLAMA_BUILD_EXAMPLES=ON \
      -DLLAMA_BUILD_SERVER=ON
```

### 3.6 Compilar
```bash
cmake --build /home/igor/opt/prism-pascal-build/build --config Release -j$(nproc)
```

### 3.7 Verificar binário
```bash
ls -lh /home/igor/opt/prism-pascal-build/build/bin/llama-server
/home/igor/opt/prism-pascal-build/build/bin/llama-server --version
/home/igor/opt/prism-pascal-build/build/bin/llama-server --help 2>&1 | grep -E "(spec-type|model-draft|rowlane)"
```

## 4. Download verificável do drafter

### Destino
```bash
DEST_DIR="/home/igor/models/bonsai-2-27b"
DEST_FILE="${DEST_DIR}/mtp-bonsai2-native-v5b-dv64k.gguf"
TEMP_FILE=$(mktemp -p /tmp mtp-drafter.XXXXXX)
```

### URL
```
https://huggingface.co/killy369/Ternary-Bonsai-2-27B-MTP-drafter-GGUF/resolve/main/mtp-bonsai2-native-v5b-dv64k.gguf
```

### SHA-256 esperado
```
9d11de22b83258b1b16ea7c73b0148d9c38a96f0cc0c077c55b9ce676ba287e7
```

### Procedimento (não executar agora)
```bash
if [ -f "$DEST_FILE" ]; then
    echo "AVISO: drafter ja existe em $DEST_FILE"
    echo "SHA-256 existente: $(sha256sum "$DEST_FILE" | cut -d' ' -f1)"
    echo "Deseja sobrescrever? (s/N)"
    read -r resp
    [ "$resp" != "s" ] && exit 1
fi

curl -L -o "$TEMP_FILE" \
  "https://huggingface.co/killy369/Ternary-Bonsai-2-27B-MTP-drafter-GGUF/resolve/main/mtp-bonsai2-native-v5b-dv64k.gguf"

SIZE=$(stat -c%s "$TEMP_FILE")
if [ "$SIZE" -ne 1055253344 ]; then
    echo "ERRO: tamanho incorreto: $SIZE (esperado 1055253344)"
    rm -f "$TEMP_FILE"
    exit 1
fi

SHA=$(sha256sum "$TEMP_FILE" | cut -d' ' -f1)
if [ "$SHA" != "9d11de22b83258b1b16ea7c73b0148d9c38a96f0cc0c077c55b9ce676ba287e7" ]; then
    echo "ERRO: SHA-256 nao confere: $SHA"
    rm -f "$TEMP_FILE"
    exit 1
fi

mv "$TEMP_FILE" "$DEST_FILE"
echo "OK: drafter validado e salvo em $DEST_FILE"
```

## 5. Ensaio temporário (após Autorização B)

### Pré-requisitos
- Ornith parado (processo PID 5915)
- Nenhuma tarefa GPU em execução
- Tarefa 6 não cancelada (não interfere)
- Build Pascal compilado

### Comando do ensaio
```bash
GGML_CUDA_ROWLANE=1 \
GGML_CUDA_RL_N4_LONG=1 \
/home/igor/opt/prism-pascal-build/build/bin/llama-server \
    -m /home/igor/models/bonsai-2-27b/Ternary-Bonsai-2-27B-PQ2_0.gguf \
    -md /home/igor/models/bonsai-2-27b/mtp-bonsai2-native-v5b-dv64k.gguf \
    --spec-type draft-mtp \
    --host 127.0.0.1 \
    --port 8081 \
    -c 32768 \
    -t 8 \
    -ngl 99 \
    --no-kv-offload \
    -n 2048 \
    --parallel 1 \
    --no-jinja \
    --threads-http 4 \
    --api-key-file /home/igor/.config/pcsala-bonsai/api.key \
    --spec-draft-n-max 5 \
    2>&1 | tee /tmp/mtp-trial-$(date +%Y%m%d-%H%M%S).log
```

Notas sobre parâmetros:
- Porta 8081 (evita conflito com Ornith se ainda estiver ativo)
- Contexto reduzido para 32768 (com mudança de `--no-kv-offload` para `--no-kv-offload` mantido, o KV fica em VRAM; com drafter cabe ~18-19 GB + drafter pesos → P40 com 23 GB fica justo)
- 32768 não é o limite máximo confirmado — é um valor seguro para o ensaio
- `--spec-draft-n-max 5`: 5 tokens draft (padrão é 3, 2 para draft-mtp CUDA — usar o próprio padrão ou explicitamente 5 conforme documentado)

### Verificações do ensaio
1. **Carregamento**: processo inicia sem `failed to create llama_context`
2. **Saúde autenticada**:
   ```bash
   curl -s -o /dev/null -w "%{http_code}" \
     -H "Authorization: Bearer $(cat /home/igor/.config/pcsala-bonsai/api.key)" \
     http://127.0.0.1:8081/health
   ```
   → deve retornar 200
3. **Geração real**:
   ```bash
   curl -s -X POST \
     -H "Authorization: Bearer $(cat /home/igor/.config/pcsala-bonsai/api.key)" \
     -H "Content-Type: application/json" \
     -d '{"prompt":"MTP","n_predict":50}' \
     http://127.0.0.1:8081/completion | jq .
   ```
4. **Evidência do drafter nos logs**: grep por `mtp`, `draft`, `spec` no log do servidor
5. **Consumo de VRAM**: `nvidia-smi` antes/durante/depois
6. **Encerramento**: `kill %1` ou `pkill -f "llama-server.*8081"`

### Rollback do ensaio
```bash
pkill -f "llama-server.*8081" 2>/dev/null
# Ornith pode ser religado com seu serviço original
```

## 6. Troca de GPU — coordenação

### Problema identificado
O gestor `_engine_reservations` é um dict em memória que **não é populado pelo worker**. O worker (`graph_runner.py:101-106`) chama `ensure_model_ready()` mas nunca chama `reserve_engine()`. Portanto:

- `request_stop()` pode rejeitar com "BUSY" mesmo sem inferência real
- `request_switch()` confere reservas que podem ser irreais
- A trava real é o lock de arquivo `/tmp/pcsala-gpu-switch.lock`

### Procedimento proposto para troca (manutenção administrativa)
```bash
# 1. Verificar consumidores
ps aux | grep llama-server
nvidia-smi

# 2. (Se Ornith) Parar Ornith
sudo systemctl stop ornith.service   # ou kill conforme documentação do serviço

# 3. Verificar GPU livre
nvidia-smi

# 4. Iniciar ensaio ou config permanent (conforme autorizado)
./pcsala models start bonsai-27b-gpu   # se Ornith parado, inicia Bonsai
```

O gestor pode ser usado como verificador, mas a mudança real requer ação administrativa porque:
- Não há coordenação de CUDA_VISIBLE_DEVICES
- O gestor não gerencia o processo Ornith (não está no registro)
- Reservas em memória não refletem estado real

## 7. Configuração permanente (diff do serviço)

### Alteração proposta
```diff
--- a) serviço atual (porta 8080, sem MTP)
+++ b) serviço com MTP
@@ -1,11 +1,14 @@
-ExecStart=/home/igor/opt/prism-gpu-build/install/bin/llama-server \
+ExecStart=/home/igor/opt/prism-pascal-build/build/bin/llama-server \
     -m /home/igor/models/bonsai-2-27b/Ternary-Bonsai-2-27B-PQ2_0.gguf \
+    -md /home/igor/models/bonsai-2-27b/mtp-bonsai2-native-v5b-dv64k.gguf \
+    --spec-type draft-mtp \
     --host 127.0.0.1 \
     --port 8080 \
-    -c 55000 \
+    -c 32768 \
     -t 8 \
     -ngl 99 \
     --no-kv-offload \
     -n 2048 \
     --parallel 1 \
     --no-jinja \
     --threads-http 4 \
     --api-key-file /home/igor/.config/pcsala-bonsai/api.key
+
+Environment=GGML_CUDA_ROWLANE=1
+Environment=GGML_CUDA_RL_N4_LONG=1
```

### Impacto da redução de contexto (55000 → 32768)
- Redução de ~40% no contexto disponível
- O orçamento de input (47452 → ~27443 tokens para o profile gpu-triage-v1) precisa ser recalculado
- Isso é uma mudança independente, não autorizada pelo escopo MTP
- Alternativa: manter 55000 e medir VRAM disponível após carregar drafter

**Decisão**: manter 32768 **apenas** no ensaio. Para config permanente, medir primeiro.

### Aplicação (drop-in recomendado)
```bash
sudo mkdir -p /etc/systemd/system/bonsai2-27b.service.d/
sudo tee /etc/systemd/system/bonsai2-27b.service.d/mtp.conf << 'EOF'
[Service]
ExecStart=
ExecStart=/home/igor/opt/prism-pascal-build/build/bin/llama-server \
    -m /home/igor/models/bonsai-2-27b/Ternary-Bonsai-2-27B-PQ2_0.gguf \
    -md /home/igor/models/bonsai-2-27b/mtp-bonsai2-native-v5b-dv64k.gguf \
    --spec-type draft-mtp \
    --host 127.0.0.1 \
    --port 8080 \
    -c 32768 \
    -t 8 \
    -ngl 99 \
    --no-kv-offload \
    -n 2048 \
    --parallel 1 \
    --no-jinja \
    --threads-http 4 \
    --api-key-file /home/igor/.config/pcsala-bonsai/api.key
Environment=GGML_CUDA_ROWLANE=1
Environment=GGML_CUDA_RL_N4_LONG=1
EOF
sudo systemctl daemon-reload
```

## 8. Reversão

### Reverter apenas MTP (sem excluir build ou drafter)
```bash
# Opção 1: remover drop-in
sudo rm -f /etc/systemd/system/bonsai2-27b.service.d/mtp.conf
sudo systemctl daemon-reload

# Opção 2: restaurar backup conhecido
sudo cp /home/igor/models/ornith/backup-bonsai2-27b.service.bak \
       /etc/systemd/system/bonsai2-27b.service
sudo systemctl daemon-reload
```

A reversão:
- Mantém `/home/igor/opt/prism-pascal-build/` (build novo)
- Mantém `/home/igor/models/bonsai-2-27b/mtp-bonsai2-native-v5b-dv64k.gguf` (drafter)
- Mantém task 6 intocada
- Não altera CPU, firewall, ou outros modelos
- Restaura `-c 55000` (contexto original)

## 9. Pendências do gestor (não bloqueiam MTP)

1. `reserve_engine()` / `release_engine()` não são chamados pelo worker
2. Sem coordenação de CUDA_VISIBLE_DEVICES
3. Processos não gerenciados (Ornith) não são detectados pelo `_find_active_gpu()`
4. `_find_active_gpu()` só consulta systemctl, não nvidia-smi

Nenhuma impede o ensaio MTP, mas devem ser documentadas.

## 10. Autorizações necessárias

### AUTORIZAÇÃO A — Preparação (sem parar modelos)

O que será feito:
1. Clonar PrismML base `5d80cff` em `/home/igor/opt/prism-pascal-build/source/` (~3 GB)
2. Clonar patch repo em `/home/igor/opt/prism-pascal-build/patch-source/` (~pequeno)
3. Aplicar patch e compilar em `/home/igor/opt/prism-pascal-build/build/` (~300 MB)
4. Baixar drafter (~1 GB) para `/home/igor/models/bonsai-2-27b/mtp-bonsai2-native-v5b-dv64k.gguf`
5. Validar SHA-256 do drafter

Impacto: ~4.5 GB de download, ~4 GB de compilação temporária, 150 GB livres. Sem parada de modelos.

### AUTORIZAÇÃO B — Ensaio na GPU

O que será feito:
1. Parar Ornith (PID 5915, 20.800 MiB VRAM)
2. Iniciar binário compilado em porta 8081 (não interfere no serviço)
3. Executar health check + geração curta
4. Verificar logs para evidência de drafter
5. Encerrar processo temporário
6. Relatar resultado

Duração estimada: ~15 minutos com risco de falha no carregamento (se o binário atual já carrega o drafter, ou se o patch Pascal é necessário — a resposta `failed to create llama_context` confirmará).

Recuperação em caso de falha: `pkill -f "llama-server.*8081"` e religar Ornith.

### Após ensaio bem-sucedido — config permanente (autorização separada)

Se o ensaio confirmar funcionamento, será proposto:
- Aplicar drop-in `mtp.conf` no serviço
- Atualizar orçamentos de contexto no profile
- Atualizar `PROJECT_STATE.md` e `CONTINUITY.md`

---

## Resumo das diferenças runtime atual vs. proposto

| Aspecto | Runtime atual (73bfe6c) | Proposto (5d80cff + patch) |
|---|---|---|
| Base PrismML | 73bfe6c | 5d80cff0 |
| Patch Pascal | Não | Sim (712c505) |
| MTP protocol | Suportado | Suportado |
| Row-lane PQ2_0 | Não | Sim (P40) |
| Hadamard path | Não | Sim |
| NEXTN arch | Não | Sim |
| CUDA sm target | Default (todas) | 61 (Pascal) |
| FORCE_MMQ | OFF | ON |
| Contexto | 55000 | 32768 (ensaio) / a medir (perm) |
| Env vars MTP | N/A | GGML_CUDA_ROWLANE, GGML_CUDA_RL_N4_LONG |