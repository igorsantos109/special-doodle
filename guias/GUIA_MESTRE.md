# GUIA MESTRE — PC-SALA-AGENT (v8.2 compacto)

**Data:** 22/10/2026 · **Host:** `pc-sala` (192.168.1.150) · **GPU:** Tesla P40 23 GB

## Arquitetura

```
CLI pcsala / ia  →  Worker (LangGraph) / ModelCoordinator
                     →  llama-server (inferencia)
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
| Bonsai 27B GPU + MTP | 8080 | 64K | 28-48 | primario, exclusivo (gpu-slot-1) |
| Bonsai 4B GPU | 8093 | 64K | — | residente, nao no boot |
| Bonsai 9B CPU | 8090 | 32K | 6,08 | ativo |
| Laguna XS 2.1 CPU | 8091 | — | 2,6 | desativado |
| Laguna XS 2.1 GPU | 8082 | 128K | ~47 | desativado, exclusivo (gpu-slot-1) |
| Ornith 35B GPU | 8092 | — | ~40 | desativado, exclusivo (gpu-slot-1) |

GPU exclusiva para modelos grandes — um por vez (27B, Laguna, Ornith).
Apenas o Bonsai 4B fica residente na GPU.

### Bonsai 27B (primario)
- Modelo: `Ternary-Bonsai-2-27B-PQ2_0.gguf` (6,8 GB) + drafter MTP (1 GB)
- Build: `5d80cff0b` (PrismML + patch Pascal), binario `prism-pascal-build/build/bin/llama-server`
- Flags: `-c 64000 -ngl 99 -t 8 -n 2048 --flash-attn on`, MTP `--spec-type draft-mtp --spec-draft-n-max 2 --spec-draft-p-min 0.4`, `--slot-save-path /var/lib/pcsala-worker/slots`
- VRAM: ~12,9 GB · Prompt eval: 126-243 tok/s · Aceitacao MTP: 0,60-0,87
- `--cache-reuse` e `--context-shift` **não suportados** (rope MROPE)
- Sem `--api-key-file` (docs dizem "API key nao"); `--no-kv-offload` removido.

### Bonsai 4B (residente)
- Porta 8093, build Pascal, mesmo binario, `--slot-save-path` habilitado.
- Nao habilitado no boot; iniciar manualmente quando necessario.

### Bonsai 9B CPU
- Modelo: `Ternary-Bonsai-2-9B-PQ2_0.gguf` (2,4 GB), 32 threads
- **MTP impossível**: sem cabeça drafter e build CPU sem caminho NEXTN

### Laguna XS 2.1
- CPU: 2,6 tok/s, 17,9 GB RAM. GPU (Pascal): `-ngl 40`, 128K ctx, ~47 tok/s, 15-21 GB VRAM
- GGUF: `Laguna-XS-2.1-APEX-I-Compact.gguf` (15 GB), SHA-256 `b674541d…05d2`

### Ornith 35B
- GGUF: `ornith-1.0-35b-MTP-graft-Q4_K_M.gguf` (21 GB)
- PrismML: 40 tok/s (sem MTP). llama.cpp oficial + MTP: 24,7 tok/s, 74% aceitacao, depth 2

## Comandos

```bash
./pcsala models list
./pcsala models status <id>
./pcsala models health <id>
./pcsala models start <id>
./pcsala models stop <id>
./pcsala models switch <id>   # apenas modelos exclusivos (27B, Laguna GPU, Ornith)
./pcsala models vram          # VRAM por modelo e folga
./pcsala models operation <id>
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
| `bonsai-4b-gpu.service` | 8093 | disabled (residente, nao no boot) |
| `bonsai2-cpu.service` | 8090 | active |
| `laguna.service` | 8091 | disabled |
| `laguna-gpu.service` | 8082 | disabled |
| `ornith.service` | 8092 | disabled |
| `pcsala-worker.service` | — | worker contínuo |

Lock de troca de GPU: `/run/pcsala/pcsala-gpu-switch.lock`.

Firewall: `pcsala-bonsai-firewall.service` (nftables, persiste no reboot), regra `pcsala_api` permite apenas 192.168.0.0/16.

## API

API obrigatória, **API key não**. `Authorization` aceite mas ignorado.

## Slot save/restore de KV (documentos longos)

Subiu os serviços com `--slot-save-path`. O worker chama `POST /slots/<id>?action=save|restore` em tarefas "document" com prefixo repetido.

**Desativado por default.** Ativar apenas (`PCSALA_SLOT_SAVE_RESTORE=1`) apos validar num slot descartavel se o MROPE aceita o restauro. Se nao aceitar, registrar neste guia e manter desativado.

## Limites

- Nenhum executor privilegiado; preparacao segura de diretorios pendente.
- Tetos de saida/armazenamento apenas declarados no perfil.
- Checkpoints/arquivos/Git nao formam transacao conjunta.
- Nao executar planos do orquestrador como root.
