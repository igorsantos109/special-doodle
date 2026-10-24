# CONTINUITY.md — Procedimento de retomada (ATUALIZADO 2026-10-23)

**Data:** 2026-10-23T23:58 UTC
**Raiz:** `/home/igor/pc-sala-agent`
**Ambiente:** `.venv` (Python 3.14.4)
**Comando de testes:** `PYTHONPATH="$PWD/src" .venv/bin/python -m pytest tests/ -v --tb=short`

## Última acção (2026-10-23T23:58Z) — Correcção "Output token limit reached" no Bonsai 27B

**Diagnóstico (evidência do journal `bonsai2-27b.service`):** o dsh no PC remoto enviou
prompts de **55.039 / 56.005 / 56.011 / 56.395 tokens sem compactar**, contra `-c 55000`:
- `send_error: request (56395 tokens) exceeds the available context size (55040)` → falha HTTP;
- `stop processing: n_tokens = 55039, truncated = 1` → `finish_reason=length` → a mensagem
  **"Output token limit reached"** exibida pelo dsh.
- Prefills de 18,5K-32,5K tok a ~165 tok/s = TTFT de 2-5 min (pendência 16.12).

**Alterações aplicadas (lado pc-sala):**
1. Drop-in `bonsai2-27b.service.d/mtp.conf`: **`-c 55000` → `-c 64000`**. Verificado:
   `n_ctx=64000`, `kv_unified='false'`, warmup 41-45 tok/s, VRAM 12,9/23,0 GB;
   pedido real de **54.470 tokens → HTTP 200** (prefill 347,6 s). Backup do drop-in:
   `mtp.conf.bak-20261023-*-pre-ctxshift`.
2. Testado e **revertido** `--context-shift` + `-kvu`: o build desactiva KV shifting para
   este modelo (`KV cache shifting is not supported for this context` — rope MROPE,
   `n_pos_per_embd()>1`), logo são flags inertes. Flags mortas removidas do drop-in.
3. `context_budget.PRIMARY_CONTEXT = 64000` (testes `test_context_budget` ajustados).
4. `guias/GUIA_MESTRE.md` §6.1/§11: linhas de Contexto/VRAM actualizadas.
5. `~/.config/pcsala-bonsai/dsh-llm-pi-ai.yaml` regenerado para merge manual:
   `contextWindow: 58000`, `maxTokens: 4096` (margem 62.096 < 64.000). **SSH
   192.168.1.101:22 continua fechado — o dsh no PC remoto tem de ser actualizado à mão.**

**Limite restante:** o servidor NÃO trunca prompt maior que o ctx (só erro), e context
shift é impossível neste modelo — **a compactação/limpeza de contexto é obrigatoriamente
do lado do dsh**. Com `-c 64000` o dsh tem margem até ~59,9K tok de prompt+saída; sem
compactação, os prompts (crescimento de 3-7K tok/turno) voltam a estourar em 1-2 turnos.

## Acção anterior (2026-10-23T18:10Z) — Medição e afinação do Bonsai 27B MTP

**Conjunto histórico reconstruído e verificado** (commit, patch, opções CMake, SHA da
cabeça MTP, linha de comando). **API key removida dos serviços** (política: API sim,
chave não). **Warm-up automático no arranque.** **Configuração dsh gerada para o PC remoto.**

### Laguna GPU — FUNCIONAL (via Pascal build)

**Laguna XS 2.1 APEX I-Compact e Ornith 35B validados na P40.**

### Laguna GPU — FUNCIONAL (via Pascal build)
- `-ngl 40` (full offload), 40 camadas, 256 expertos, 8 usados/token
- Prompt eval: ~55-70 tok/s, Geração: ~40-47 tok/s (vs CPU: 1.4/2.6 tok/s)
- VRAM: 15,9 GB (4K ctx) → 21,2 GB (150K ctx) — cabe na P40 (23 GB)
- Contexto 128K validado, 150K cabe, 200K OOM
- Código gerado corretamente (fibonacci, hello world)
- **Não precisa de build separado**: o mesmo Pascal build (`5d80cff0b`) já contém `LLM_ARCH_LAGUNA`
- Service: `laguna-gpu.service` (porta 8082, disabled, GPU exclusiva)

### Ornith GPU — MTP validado (experimental)

**Runtime preferencial:** PrismML GPU build (40 tok/s sem MTP, service `ornith.service`).
**MTP experimental:** llama.cpp oficial (commit `73bfe6c`) com `--spec-type draft-mtp` depth 2.

Resultados MTP no Ornith (build `/home/igor/opt/llama-cuda-official/`):
- MTP activo: `speculative.types = none,draft-mtp` confirmado
- Draft: 17 aceitos / 23 gerados, aceitação 74%, mean len 2.58
- Geração: 24.7 tok/s com MTP vs 18.7 tok/s sem MTP (ganho 1.32x)
- VRAM: 19.861 MiB (cabe na P40)
- Depth 2 é ótimo; depth 3 (21 tok/s) e depth 5 (16 tok/s) degradam
- MTP chained: não suportado (single head qwen35 + flash attn)
- Cache de contexto funcional entre chamadas (LCP similarity match)

O GGUF `ornith-1.0-35b-MTP-graft-Q4_K_M.gguf` já contém a cabeça MTP integrada (`nextn_predict_layers: 1`, 753 tensores). Nenhum download ou enxerto foi necessário.

**Sem alteração no serviço ornith.service, no cadastro, na inicialização ou na GPU.** Build experimental separado em `/home/igor/opt/llama-cuda-official/`. Bonsai restaurado como primário.

### GPU exclusiva — 3 modelos competem
| Serviço | Porta | Status | Como ativar |
|---|---|---|---|
| `bonsai2-27b.service` | 8080 | active (primário) | `./pcsala models switch bonsai-27b-gpu` |
| `laguna-gpu.service` | 8082 | disabled | `./pcsala models switch laguna-xs-2.1-gpu` |
| `ornith.service` | 8092 | disabled | `./pcsala models switch ornith-35b-gpu` |

### 5 modelos registrados no gestor
| model_id | Classe | Perfil | Porta | Unidade | Estado |
|---|---|---|---|---|---|
| bonsai-27b-gpu | GPU | gpu-triage-v1 | 8080 | bonsai2-27b.service | active |
| laguna-xs-2.1-gpu | GPU | laguna-programming-v1 | 8082 | laguna-gpu.service | disabled |
| ornith-35b-gpu | GPU | gpu-triage-v1 | 8092 | ornith.service | disabled |
| bonsai-9b-cpu | CPU | cpu-triage-v1 | 8090 | bonsai2-cpu.service | active (32 threads) |
| laguna-xs-2.1-cpu | CPU | laguna-programming-v1 | 8091 | laguna.service | **disabled (RAM ~18 GB)** |

### Tabela comparativa — benchmarks
| Configuração | Prompt eval | Geração | VRAM | Contexto máximo | Qualidade código |
|---|---|---|---|---|---|
| **Bonsai 27B GPU + MTP** | **126-243 tok/s** | **28-48 tok/s** (ctx-dependente) | 12,4 GB | 55K | ✅✅ |
| **Laguna CPU** | ~1.4 tok/s | ~2.6 tok/s | 0 GB (RAM 18 GB) | 16K | ✅✅✅ |
| **Laguna GPU** | **~55-70 tok/s** | **~40-47 tok/s** | 15,9-21,2 GB | **150K** | ✅✅✅ |
| **Ornith GPU (PrismML, preferencial)** | ~54 tok/s | ~40 tok/s | ~19,4 GB | 4K+ | ✅✅ |
| **Ornith GPU (llama.cpp oficial + MTP)** | ~24.5 tok/s | **24.7 tok/s** | 19,9 GB | 4K+ | ✅✅ |

## Medição de 2026-10-23 — Bonsai 27B MTP

### Conjunto histórico verificado (todos os itens confirmados)

| Item | Valor |
|---|---|
| Base PrismML | `5d80cff0b8cb9f2bf823cfc4e71e3abb97f290d6` |
| Patch | `killy-netsphere/bonsai2-1080ti` commit `712c505`, ficheiro `bonsai2-pascal.patch` SHA-256 `f8aeebbc...50b9` (idêntico ao aplicado; `git apply -R --check` = 0; 29 ficheiros + `mmvq-rowlane.cu`, 2756 inserções) |
| Opções CMake | `arch=61`, `GGML_CUDA_FORCE_MMQ=ON`, `GGML_CUDA_GRAPHS=ON`, `GGML_CUDA_FA=ON`, `GGML_NATIVE=OFF`, `LLAMA_CURL=OFF` |
| build_info | `b10687-5d80cff0b` |
| Modelo principal | `3907dc16...62ec1`, 7.206.168.928 bytes |
| Cabeça MTP | `9d11de22...287e7`, 1.055.253.344 bytes (bate com o valor documentado) |
| Desempenho | 48,30 tok/s vs histórico 50,81 (95,1%) |
| Sem MTP | 25,4 tok/s vs histórico 25,71 |

**Pendente:** SHA-256 histórico do modelo principal (sem valor de referência do PC antigo).

### Configuração final (`mtp.conf`)

```
llama-server -m Ternary-Bonsai-2-27B-PQ2_0.gguf
  -md mtp-bonsai2-native-v5b-dv64k.gguf --spec-type draft-mtp
  --spec-draft-n-max 2 --spec-draft-p-min 0.4 --backend-sampling
  --host 0.0.0.0 --port 8080 -c 55000 -t 8 -ngl 99 -ngld 99 -n 2048
  --parallel 1 --threads-http 4 --flash-attn on
ExecStartPost=-/home/igor/pc-sala-agent/scripts/bonsai-warmup.sh
TimeoutStartSec=300
Environment: LD_LIBRARY_PATH=..., GGML_CUDA_ROWLANE=1, GGML_CUDA_RL_N4_LONG=1
```

Sem `--api-key-file`. Sem `--no-kv-offload` (KV em GPU).

### Geração por contexto (384 tokens, GPU ociosa)

| Contexto | Geração |
|---|---|
| 27 tokens | **48,01 / 48,43 tok/s** |
| 564 tokens | 40,17 tok/s |
| ~10.592 tokens | 35,10 tok/s |
| 10-16K (uso real) | 27,78-37,45 (mediana 32,85, n=16) |

**Matriz A/B (384 tokens, GPU ociosa):** sem MTP 25,4 | config actual **44,0** | n-max 5 + p-min 0,1 38,2 | idem sem flash-attn 36,2.
A configuração actual é a melhor — as alternativas pioram.

**Acceptance MTP:** 0,60-0,87, mean len 2,12-2,65.

### Prefill / TTFT

- Contexto vazio (9.228 tok): **236-243 tok/s**
- Produção com contexto grande: **126-186 tok/s** (teto da P40, 12 TFLOP/s FP32, sem tensor cores)
- Outliers medidos no harness: 91,2 s (16.865 tok), **87,5 s (16.280 tok com f_keep=0,240)**, 54,1 s (8.211 tok)
- Turnos normais: 7,5-16,6 s de TTFT

**TTFT médio de 50 s no harness = 4 pedidos gigantes a arrastar a média.** Causa:
prefixo instável (reuso de cache caiu para 24%) e respostas longas (941-2.221 tokens)
re-prefilladas no turno seguinte a ~135 tok/s.

### `--cache-reuse` — IMPOSSÍVEL para este modelo

Flag testada e rejeitada pelo runtime:
`cache_reuse is not supported by this context, it will be disabled`.

Cadeia no código: `server-context.cpp:1156` → `llama_memory_can_shift()` →
`llama-kv-cache.cpp:1176` devolve `false` quando `hparams.n_pos_per_embd() > 1`,
e `llama-hparams.cpp:239` dá 4 quando `rope_type` é MROPE/IMROPE.
O GGUF declara `qwen35.rope.dimension_sections` (MROPE). É propriedade do modelo —
nenhuma flag o altera sem corromper a inferência. `ctx_shift` é desactivado pela mesma razão.

### Primeiro pedido após ocioso — 13-14 tok/s (decidido manter)

| Estado | Clock | Potência |
|---|---|---|
| Ocioso | 1303 MHz | 51,95 W |
| Em pedido | 1531 MHz | 65,6 W |
| 5s depois de parar | 1303 MHz | 51,95 W |

Conexão persistente: run1 após pausa 1,116 s = **14,33 tok/s**; runs2-6 contíguos 0,66 s = **24,2 tok/s**.
**Decisão de Igor: manter como está.** Travar clocks (`nvidia-smi -ac 3615,1531`) custaria
+8 a +23 W contínuos ≈ **+6 a +17 kWh/mês** para eliminar 0,45 s só no primeiro pedido.

### MTP no Bonsai 9B CPU — IMPOSSÍVEL

1. Não existe cabeça MTP para 9B (HuggingFace: só `killy369/Ternary-Bonsai-2-27B-MTP-drafter-GGUF`)
2. O drafter do 27B tem 8 ocorrências de `nextn` e 18 de `blk.64.`; o 9B tem **0** de ambas
3. Build CPU `73bfe6c` falha: `prism.hadamard: weight 'blk.64.nextn.shared_head_head.weight' is not on a verified Hadamard-aware matmul path`
   (caminho NEXTN/Hadamard só existe no build Pascal `5d80cff0b`)

Medido no CPU: baseline **6,08 tok/s** | `--spec-type ngram-map-k` 6,06 tok/s (sem ganho).

### Warm-up no arranque

`scripts/bonsai-warmup.sh` ligado por `ExecStartPost`: espera `/health` até 150 s, gera
400 tokens (~10-12 s) para montar CUDA graphs e rampar clocks. O serviço só passa a
`active` depois de servir. Registo no journal como `[warmup]`.

### dsh no PC remoto

Config gerada em `/home/igor/.config/pcsala-bonsai/dsh-llm-pi-ai.yaml` (YAML validado).
**Correcção:** `laguna-local` apontava para a porta **8084, que nunca existiu** — corrigida
para **8082** (`laguna-gpu.service`, ainda `inactive`).
SSH ao PC remoto (192.168.1.101) recusa porta 22 — não é possível aplicar remotamente.
Endpoints verificados sem chave: 8080 → 200, 8090 → 200, `/v1/chat/completions` com os
`id` exactos do config → 200, `reasoning_effort: medium` aceite.

## Comandos de uso

```bash
# Estado do sistema
ia status
./pcsala health

# Gestao de modelos
./pcsala models list
./pcsala models switch laguna-xs-2.1-gpu   # Trocar GPU para Laguna
./pcsala models switch ornith-35b-gpu      # Trocar GPU para Ornith
./pcsala models switch bonsai-27b-gpu      # Voltar para Bonsai

# Testes
PYTHONPATH="$PWD/src" .venv/bin/python -m pytest tests/ -v --tb=short

# Monitorização
sudo journalctl -u bonsai2-27b.service --no-pager -n 10
sudo journalctl -u pcsala-worker.service --no-pager -n 10

# Backup
./pcsala backup
```

## Pendências
1. Worker parado — reiniciar: `sudo systemctl start pcsala-worker.service`
2. Budget de contexto Laguna — preenchido na documentação (~113K GPU, ~12.7K CPU)
3. Firewall — habilitado (`pcsala-bonsai-firewall.service`)
4. Laguna CPU — desativado (liberou ~18 GB RAM), reativar com `sudo systemctl enable --now laguna.service`
5. Ornith LD_LIBRARY_PATH — corrigido (build/bin)
6. Teste de contexto longo real no Laguna GPU
7. `reserve_engine()` — integrar no worker

## Reversão — entrega Laguna GPU

```bash
# Remover service
sudo systemctl disable --now laguna-gpu.service
sudo rm /etc/systemd/system/laguna-gpu.service
sudo systemctl daemon-reload

# Remover registo do gestor (se necessário)
# git checkout -- src/pcsala_agent/model_manager.py

# Remover configuração firewall porta 8092
sudo ufw delete allow from 192.168.0.0/16 to any port 8092

# Reverter Ornith ao estado anterior
sudo systemctl disable --now ornith.service
sudo systemctl daemon-reload

# Preservar GGUF (nunca apagar)
# /home/igor/models/laguna-xs-2-1/Laguna-XS-2.1-APEX-I-Compact.gguf (15 GB)
# /home/igor/models/ornith/ornith-1.0-35b-MTP-graft-Q4_K_M.gguf (21 GB)
```

## Reversão do MTP Bonsai
```bash
sudo rm /etc/systemd/system/bonsai2-27b.service.d/mtp.conf
sudo systemctl daemon-reload
sudo systemctl restart bonsai2-27b.service
```