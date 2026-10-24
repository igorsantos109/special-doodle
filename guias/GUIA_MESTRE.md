# GUIA MESTRE — PC-SALA-AGENT

**Versão:** 8.2 — Completo (consolidação documental e ajustes)
**Data:** 22/10/2026 22:20 UTC
**Responsável:** Igor Estevam Santos de Oliveira
**Host:** PC-SALA (`pc-sala`, IP `192.168.1.150`)
**SO:** LMDE/Linux, kernel 6.x
**Projeto:** `/home/igor/pc-sala-agent`

---

## 1. VISÃO GERAL DA ARQUITETURA

```
    CLI pcsala                          CLI ia (gestor)
       |                                     |
       v                                     v
    Worker (pcsala-worker.service)     ModelCoordinator (Python)
       |                                     |
       v                                     v
    LangGraph (grafo de inferencia)     systemctl → servicos systemd
       |                                     |
       v                                     v
    Servidores de inferencia (llama-server)
       |
       +-- http://0.0.0.0:8080  Bonsai 27B GPU + MTP   (primário)
       +-- http://0.0.0.0:8082  Laguna XS 2.1 GPU       (alternativo GPU)
       +-- http://0.0.0.0:8090  Bonsai 9B CPU           (auxiliar)
       +-- http://0.0.0.0:8091  Laguna XS 2.1 CPU       (desativado — RAM)
       +-- http://0.0.0.0:8092  Ornith 35B GPU           (alternativo GPU)
```

---

## 2. HARDWARE

| Componente | Especificação |
|---|---|
| CPU | Intel Xeon E5-2697 v4, 36 threads @ 2.30 GHz |
| ISA | x86_64, AVX2, FMA, BMI2 |
| RAM | 30 GiB total (~16 GiB disponível) |
| GPU | NVIDIA Tesla P40 (23.040 MiB, CC 6.1 Pascal) |
| SSD | XrayDisk 256 GB (sistema, 148 GB livres) |
| HDD | HGST 465 GB (dados, em `/mnt/arquivos`, 435 GB livres) |
| Rede | 192.168.1.150/24 (enp6s0) |
| CUDA | Toolkit 12.4.131, Driver 580.178.04 |

---

## 3. MODELOS DE IA

### 3.1. Bonsai 2 27B GPU (PRINCIPAL — com MTP)

| Campo | Valor |
|---|---|
| Modelo | `Ternary-Bonsai-2-27B-PQ2_0.gguf` (6,8 GB) |
| Drafter MTP | `mtp-bonsai2-native-v5b-dv64k.gguf` (1.055.253.344 B) |
| SHA-256 (modelo) | `3907dc1658db1f78a9826bf8d5bcb8dc65db0d466388937af57f2294fae62ec1` |
| SHA-256 (drafter) | `9d11de22b83258b1b16ea7c73b0148d9c38a96f0cc0c077c55b9ce676ba287e7` |
| Serviço | `bonsai2-27b.service` (enabled, active) |
| Drop-in | `/etc/systemd/system/bonsai2-27b.service.d/mtp.conf` |
| Binário | `/home/igor/opt/prism-pascal-build/build/bin/llama-server` |
| Build | `5d80cff0b8cb9f2bf823cfc4e71e3abb97f290d6` (build_info `b10687-5d80cff0b`) — PrismML + patch Pascal |
| Patch | `killy-netsphere/bonsai2-1080ti` commit `712c505`, SHA-256 `f8aeebbc...50b9` (aplicado e verificado) |
| Porta | **8080** (0.0.0.0, **sem API key** — API obrigatória, chave não) |
| Contexto | 64.000 tokens (`-c 64000`, elevado de 55.000 em 2026-10-23 para absorver prompts do dsh de 56K tok) |
| GPU VRAM | ~12,9 GB (modelo + drafter + KV, 23,0 GB P40) |
| MTP | `--spec-type draft-mtp --spec-draft-n-max 2 --spec-draft-p-min 0.4` |
| Outras flags | `--backend-sampling --flash-attn on -ngl 99 -ngld 99 -t 8 -n 2048 --parallel 1 --threads-http 4` |
| Env MTP | `GGML_CUDA_ROWLANE=1`, `GGML_CUDA_RL_N4_LONG=1`, `LD_LIBRARY_PATH=<build/bin>` |
| Warm-up | `ExecStartPost=-/home/igor/pc-sala-agent/scripts/bonsai-warmup.sh` + `TimeoutStartSec=300` |
| Prompt eval | **236-243 tok/s** (contexto vazio) → **126-186 tok/s** (contexto 10-17K) |
| Geração | **48,4 tok/s** (ctx 27) / 40,2 (ctx 564) / 35,1 (ctx 10K) / **27,8-37,5** (ctx 10-16K, mediana 32,85) |
| Acceptance MTP | 0,60-0,87, mean len 2,12-2,65 |
| Sem MTP | 25,4 tok/s (referência histórica: 50,81 com MTP, 25,71 sem) |

**Matriz A/B (384 tokens, GPU ociosa):** sem MTP 25,4 | actual **44,0** | `n-max 5`+`p-min 0,1` 38,2 |
idem sem flash-attn 36,2. A configuração actual é a melhor.

**`--cache-reuse` não é suportado** (`cache_reuse is not supported by this context`):
`llama_kv_cache::get_can_shift()` devolve `false` porque `n_pos_per_embd() > 1`
(`rope_type` MROPE, `qwen35.rope.dimension_sections`). É propriedade do modelo.
`ctx_shift` é desactivado pela mesma razão.

**Primeiro pedido após ocioso ≈ 14 tok/s** (clocks descem de 1531 → 1303 MHz em 5 s);
pedidos contíguos ≈ 24 tok/s (respostas de 16 tokens). Travar clocks custaria
+6 a +17 kWh/mês — decisão: manter como está.

### 3.2. Bonsai 2 9B CPU (AUXILIAR)

| Campo | Valor |
|---|---|
| Modelo | `Ternary-Bonsai-2-9B-PQ2_0.gguf` (2.4 GB) |
| SHA-256 | `7a89ab48...` |
| Serviço | `bonsai2-cpu.service` (enabled, active) |
| Drop-in | `/etc/systemd/system/bonsai2-cpu.service.d/no-apikey.conf` |
| Binário | `/home/igor/opt/prism-cpu-install-aswyUW/install/bin/llama-server` (`73bfe6c`) |
| Porta | **8090** (0.0.0.0, **sem API key**) |
| Contexto | 32.768 tokens |
| Threads | 32 (testado: 18→4.9, 24→5.25, 32→5.75, 36→5.24 tok/s) |
| Performance | Prompt: ~18-20 tok/s, Geração: **6,08 tok/s** (medido 2026-10-23) |

#### MTP no 9B — IMPOSSÍVEL (verificado 2026-10-23)

Três bloqueios independentes, nenhum contornável por configuração:

1. **Não existe cabeça MTP para 9B.** No HuggingFace, `killy369` publicou apenas
   `Ternary-Bonsai-2-27B-MTP-drafter-GGUF`. Buscas por `Bonsai-2-9B-MTP`,
   `…-9B-drafter`, `…-9B-draft` → nenhum resultado.
2. **O único drafter é estruturalmente do 27B.** `mtp-bonsai2-native-v5b-dv64k.gguf`
   contém 8 ocorrências de `nextn` e 18 de `blk.64.`; o GGUF do 9B tem **0** de ambas.
3. **O build CPU não tem o caminho NEXTN/Hadamard.** Teste de carga:
   `prism.hadamard: weight 'blk.64.nextn.shared_head_head.weight' is not on a verified Hadamard-aware matmul path`
   (o patch Pascal existe só no build `5d80cff0b`).

Medido em porta temporária, sem tocar no serviço: baseline **6,08 tok/s**,
`--spec-type ngram-map-k` **6,06 tok/s** (arranca, sem ganho). Decisão: manter como está.

### 3.3. Laguna XS 2.1 CPU (PROGRAMAÇÃO/DEPURAÇÃO — DESATIVADO)

| Campo | Valor |
|---|---|
| Modelo | `Laguna-XS-2.1-APEX-I-Compact.gguf` (15 GB) |
| SHA-256 | `b674541db815d8829e4c57bd56cffebbd49e9822e284e69f199ae7fbd0b705d2` |
| Arquitetura | LagunaForCausalLM (MoE, 33B total, ~3B ativos/token, 256 expertos, 8 usados/token, 40 camadas) |
| Serviço | `laguna.service` (disabled, inactive) |
| Binário | CPU (prism-cpu-install-aswyUW) |
| Porta | **8091** (0.0.0.0, sem auth) |
| Contexto | 16.384 tokens |
| Prompt eval | ~1.4 tok/s |
| Geração | ~2.6 tok/s |
| Nota | **Desativado para liberar RAM (~18 GB)**. GPU Laguna é 18x mais rápido. Reativar com `sudo systemctl enable --now laguna.service` |

### 3.4. Laguna XS 2.1 GPU (PROGRAMAÇÃO/DEPURAÇÃO — NOVO)

| Campo | Valor |
|---|---|
| Modelo | `Laguna-XS-2.1-APEX-I-Compact.gguf` (15 GB) |
| Arquitetura | LagunaForCausalLM (MoE, 40 camadas, 256 expertos, 8 usados/token) |
| Serviço | `laguna-gpu.service` (disabled, inactive — troca via gestor) |
| Binário | Pascal (prism-pascal-build/build/bin/llama-server + libllama-server-impl.so) |
| Build | `5d80cff0b` (build 10687) — **mesma build do Bonsai MTP** |
| Porta | **8082** (0.0.0.0, sem auth) |
| Contexto | 131.072 tokens (máx 150K, 200K OOM) |
| Prompt eval | ~55-70 tok/s |
| Geração | ~40-47 tok/s |
| VRAM | 15,9 GB (4K ctx) → 21,2 GB (150K ctx) |
| Conflitos | `bonsai2-27b.service`, `ornith.service` (GPU exclusiva) |
| Troca | `./pcsala models switch laguna-xs-2.1-gpu` |

### 3.5. Ornith 35B GPU (ALTERNATIVO — REATIVADO)

| Campo | Valor |
|---|---|
| Modelo | `ornith-1.0-35b-MTP-graft-Q4_K_M.gguf` (21 GB) |
| Arquitetura | **qwen35moe** (41 blocos, `nextn_predict_layers: 1`, cabeça MTP integrada) |
| SHA-256 | (verificar com `sha256sum`) |
| Runtime preferencial | **PrismML GPU build** (`prism-gpu-build` — 40 tok/s, ignora nextn.*) |
| Serviço | `ornith.service` (disabled, inactive — troca via gestor) |
| Binário (PrismML) | `prism-gpu-build/install/bin/llama-server` |
| Porta | **8092** (0.0.0.0, sem auth) |
| Contexto | 16.384 tokens |
| Prompt eval | ~54 tok/s (PrismML) |
| Geração | ~40 tok/s (PrismML) |
| VRAM | ~19.4 GB (4K contexto) |
| Conflitos | `bonsai2-27b.service`, `laguna-gpu.service` (GPU exclusiva) |
| Troca | `./pcsala models switch ornith-35b-gpu` |

#### MTP do Ornith — experimental (llama.cpp oficial)

O GGUF contém cabeça MTP integrada (`nextn_predict_layers: 1`, 753 tensores). O runtime PrismML ignora os tensores `nextn.*`. Para ativar MTP, usar o build experimental do llama.cpp oficial:

| Campo | Valor |
|---|---|
| Build | `/home/igor/opt/llama-cuda-official/` (commit `73bfe6c`, independente) |
| Flags | `--spec-type draft-mtp` (depth 2 implícito) |
| Geração (com MTP) | **24.7 tok/s** (vs 18.7 tok/s sem MTP = 1.32x) |
| Taxa de aceitação | 74% (17 aceitos / 23 propostos, depth 2) |
| VRAM (com MTP) | 19.861 MiB (+576 MiB sobre baseline) |
| Depth ótimo | **2** (depth 3: 21.08 tok/s; depth 5: 15.97 tok/s — pior) |
| Cache de contexto | Funcional (LCP similarity match) |

Recomendação: **PrismML sem MTP** é o runtime preferencial do Ornith (40 tok/s > 24.7 tok/s com MTP no oficial). O build oficial+MTP é experimental, mantido em diretório separado, sem serviço ou integração automática.

---

## 4. GESTOR DE MODELOS

### 4.1. CLI `ia` (gestor local)

**Script:** `~/.local/bin/ia`
**Cadastro:** `~/.config/ia/modelos.conf` (JSON)

| Comando | Exemplo | O que faz |
|---|---|---|
| `ia status` | `ia status` | Estado de todos os modelos |
| `ia status <modelo>` | `ia status bonsai` | Estado detalhado de um modelo |
| `ia on <modelo>` | `ia on laguna` | Inicia o modelo (idempotente) |
| `ia off <modelo>` | `ia off ornith` | Para o modelo |
| `ia off` | `ia off` | **Para todos** (confirma antes) |
| `ia restart <modelo>` | `ia restart bonsai` | Reinicia (exige alvo) |
| `ia health <modelo>` | `ia health bonsai` | Health check do endpoint |
| `ia solo <modelo>` | `ia solo ornith` | Troca exclusiva GPU (para os outros, inicia alvo) |
| `ia doctor` | `ia doctor` | Diagnóstico leitura (sem alterações) |
| `ia list` | `ia list` | Lista modelos cadastrados |
| `ia help` | `ia help` | Ajuda |

Alias disponíveis: `bonsai`, `bonsai-cpu`, `laguna`, `laguna-gpu`, `ornith`

Estados reportados: `configurado` (cadastrado), `em_execucao` (processo vivo), `funcional` (health 200).

### 4.2. CLI `pcsala models` (gestor via projeto)

| Comando | Exemplo | O que faz |
|---|---|---|
| `./pcsala models list` | — | Lista modelos |
| `./pcsala models status <id>` | `... status bonsai-27b-gpu` | Estado JSON |
| `./pcsala models health <id>` | `... health bonsai-27b-gpu` | Health HTTP |
| `./pcsala models start <id>` | `... start bonsai-27b-gpu` | Inicia via systemctl |
| `./pcsala models stop <id>` | `... stop bonsai-27b-gpu` | Para (CPU compartilhado rejeita) |
| `./pcsala models switch <id>` | `... switch ornith-35b-gpu` | Troca GPU (para atual, inicia alvo) |
| `./pcsala models operation <id>` | `... operation <uuid>` | Consulta operação persistida |

model_id disponíveis:
- `bonsai-27b-gpu` — Bonsai 27B + MTP (primário GPU)
- `bonsai-9b-cpu` — Bonsai 9B CPU (auxiliar)
- `laguna-xs-2.1-cpu` — Laguna CPU (permanente)
- `laguna-xs-2.1-gpu` — Laguna GPU **(novo)**
- `ornith-35b-gpu` — Ornith GPU **(reativado)**

**Regras do gestor:**
- GPU é exclusiva (só um modelo GPU por vez, grupo `gpu-slot-1`)
- CPU é compartilhado (vários consumidores simultâneos)
- CPU compartilhado **não pode ser parado** individualmente (`ia off <cpu_modelo>` rejeita)
- `ia solo` para GPU: para o GPU atual, inicia o alvo, com confirmação
- Nomes inválidos: erro claro, sem alterações

---

## 5. WORKER E FILA

### 5.1. Worker

**Serviço:** `pcsala-worker.service` (enabled, active)
**Comando:** `python -m pcsala_agent.graph_runner --root /var/lib/pcsala-worker --profile gpu-triage-v1 --queue-mode`
**Banco:** `/var/lib/pcsala-worker/state.sqlite`

### 5.2. Fila de tarefas

| Comando | Descrição |
|---|---|
| `./pcsala enqueue --prompt "texto"` | Enfileirar tarefa textual |
| `./pcsala enqueue --prompt "texto" --idempotency-key "chave"` | Com idempotência |
| `./pcsala enqueue --prompt "texto" --profile cpu-triage-v1` | Perfil alternativo |
| `./pcsala document --path /tmp/doc.txt` | Enfileirar análise documental |
| `./pcsala list` | Listar tarefas |
| `./pcsala status <id>` | Consultar tarefa |
| `./pcsala cancel <id>` | Cancelar (só QUEUED) |
| `./pcsala reconcile` | Reconciliar RESERVED sem re-inferir |

### 5.3. Perfis de inferência

| Perfil | Modelo | Endpoint | Timeout |
|---|---|---|---|
| `gpu-triage-v1` | Bonsai 27B GPU | `:8080` | 300s |
| `cpu-triage-v1` | Bonsai 9B CPU | `:8090` | 300s |
| `laguna-programming-v1` | Laguna XS 2.1 (CPU/GPU) | `:8091` ou `:8082` | 600s |

### 5.4. Orçamento de contexto

| Modelo | Contexto total | Budget input | Reserva | Margem |
|---|---|---|---|---|
| GPU 27B | 55.000 tok | 47.452 tok | 2.048 tok | 10% |
| CPU 9B | 32.768 tok | 27.443 tok | 2.048 tok | 10% |
| Laguna GPU | 131.072 tok | ~113.152 tok | 2.048 tok | 10% |
| Laguna CPU | 16.384 tok | ~12.698 tok | 2.048 tok | 10% |

Se o prompt excede o budget, o worker comprime via CPU 9B antes de enviar ao GPU.

### 5.5. Tarefas no sistema

```
id=13 COMPLETED  gpu-triage-v1  (analise longa — 145s)
id=12 COMPLETED  gpu-triage-v1  (resumo — 30s)
id=11 FAILED     gpu-triage-v1  (contexto longo — HTTP 400)
id=10 COMPLETED  gpu-triage-v1  (verbos — 50s)
id=9  FAILED     gpu-triage-v1  (timeout — documento longo)
id=8  COMPLETED  gpu-triage-v1  (GESTOR)
id=7  COMPLETED  gpu-triage-v1  (PÓS-REBOOT)
id=6  RESERVED   gpu-triage-v1  (preservada — NÃO CANCELAR)
id=5  COMPLETED  gpu-triage-v1  (OK)
id=4  COMPLETED  gpu-triage-v1  (Beta)
id=3  COMPLETED  gpu-triage-v1  (Alpha)
id=2  CANCELLED  gpu-triage-v1
id=1  COMPLETED  gpu-triage-v1  (Resultado A)
```

---

## 6. APIS DE INFERÊNCIA

### 6.1. Endpoints

| Porta | Modelo | Host | Auth | Firewall |
|---|---|---|---|---|
| **8080** | Bonsai 27B + MTP | `0.0.0.0` | API sem chave | LAN + loopback |
| **8082** | Laguna XS 2.1 GPU | `0.0.0.0` | API sem chave | LAN + loopback |
| **8090** | Bonsai 9B CPU | `0.0.0.0` | API sem chave | LAN + loopback |
| **8091** | Laguna XS 2.1 CPU | `0.0.0.0` | API sem chave | LAN + loopback |
| **8092** | Ornith 35B GPU | `0.0.0.0` | API sem chave | LAN + loopback |

**Política (2026-10-23): API obrigatória, API key não.** Os serviços correm sem
`--api-key-file`; um header `Authorization` é aceite mas ignorado. A proteção é a rede
(§7). Backup da versão com chave: `mtp.conf.bak-20261023-165825-with-apikey`;
do 9B: `no-apikey.conf` em `bonsai2-cpu.service.d/`.

**OpenAI/DeepSeek-compatível** — `/v1/chat/completions` aceita `model`, `messages`,
`max_tokens`, `reasoning_effort`. O `model` pode ser o caminho do GGUF tal como consta
no config dsh. Config para o PC remoto gerada em
`/home/igor/.config/pcsala-bonsai/dsh-llm-pi-ai.yaml`
(nota: o `laguna-local` apontava para a 8084 inexistente — corrigido para 8082).

### 6.2. Chamadas HTTP

**Health check:**
```bash
curl -s http://192.168.1.150:8080/health
# → 200
```

**Geração de texto:**
```bash
curl -s -X POST http://192.168.1.150:8080/completion \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Explique IA","n_predict":50,"temperature":0.7}'
```

**Tokenizar:**
```bash
curl -s -X POST http://192.168.1.150:8080/tokenize \
  -H "Content-Type: application/json" \
  -d '{"content":"Texto exemplo"}'
```

### 6.3. Resposta da geração

```json
{
  "content": "texto gerado...",
  "tokens_predicted": 30,
  "tokens_evaluated": 2,
  "timings": {
    "prompt_per_second": 145.6,
    "predicted_per_second": 34.4,
    "draft_n": 135,
    "draft_n_accepted": 104
  },
  "generation_settings": {
    "speculative.types": "none,draft-mtp"
  }
}
```

---

## 7. FIREWALL E REDE

### 7.1. Regras UFW

```
Status: active, policy DROP incoming
Allow:
  22/tcp                ANY (SSH)
  8080,8082,8090/tcp    192.168.0.0/16 (APIs)
  8091,8092/tcp         192.168.0.0/16 (APIs)
```

### 7.2. Regras nftables

Tabela `pcsala_api` em `inet filter` (prioridade filter -5):
- Portas `{8080,8082,8090,8091,8092}` em loopback (`lo`): ACCEPT
- Mesmas portas via `enp6s0` origem `192.168.0.0/16`: ACCEPT
- Qualquer outra origem nas mesmas portas: DROP

### 7.3. Regra geral

`iptables INPUT policy DROP` — apenas conexões explícitas passam.

---

## 8. SERVIÇOS SYSTEMD

| Serviço | Enabled | Active | Porta | Descrição |
|---|---|---|---|---|
| `bonsai2-27b.service` | enabled | active | 8080 | Bonsai 27B GPU + MTP |
| `bonsai2-cpu.service` | enabled | active | 8090 | Bonsai 9B CPU |
| `laguna.service` | disabled | inactive | 8091 | Laguna XS 2.1 CPU (desativado — RAM) |
| `pcsala-worker.service` | enabled | active | — | Worker LangGraph |
| `pcsala-bonsai-firewall.service` | disabled | active | — | Regras nft API |
| `laguna-gpu.service` | disabled | inactive | 8082 | Laguna XS 2.1 GPU **(novo)** |
| `ornith.service` | disabled | inactive | 8092 | Ornith 35B GPU **(reativado)** |

Logs:
```bash
journalctl -u bonsai2-27b.service -n 30 --no-pager
journalctl -u pcsala-worker.service -n 30 --no-pager
```

---

## 9. DIRETÓRIOS IMPORTANTES

| Caminho | Conteúdo |
|---|---|
| `/home/igor/pc-sala-agent/` | Código fonte, CLI, docs |
| `/home/igor/pc-sala-agent/src/` | Módulos Python |
| `/home/igor/pc-sala-agent/guias/` | Documentação |
| `/home/igor/pc-sala-agent/configs/` | Templates de serviço (incl. `laguna-gpu.service`) |
| `/var/lib/pcsala-worker/` | Banco SQLite + artefatos |
| `/home/igor/opt/prism-pascal-build/` | Build GPU Pascal (MTP + Laguna) |
| `/home/igor/opt/prism-gpu-build/` | Build GPU original (Ornith) |
| `/home/igor/opt/prism-cpu-install-aswyUW/` | Build CPU |
| `/home/igor/opt/llama-cuda-official/` | Build llama.cpp oficial (CUDA, experimental — MTP Ornith) |
| `/home/igor/models/bonsai-2-27b/` | Pesos 27B + drafter MTP |
| `/home/igor/models/ternary-bonsai-2-9b-cpu/` | Pesos 9B |
| `/home/igor/models/laguna-xs-2-1/` | Pesos Laguna APEX I-Compact (15 GB) |
| `/home/igor/models/ornith/` | Pesos Ornith Q4_K_M (21 GB) + backup serviço |
| `/home/igor/.config/pcsala-bonsai/` | Chave API (fallback), models.json |
| `/home/igor/.config/ia/` | Cadastro do gestor `ia` (modelos.conf) |
| `/mnt/arquivos/` | HDD 465 GB (mount automático) |
| `/etc/systemd/system/` | Serviços systemd |
| `/etc/systemd/system/bonsai2-27b.service.d/mtp.conf` | Drop-in MTP |

---

## 10. FERRAMENTAS DE EXECUÇÃO ISOLADA

**Executor:** `pcsala-executor` (UID 999, grupo 983)
**Sandbox:** Bubblewrap (`bwrap`), `--unshare-net --unshare-pid --clearenv`
**Orquestrador:** `systemd-run` com `User=pcsala-executor`, `MemoryMax=256M`
**Workspace:** `/var/lib/pcsala-executor/jobs/{project}/{session}/{task}/{attempt}/`

Uso:
```bash
./pcsala exec-demo   # demonstração sintética
```

---

## 11. SEGURANÇA

- APIs sem autenticação na LAN (autorizado por Igor)
- Firewall UFW + nftables: apenas SSH + APIs da LAN (portas 8080,8082,8090,8091,8092)
- `INPUT policy DROP` — sem acesso externo
- Worker roda como `igor` (sem sudo)
- Executor roda como UID 999 (sem sudo, sem rede)
- Chave API em `/home/igor/.config/pcsala-bonsai/api.key` preservada como fallback
- Serviços systemd com `NoNewPrivileges=yes`, `PrivateTmp=yes`, `ProtectSystem=full`

---

## 12. BUILD PASCAL (MTP + LAGUNA)

**Base:** PrismML `5d80cff0b8cb9f2bf823cfc4e71e3abb97f290d6`
**Patch:** `killy-netsphere/bonsai2-1080ti` commit `712c505` — `bonsai2-pascal.patch`
**Diretório:** `/home/igor/opt/prism-pascal-build/`
**Binário (stub):** `build/bin/llama-server` (build 10687, commit `5d80cff0b`)
**Biblioteca:** `build/bin/libllama-server-impl.so` — contém suporte a Laguna (`LLM_ARCH_LAGUNA`)
**Flags CMake:** `-DCUDA_ARCHITECTURES=61 -DFORCE_MMQ=ON -DGGML_CUDA_GRAPHS=ON -DGGML_CUDA_FA=ON`
**Compilador:** gcc 15.2.0, CUDA 12.4.131

---

## 13. TABELA COMPARATIVA — BENCHMARKS REAIS

| Configuração | Prompt eval | Geração | VRAM | Contexto | Qualidade código |
|---|---|---|---|---|---|
| **Bonsai 27B GPU + MTP** | **126-243 tok/s** | **48,4 (ctx 27) → 27,8-37,5 (ctx 10-16K)** | 12,4 GB | 55K | ✅✅ |
| **Bonsai 27B GPU sem MTP** | ~243 tok/s | 25,4 tok/s | 12,4 GB | 55K | ✅✅ |
| **Bonsai 9B CPU** | ~18-20 tok/s | 6,08 tok/s | 0 (RAM ~3 GB) | 32K | ✅✅ |
| **Laguna CPU** | ~1.4 tok/s | ~2.6 tok/s | 0 (RAM 18 GB) | 16K | ✅✅✅ |
| **Laguna GPU (full offload)** | **~55-70 tok/s** | **~40-47 tok/s** | 15,9-21,2 GB | **150K** | ✅✅✅ |
| **Ornith GPU (PrismML, preferencial)** | ~54 tok/s | ~40 tok/s | ~19,4 GB | 16K+ | ✅✅ |
| **Ornith GPU (llama.cpp oficial + MTP depth 2)** | ~24.5 tok/s | **~24.7 tok/s** | 19,9 GB | 4K+ | ✅✅ |

**A geração do Bonsai 27B depende do contexto** (27 tokens → 48,4; 10K → 35,1;
10-16K → mediana 32,85). Os 40-50 tok/s só se atingem com contexto pequeno —
a atenção sobre o KV longo custa por token. O TTFT é `tokens_novos / 126-186 tok/s`.

Laguna GPU é ~18x mais rápido que Laguna CPU.

---

## 14. COMANDOS RÁPIDOS

```bash
# Estado do sistema
ia status                    # Todos os modelos
ia doctor                    # Diagnóstico completo
./pcsala health               # Saúde resumida

# Gestão de modelos (ia)
ia on laguna                 # Iniciar Laguna CPU
ia on laguna-gpu             # Iniciar Laguna GPU (bloqueia se Bonsai ativo)
ia off ornith                # Parar Ornith
ia solo ornith               # Trocar GPU para Ornith (confirma antes)
ia solo laguna-gpu           # Trocar GPU para Laguna
ia restart bonsai            # Reiniciar Bonsai GPU

# Gestão de modelos (pcsala)
./pcsala models switch laguna-xs-2.1-gpu   # Trocar GPU para Laguna
./pcsala models switch ornith-35b-gpu      # Trocar GPU para Ornith
./pcsala models switch bonsai-27b-gpu      # Voltar para Bonsai
./pcsala models list                       # Listar todos

# Inferência direta
curl -X POST http://192.168.1.150:8080/completion \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Ola","n_predict":20}'

# Laguna GPU direto (se ativo)
curl -X POST http://192.168.1.150:8082/completion \
  -H "Content-Type: application/json" \
  -d '{"prompt":"def hello","n_predict":50}'

# Ornith GPU direto (se ativo)
curl -X POST http://192.168.1.150:8092/completion \
  -H "Content-Type: application/json" \
  -d '{"prompt":"def hello","n_predict":50}'

# Fila de tarefas
./pcsala enqueue --prompt "Minha pergunta"
./pcsala list
./pcsala status 13

# GPU
nvidia-smi
```

---

## 15. REVERSÃO

**Reversão do MTP (remove também o warm-up e as flags novas):**
```bash
sudo cp /etc/systemd/system/bonsai2-27b.service.d/mtp.conf{,.bak-manual-$(date +%s)}
sudo rm /etc/systemd/system/bonsai2-27b.service.d/mtp.conf
sudo systemctl daemon-reload
sudo systemctl restart bonsai2-27b.service
# warm-up fica órfão mas inofensivo — remover se já não se quiser:
sudo rm /home/igor/pc-sala-agent/scripts/bonsai-warmup.sh
```

**Reverter só a API key (sem mexer no restante):**
```bash
sudo cp /etc/systemd/system/bonsai2-27b.service.d/mtp.conf.bak-20261023-165825-with-apikey \
        /etc/systemd/system/bonsai2-27b.service.d/mtp.conf
sudo rm -f /etc/systemd/system/bonsai2-cpu.service.d/no-apikey.conf
sudo systemctl daemon-reload && sudo systemctl restart bonsai2-27b.service bonsai2-cpu.service
```

**Reversão do Laguna GPU:**
```bash
sudo systemctl disable --now laguna-gpu.service
sudo rm /etc/systemd/system/laguna-gpu.service
sudo systemctl daemon-reload
```

**Reversão do Ornith (para estado anterior):**
```bash
sudo systemctl disable --now ornith.service
# Restaurar service original de backup
cp /home/igor/models/ornith/backup-bonsai2-27b.service.bak /etc/systemd/system/ornith.service
sudo systemctl daemon-reload
```

**Reversão de auth/firewall:**
```bash
# Remover porta 8092 das regras
sudo ufw delete allow from 192.168.0.0/16 to any port 8092
```

**Reversão do `ia`:**
```bash
rm ~/.local/bin/ia
```

---

## 16. PENDÊNCIAS

1. **Budget de contexto** — recalcular budget do perfil `laguna-programming-v1` para GPU (128K)
2. **Ornith MTP** — funcional no llama.cpp oficial (depth 2, 74% aceitação, 24.7 tok/s). PrismML continua runtime preferencial (40 tok/s). Build experimental mantido em `/home/igor/opt/llama-cuda-official/`, sem serviço ou integração automática
3. **Budget de contexto** — preenchido para Laguna GPU (~113.152 tok) e Laguna CPU (~12.698 tok)
4. **Firewall** — `pcsala-bonsai-firewall.service` habilitado para persistir no reboot
5. **Executor real** — primeiro projeto real aguardando autorização
6. **Dependências documentais** — pdfminer, python-docx
7. **Laguna CPU desativado** — liberou ~18 GB RAM, reativar com `sudo systemctl enable --now laguna.service`
8. **Ornith MTP integrado** — build experimental em `/home/igor/opt/llama-cuda-official/`
9. **SHA-256 histórico do modelo principal** — `3907dc16...62ec1` não tem valor de referência (PC antigo formatado); confirmar quando houver o registo original
10. **dsh no PC remoto** — config gerada em `~/.config/pcsala-bonsai/dsh-llm-pi-ai.yaml` mas **não aplicada**: SSH a 192.168.1.101 recusa porta 22. `laguna-local` corrigido de 8084 (inexistente) para 8082; `laguna-gpu.service` continua `inactive`
11. **MTP no Bonsai 9B** — bloqueado (sem cabeça 9B publicada e build CPU sem caminho NEXTN/Hadamard). Alternativa `ngram-map-k` testada sem ganho
12. **TTFT do harness** — média de 50 s causada por 4 pedidos de 5,6K-16,9K tokens e por respostas de 941-2.221 tokens re-prefilladas no turno seguinte. Correcção é do lado do dsh (prefixo estável + `max_tokens` menor), não do servidor

---

## 17. REGRA DE CONTINUIDADE

Executar somente o escopo autorizado. Verificar o que foi feito. Preservar evidências. Distinguir implementado, configurado, demonstrado e não verificado. Não transformar um ensaio bem-sucedido em promessa geral de segurança.

---

## 18. DOCUMENTOS RELACIONADOS

- `guias/MANUAL_GESTOR_API.md` — Manual do gestor e APIs
- `guias/DIAGNOSTICO_LAGUNA_ORINTH.md` — Diagnóstico técnico detalhado
- `CONTINUITY.md` — Procedimento de retomada
- `PROJECT_STATE.md` — Estado consolidado
- `guias/ANALISE_PROMPT_v8.2.md` — Análise de pertinência e consolidação