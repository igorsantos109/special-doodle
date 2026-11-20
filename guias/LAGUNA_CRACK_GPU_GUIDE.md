# Guia: Laguna-S-2.1-CRACK Q2_K na Tesla P40 (24 GB VRAM)

> Hardware: 1× NVIDIA Tesla P40 (24 GB VRAM) · 59 GB RAM · Ubuntu Linux  
> Objetivo: Agentic tool-calling + raciocínio, offload MoE experts → CPU, attention/KV → GPU  
> Modelo: `dealignai/Laguna-S-2.1-CRACK-GGUF` (arquivo `Laguna-S-2.1-CRACK-Q2_K.gguf`, ~11 GB)

---

## 1. Preparação do sistema

```bash
# Atualizar e instalar dependências de build
sudo apt update && sudo apt install -y \
  build-essential cmake git curl wget \
  libcurl4-openssl-dev libssl-dev \
  nvidia-cuda-toolkit nvidia-driver-550 \
  htop lsof jq

# Verificar CUDA
nvcc --version
nvidia-smi
```

> **Nota:** Tesla P40 = arquitetura Pascal (sm_60). O driver 550+ suporta.

---

## 2. Compilar llama.cpp (fork Poolside, branch `laguna`)

```bash
# Clonar fork oficial
cd /home/igor
git clone --branch laguna --depth 1 https://github.com/poolside-ai/llama.cpp.git llama.cpp-laguna
cd llama.cpp-laguna

# Build com CUDA (Pascal sm_60)
cmake -B build -DCMAKE_BUILD_TYPE=Release \
  -DLLAMA_CUBLAS=ON \
  -DLLAMA_CUDA=ON \
  -DCMAKE_CUDA_ARCHITECTURES=60 \
  -DLLAMA_NATIVE=OFF

cmake --build build --config Release -j$(nproc)

# Verificar binários
ls -lh build/bin/llama-server build/bin/llama-cli
./build/bin/llama-server --version
```

**Saída esperada:** `llama-server` e `llama-cli` compilados com `CUDA = 1` e `CUBLAS = 1`.

---

## 3. Baixar modelo GGUF (Q2_K ~11 GB)

```bash
# Opção A: huggingface-cli (recomendado, resume se cair)
pip install -U "huggingface_hub[cli]"
huggingface-cli download dealignai/Laguna-S-2.1-CRACK-GGUF \
  --include "Laguna-S-2.1-CRACK-Q2_K.gguf" \
  --local-dir /home/igor/models/laguna-crack-q2k \
  --local-dir-use-symlinks False

# Opção B: wget direto (se HF lento)
# wget -c -P /home/igor/models/laguna-crack-q2k \
#   "https://huggingface.co/dealignai/Laguna-S-2.1-CRACK-GGUF/resolve/main/Laguna-S-2.1-CRACK-Q2_K.gguf"

# Verificar
ls -lh /home/igor/models/laguna-crack-q2k/Laguna-S-2.1-CRACK-Q2_K.gguf
sha256sum /home/igor/models/laguna-crack-q2k/Laguna-S-2.1-CRACK-Q2_K.gguf
```

---

## 4. Comando de execução (llama-server) — offload MoE → CPU

```bash
# Variáveis de ambiente para CUDA
export CUDA_VISIBLE_DEVICES=0
export LD_LIBRARY_PATH=/usr/local/cuda/lib64:${LD_LIBRARY_PATH}

# Executar servidor
/home/igor/llama.cpp-laguna/build/bin/llama-server \
  -m /home/igor/models/laguna-crack-q2k/Laguna-S-2.1-CRACK-Q2_K.gguf \
  --host 0.0.0.0 \
  --port 8082 \
  -c 32768 \
  -ngl 35 \
  -ot moe \
  --n-cpu-moe 8 \
  --flash-attn \
  --jinja \
  --parallel 2 \
  --threads 20 \
  --ctx-size 32768 \
  --batch-size 512 \
  --ubatch-size 512 \
  --no-mmap \
  --mlock \
  --verbose
```

### Explicação das flags críticas

| Flag | Valor | Porquê |
|------|-------|--------|
| `-ngl 35` | 35 camadas na GPU | Atenção + router + primeiras camadas; ~20-21 GB VRAM na P40 |
| `-ot moe` | offload type MoE | Ativa roteamento de experts para CPU |
| `--n-cpu-moe 8` | 8 experts na CPU | Máximo paralelo na CPU (24 threads Xeon); ajuste 6-10 conforme carga |
| `-c 32768` | contexto 32K | Equilíbrio VRAM/RAM; 262K estoura VRAM (KV cache ~14 GB extra) |
| `--flash-attn` | ON | Atenção flash economiza VRAM e acelera prefill |
| `--no-mmap` | ON | Carrega tudo na RAM (59 GB sobra); evita page faults em inferência longa |
| `--mlock` | ON | Impede swap do modelo (precisa `ulimit -l unlimited`) |
| `--jinja` | ON | Template de chat nativo do modelo |
| `--parallel 2` | 2 slots paralelos | Para agentic tool-calling simultâneo |
| `--threads 20` | 20 threads CPU | Deixa 4 threads livres p/ SO / outros processos |

> **Ajuste fino de `-ngl`**: Comece com 35. Se `CUDA out of memory`, baixe para 32, 30... Cada camada ≈ 500-600 MB VRAM em Q2_K. Monitore com `nvidia-smi -l 1`.

---

## 5. Verificação em tempo real

```bash
# Terminal 1: VRAM GPU (atualiza a cada 1s)
watch -n 1 nvidia-smi

# Terminal 2: RAM/CPU sistema
htop

# Terminal 3: Logs do servidor (já aparece no terminal onde rodou)
# Procure por:
# - "gguf: loading model... done"
# - "cuda: offloaded 35/XX layers to GPU"
# - "moe: offloading XX experts to CPU"
# - "HTTP server listening on 0.0.0.0:8082"
```

### Teste rápido de saúde

```bash
# Health check
curl -s http://127.0.0.1:8082/health

# Completion simples
curl -s http://127.0.0.1:8082/v1/completions \
  -H "Content-Type: application/json" \
  -d '{"prompt":"<|im_start|>user\nOlá<|im_end|>\n<|im_start|>assistant\n","max_tokens":50,"temperature":0.7}'

# Chat completions (tool-calling)
curl -s http://127.0.0.1:8082/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Qual a capital do Brasil?"}],"max_tokens":100,"temperature":0.7}'
```

---

## 6. Erros comuns e soluções

| Erro | Causa | Solução |
|------|-------|---------|
| `Unsupported architecture: laguna` | llama.cpp upstream não tem suporte | **Use o fork Poolside branch `laguna`** (passo 2) |
| `CUDA out of memory` | `-ngl` alto demais para 24 GB | Reduza `-ngl 35` → `32` → `30`; desative `--flash-attn` se persistir |
| `gguf: unsupported MoE type` | Build sem suporte MoE | Recompile com `-DLLAMA_CUBLAS=ON -DLLAMA_CUDA=ON`; verifique `llama-server --version` mostra `MOE = 1` |
| `failed to load model: mmap failed` | `--no-mmap` sem RAM suficiente | Remova `--no-mmap` ou feche outros processos; 59 GB basta para Q2_K + KV 32K |
| `jinja: template not found` | Modelo sem template chat | Remova `--jinja` e use formato raw: `<|im_start|>user\n...<|im_end|>` |
| Servidor inicia mas `/health` falha | Porta ocupada / bind errado | `ss -tlnp | grep 8082`; mude `--port` ou mate processo antigo |

---

## 7. Systemd service (produção)

```bash
sudo tee /etc/systemd/system/laguna-crack.service > /dev/null <<'EOF'
[Unit]
Description=Laguna-S-2.1-CRACK Q2_K llama-server
After=network.target nvidia-persistenced.service
Requires=nvidia-persistenced.service

[Service]
Type=simple
User=igor
Group=igor
WorkingDirectory=/home/igor/llama.cpp-laguna
Environment=CUDA_VISIBLE_DEVICES=0
Environment=LD_LIBRARY_PATH=/usr/local/cuda/lib64
ExecStart=/home/igor/llama.cpp-laguna/build/bin/llama-server \
  -m /home/igor/models/laguna-crack-q2k/Laguna-S-2.1-CRACK-Q2_K.gguf \
  --host 0.0.0.0 --port 8082 \
  -c 32768 -ngl 35 -ot moe --n-cpu-moe 8 \
  --flash-attn --jinja --parallel 2 --threads 20 \
  --ctx-size 32768 --batch-size 512 --ubatch-size 512 \
  --no-mmap --mlock --verbose
Restart=on-failure
RestartSec=10
LimitMEMLOCK=infinity
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=full
ProtectHome=read-only

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now laguna-crack.service
sudo journalctl -u laguna-crack.service -f
```

---

## 8. Integração com DSH (opcional)

Adicione ao `~/.dsh/profiles/web/cordis.patch.yml` (provider `llm-newapi` → `models`):

```yaml
laguna-crack:
  displayName: Laguna-S-2.1-CRACK Q2_K GPU (P40:8082, 32K MoE→CPU)
  apiKeyEnv: PCSALA_LOCAL_API_KEY
  api: openai-completions
  baseURL: http://192.168.1.184:8082/v1
  timeoutMs: 10800000
  streamIdleTimeoutMs: 5400000
  reasoning: off
  compat:
    supportsDeveloperRole: false
    maxTokensField: max_tokens
  models:
    - id: laguna-s-2.1-crack-q2k
      name: Laguna-S-2.1-CRACK Q2_K (MoE CPU offload, 32K)
      contextWindow: 32768
      maxTokens: 4096
      reasoning: off
      input:
        - text
```

Reinicie GUI: `pnpm run dev:web` (no diretório do DSH).

---

## 9. Referências rápidas

- **Modelo HF:** https://huggingface.co/dealignai/Laguna-S-2.1-CRACK-GGUF
- **Fork llama.cpp:** https://github.com/poolside-ai/llama.cpp/tree/laguna
- **Offload MoE docs:** `llama-server --help | grep -A5 -i moe`
- **Contexto 262K oficial:** Requer ~40 GB VRAM só de KV — **não viável na P40**. Use 32K.