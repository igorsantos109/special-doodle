# GUIA MESTRE — PC-SALA-AGENT (v8.2 compacto)

**Data:** 22/10/2026 · **Host:** `pc-sala` (192.168.1.150) · **GPU:** Tesla P40 23 GB

## Arquitetura

```
CLI pcsala / ia  →  Worker (LangGraph) / ModelCoordinator
                     →  llama-server (inferência)
```

## Hardware

| Componente | Especificação |
|---|---|
| CPU | Xeon E5-2697 v4, 36 threads @ 2.30 GHz |
| RAM | 30 GiB (~16 GiB livre) |
| GPU | Tesla P40 23.040 MiB, CC 6.1, driver 580.178.04 |
| CUDA | 12.4.131 |

## Modelos

| Modelo | Porta | Ctx | Gen tok/s | Estado |
|---|---|---|---|---|
| Bonsai 27B GPU + MTP | 8080 | 64K | 28-48 | primário |
| Bonsai 9B CPU | 8090 | 32K | 6,08 | ativo |
| Laguna XS 2.1 CPU | 8091 | — | 2,6 | desativado |
| Laguna XS 2.1 GPU | 8082 | 128K | ~47 | desativado |
| Ornith 35B GPU | 8092 | — | ~40 | desativado |

GPU é exclusiva — um modelo por vez.

### Bonsai 27B (primário)
- Modelo: `Ternary-Bonsai-2-27B-PQ2_0.gguf` (6,8 GB) + drafter MTP (1 GB)
- Build: `5d80cff0b` (PrismML + patch Pascal), binário `prism-pascal-build/build/bin/llama-server`
- Flags: `-ngl 99 -t 8 -n 2048 --flash-attn on`, MTP `--spec-type draft-mtp --spec-draft-n-max 2 --spec-draft-p-min 0.4`
- VRAM: ~12,9 GB · Prompt eval: 126-243 tok/s · Aceitação MTP: 0,60-0,87
- `--cache-reuse` e `--context-shift` **não suportados** (rope MROPE)

### Bonsai 9B CPU
- Modelo: `Ternary-Bonsai-2-9B-PQ2_0.gguf` (2,4 GB), 32 threads
- **MTP impossível**: sem cabeça drafter e build CPU sem caminho NEXTN

### Laguna XS 2.1
- CPU: 2,6 tok/s, 17,9 GB RAM. GPU (Pascal): `-ngl 40`, 128K ctx, ~47 tok/s, 15-21 GB VRAM
- GGUF: `Laguna-XS-2.1-APEX-I-Compact.gguf` (15 GB), SHA-256 `b674541d…05d2`

### Ornith 35B
- GGUF: `ornith-1.0-35b-MTP-graft-Q4_K_M.gguf` (21 GB)
- PrismML: 40 tok/s (sem MTP). llama.cpp oficial + MTP: 24,7 tok/s, 74% aceitação, depth 2

## Comandos

```bash
./pcsala models list
./pcsala models switch bonsai-27b-gpu
./pcsala health
./pcsala enqueue --prompt "texto"
./pcsala status <id>
./pcsala cancel <id>
./pcsala reconcile
./pcsala backup
```

## Serviços systemd

| Serviço | Porta | Estado |
|---|---|---|
| `bonsai2-27b.service` | 8080 | active |
| `bonsai2-cpu.service` | 8090 | active |
| `laguna.service` | 8091 | disabled |
| `laguna-gpu.service` | 8082 | disabled |
| `ornith.service` | 8092 | disabled |
| `pcsala-worker.service` | — | worker contínuo |

Firewall: `pcsala-bonsai-firewall.service` (nftables, persiste no reboot), regra `pcsala_api` permite apenas 192.168.0.0/16.

## API

API obrigatória, **API key não**. `Authorization` aceite mas ignorado.

## Limites

- Nenhum executor privilegiado; preparação segura de diretórios pendente.
- Tetos de saída/armazenamento apenas declarados no perfil.
- Checkpoints/arquivos/Git não formam transação conjunta.
- Não executar planas do orquestrador como root.