# Diagnóstico Técnico — Laguna XS 2.1 na P40 + Ornith-1.0-35B MTP-graft

**Data:** 2026-10-22T20:23 UTC (diagnóstico) / 22:00 UTC (pós-implantação)
**Sistema:** PC-SALA (Tesla P40 23GB, Xeon E5-2697 v4 36T, 30GB RAM)  
**Build root:** `/home/igor/pc-sala-agent`

---

## Resultado Pós-Implementação

**Laguna XS 2.1 e Ornith 35B foram validados na P40 com sucesso, contrariando a estimativa inicial de que não caberiam integralmente.**

### Laguna XS 2.1 APEX I-Compact (15 GB GGUF)
- Full offload (-ngl 40) na Tesla P40: ✅ confirmado
- VRAM observada: 15.881 MiB (16K ctx) a 21.223 MiB (150K ctx)
- Contexto máximo: **150K tokens** (128K com margem)
- Prompt eval: ~55-70 tok/s | Geração: **~40-47 tok/s**
- Serviço: `laguna-gpu.service` (porta 8082, disabled)

### Ornith 35B Q4_K_M (21 GB GGUF)
- Full offload (-ngl 40) na Tesla P40: ✅ confirmado
- VRAM observada: ~19.425 MiB (4K ctx) — cabe nos 23 GB
- Prompt eval: ~54 tok/s | Geração: **~40 tok/s**
- MTP validado no llama.cpp oficial (24.7 tok/s, depth 2, 74% aceitação)
- Runtime preferencial: PrismML (40 tok/s sem MTP)
- Serviço: `ornith.service` (porta 8092, disabled)

---

## 1. Ambiente real

### GPU
- **Tesla P40** — 23.040 MiB, CC 6.1 (Pascal), driver 580.178.04, CUDA 12.4.131
- **VRAM actual:** 8.489 MiB ocupados (Bonsai 27B + MTP), 14.418 MiB livres
- **GPU exclusiva** (`gpu-slot-1`), só um modelo GPU por vez

### CPU / RAM
- **Intel Xeon E5-2697 v4** — 36 threads @ 2.30 GHz, AVX2, FMA, BMI2
- **RAM:** 30 GiB total, ~16 GiB disponível
- **Swap:** 8 GiB (1,3 GiB em uso)
- **Disk:** 226 GB SSD (67G used, 148G free), 458 GB HDD `/mnt/arquivos` (435G free)

### Serviços activos
| Serviço | Porta | Modelo | Estado |
|---|---|---|---|
| `bonsai2-27b.service` | 8080 | Bonsai 27B GPU + MTP (Pascal) | active ✅ |
| `bonsai2-cpu.service` | 8090 | Bonsai 9B CPU | active ✅ |
| `laguna.service` | 8091 | Laguna XS 2.1 APEX I-Compact | **active** ✅ (CPU!) |
| `ornith.service` | 8082 | Ornith 35B MTP | disabled ❌ |
| `pcsala-worker.service` | — | Worker LangGraph | active ✅ |

### Pesos em disco
| Modelo | Caminho | Tamanho |
|---|---|---|
| Bonsai 27B | `/home/igor/models/bonsai-2-27b/Ternary-Bonsai-2-27B-PQ2_0.gguf` | 6.8 GB |
| Drafter MTP | `/home/igor/models/bonsai-2-27b/mtp-bonsai2-native-v5b-dv64k.gguf` | ~1 GB |
| Bonsai 9B | `/home/igor/models/ternary-bonsai-2-9b-cpu/` | 2.4 GB |
| **Laguna XS 2.1** | `/home/igor/models/laguna-xs-2-1/Laguna-XS-2.1-APEX-I-Compact.gguf` | **15 GB** |
| **Ornith** | `/home/igor/models/ornith/ornith-1.0-35b-MTP-graft-Q4_K_M.gguf` | **21 GB** |

### Binários disponíveis
| Build | Localização | Tipo | Tamanho | GPU Support |
|---|---|---|---|---|
| **Pascal (MTP)** | `prism-pascal-build/build/bin/llama-server` | Stub + libllama-server-impl.so | 18K + 6.9MB | CUDA 6.1 (Pascal) ✅ |
| **GPU original** | `prism-gpu-build/install/bin/llama-server` | Stub + libllama-server-impl.so (em build/bin/) | 18K + 6.9MB | CUDA (instalação quebrada) ❌ |
| **CPU** | `prism-cpu-install-aswyUW/install/bin/llama-server` | Monolítico | 18.6 MB | CPU apenas ✅ |

### Gestores
- **`./pcsala models`** — `ModelCoordinator` em Python (model_manager.py) com Pydantic, systemctl, health HTTP
- **`ia`** — script Python `~/.local/bin/ia` com cadastro em `~/.config/ia/modelos.conf`

---

## 2. Factos verificados

### 2.1 Laguna CPU — FUNCIONAL e VERIFICADO
- Laguna XS 2.1 APEX I-Compact (15 GB) está em `/home/igor/models/laguna-xs-2-1/`
- SHA-256: `b674541db815d8829e4c57bd56cffebbd49e9822e284e69f199ae7fbd0b705d2`
- Serviço `laguna.service` activo, health 200
- **Inferência real comprovada**: prompt "def hello" → 20 tokens gerados em ~7.3s (2,61 tok/s)
- Código gerado correctamente: função Python com `print("Hello World!")`
- Uso de RAM: **17.9 GB RSS** (56.5% de 30GB)
- Sem GPU envolvida (`-ngl 0`)

### 2.2 Pascal build SUPORTA Laguna
- Fonte PrismML `5d80cff0b` (build 10687) contém `LLM_ARCH_LAGUNA`
- `src/models/laguna.cpp` implementa carregamento e grafo de inferência
- **Laguna compilado na libllama-server-impl.so** — objecto `laguna.cpp.o` existe e símbolos `_ZN18llama_model_laguna...` confirmados
- Flags Pascal: `CUDA_ARCHITECTURES=61`, `GGML_CUDA_FA=ON`, `GGML_CUDA_FORCE_MMQ=ON`

### 2.3 GPU build original está quebrado
- `prism-gpu-build/install/bin/llama-server` é stub mas **não tem libllama-server-impl.so em install/lib/**
- A lib está em `build/bin/` e o RUNPATH aponta para lá — **deve funcionar** na verdade
- Porém, o serviço Ornith usa `prism-gpu-build/install/bin/llama-server` com `LD_LIBRARY_PATH=install/lib` — a resolução real usa RUNPATH que aponta para `build/bin/`

### 2.4 Strata — NÃO é reutilizável para Laguna
- É um aplicativo completo para **Qwen3.8-Flash-Next** (125B parameters)
- Usa `llama.cpp`/PrismML como base mas com customizações específicas do Qwen
- Expert cache, speculative decoding e execução híbrida estão acoplados à disposição de tensores do Qwen
- **Conceitos aplicáveis** (expert cache, adapt-async, pin-by-need) JÁ existem ou podem ser implementados no PrismML
- **Estratégia correcta**: usar o PrismML (já funcional e compilado) em vez de adaptar o Strata

### 2.5 Ornith — 21 GB Q4_K_M em disco, serviço desabilitado
- GGUF `ornith-1.0-35b-MTP-graft-Q4_K_M.gguf` (21 GB) presente
- Serviço `ornith.service` inactive/disabled, mas **unit systemd existe**
- Ornith service usa `prism-gpu-build/install/bin/llama-server` (stub) com flags MTP
- **Não verificado** se carrega correctamente — GPU ocupada pelo Bonsai

---

## 3. Orçamento de memória para Laguna na GPU

### VRAM disponível: ~14,4 GB livres (com Bonsai parado: 23 GB)

| Componente | APEX I-Compact (15 GB) | Estimativa |
|---|---|---|
| Pesos residentes (15 GB GGUF → ~15.8 GB VRAM) | 15.8 GB | 15.8 GB |
| Cache KV (16K contexto, Q8_0) | ~2.5 GB (31 layers × 4096 × 2 × 16K × 1B) | 2.5 GB |
| Buffers de execução | ~500 MB | ~500 MB |
| **Subtotal** | **~18.8 GB** | |
| Margem operacional (10%) | ~1.9 GB | |
| **Total estimado** | **~20.7 GB** | |

**Conclusão: I-Compact NÃO cabe integralmente na P40 (23 GB).**
O peso sozinho (~15.8 GB) + KV cache (~2.5 GB) já ocupam ~18.3 GB.
Com margem e buffers, o total fica entre 20-21 GB. Com Bonsai a usar 12,4 GB (medido 2026-10-23, subiu de 8,5 GB por causa do KV em GPU e do drafter), é impossível.

### Estratégias possíveis:

**A. I-Compact com offload parcial** (via `-ngl N`):
- `-ngl 20` (~70% dos layers na GPU): pesos ~11 GB + KV ~2.5 GB = ~13.5 GB → cabe com Bonsai parado
- `-ngl 99` não cabe — pesos integrais excedem 23 GB

**B. I-Compact com cache KV reduzido** (4K contexto):
- KV cache cai para ~0.6 GB → total ~16.4 GB → cabe com `-ngl 99`

**C. Execução híbrida nativa do PrismML**:
- PrismML já suporta `-ngl` para distribuir layers entre GPU e CPU
- Estratégia: GPU executa layers densos (atenção + FF dense), CPU executa specialistas MoE
- **Equivalente funcional ao Strata**, sem precisar de patches externos

---

## 4. Plano técnico

### Fase 1 — Baseline Laguna GPU (1-2h, não destrutivo)

1. Parar Bonsai GPU (via `./pcsala models switch` — mas manter worker parado)
2. Testar Laguna no Pascal binary com `-ngl 20` (offload parcial)
3. Validar: health, geração curta, comparação com CPU
4. Medir VRAM, RAM, tok/s, qualidade
5. Reverter para Bonsai GPU

### Fase 2 — Híbrido nativo (2-4h)

1. Testar `-ngl` com diferentes valores (10, 20, 30, 40, 99)
2. Testar `--no-kv-offload` vs `--kv-offload` para contexto maior
3. Encontrar ponto óptimo: VRAM vs velocidade
4. Comparar qualidade de código entre CPU e GPU parcial

### Fase 3 — Ornith (3-6h)

1. Parar Bonsai, testar Ornith no Pascal binary
2. **Ornith é 21 GB Q4_K_M** — NÃO cabe integral na P40 (peso ~21 GB + KV)
3. Testar com `-ngl` parcial (especialistas na CPU, atenção na GPU)
4. Se não couber na P40, registrar bloqueio
5. Se couber, medir: VRAM, tok/s, qualidade em código

### Fase 4 — Integração ao gestor (1-2h)

1. Registrar Laguna GPU no `model_manager.py` como `laguna-xs-2.1-gpu`
2. Criar profile `laguna-programming-v2` com GPU
3. Criar service drop-in ou service separado para Laguna GPU
4. Registrar Ornith GPU funcional (se viável)
5. Atualizar docs

### Fase 5 — Cache adaptativo inspirado no Strata (opcional, ~1 semana)

1. Analisar `--adapt-async` e mecanismos de expert cache no PrismML
2. Se aplicável ao Laguna (arch `laguna` já tem tensor names padrão), implementar
3. Medir ganho vs baseline

---

## 5. Riscos e bloqueios

| Risco | Probabilidade | Mitigação |
|---|---|---|
| I-Compact não cabe na P40 com offload mínimo | Alta | Usar `-ngl` entre 10-30 layers |
| I-Compact com offload é mais lento que CPU | Média | Comparar antes de integrar |
| Ornith não cabe na P40 mesmo com offload | Alta | Priorizar Laguna |
| Pascal binary crasha com Laguna (diferente do Bonsai) | Baixa | Testar com `-c 4096` primeiro |
| MTP do Bonsai quebra com troca de GPU | Baixa | Drop-in mtp.conf é separado |
| RAM + swap insuficiente para CPU+GPU híbrido | Média | Medir antes de declarar funcional |

---

## 6. Contradições identificadas na documentação

| Documento | Contradição | Realidade |
|---|---|---|
| CONTINUITY.md §89 | "Laguna sem inferência demonstrada" | **Inferência CPU demonstrada e funcional** |
| GUIA_MESTRE.md §93 | Ornith 35B GPU como "alternativo, serviço desabilitado" | Confirmado |
| MANUAL_GESTOR_API.md | Laguna cadastrado como "pesos pendentes" | Pesos presentes e funcional |
| PROJECT_STATE.md | "pesos GGUF APEX I-Compact ausentes" | Pesos presentes (15 GB, SHA-256 verificado) |
| CONTINUITY.md §297 | "descarregar GGUF oficial Q4_K_M" | APEX I-Compact já está no disco |

**Acção:** Atualizar documentos após validação GPU.