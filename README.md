# PC-SALA Agent

Hybrid agentic programming prototype (handoff 1.0). Not production-grade.

## Quick start

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.lock
PYTHONPATH="$PWD/src" .venv/bin/python -m pytest -q tests
./pcsala health
```

## CLI

```text
pcsala enqueue --prompt "..." [--profile gpu-triage-v1] [--idempotency-key K]
pcsala document --path <file> [--profile gpu-triage-v1]
pcsala document-deps
pcsala list [--status QUEUED|RESERVED|COMPLETED|FAILED|CANCELLED]
pcsala status <id>
pcsala cancel <id>
pcsala reconcile
pcsala health
pcsala backup
pcsala models {list,status,health,start,stop,switch,vram,operation}
```

## Models (GPU is exclusive for big models — one at a time)

| Modelo | Porta | Ctx | Gen tok/s | Notas |
|---|---|---|---|---|
| Bonsai 27B GPU + MTP | 8080 | 64K | 28-48 | Primario, exclusivo (gpu-slot-1) |
| Bonsai 4B GPU | 8093 | 64K | — | Residente (nao habilitado no boot) |
| Bonsai 9B CPU | 8090 | 32K | 6.08 | Sem MTP |
| Laguna XS 2.1 CPU | 8091 | — | — | Desativado (libera RAM) |
| Laguna XS 2.1 GPU | 8082 | 128K | ~47 | Build Pascal; exclusivo (gpu-slot-1) |
| Ornith 35B GPU | 8092 | — | ~40 | PrismML runtime; exclusivo (gpu-slot-1) |

Apenas o Bonsai 4B fica residente na GPU. O Bonsai 27B, Laguna GPU e
Ornith compoem o grupo exclusivo `gpu-slot-1`: apenas um fica carregado
por vez. O `switch` aplica-se apenas a modelos desse grupo.

`pcsala models vram` mostra a VRAM usada por modelo e a folga (nvidia-smi).
`start` e `switch` recusam o arranque se a folga for menor que 1,5 GB.

Switch: `./pcsala models switch <model-id>` (e.g. `bonsai-27b-gpu` ou
`laguna-xs-2.1-gpu`).

## Architecture

- SQLite persistence, versioned migrations (`migrations/`), checkpoints with SHA-256 artifacts.
- Persistent sessions, attempts, pause/resume, audit trail.
- Strict request/result contracts; deterministic planner (no command execution).
- Interrupt classification without automatic retry; logical shutdown DRAINING -> CHECKPOINTING -> STOPPED.
- Continuous worker + persistent task queue; reconciliation of RESERVED tasks.
- Model manager for exclusive GPU switching (reserve_engine persisted in SQLite, CUDA_VISIBLE_DEVICES, lock em /run/pcsala/).
- Document flow (pdfminer optional) and output collection/probing.
- Slot save/restore de KV para documentos longos (desativado por default; ativar apenas apos validar MROPE num slot descartavel).

## Operations

Services: `bonsai2-27b.service` (8080), `pcsala-worker.service`, optional `bonsai-4b-gpu.service` (8093, residente, nao no boot), `laguna-gpu.service` (8082), `ornith.service` (8092).

```bash
sudo systemctl {start|stop|status} bonsai2-27b.service pcsala-worker.service
./pcsala health
./pcsala reconcile
./pcsala backup
./pcsala models list
./pcsala models vram
```

## API policy

API required, API key not. Services accept `Authorization` but ignore it. Network restricted via ufw + nft to 192.168.0.0/16.

## Limits

- No privileged executor enabled; no sudo rules for agent.
- Safe directory preparation pending.
- Output/storage caps declared in profile only.
- No universal exactly-once guarantee; checkpoints/files/Git are not a single transaction.
- Do not run an orchestrator plan directly as root.

## Docs

Detailed guides: `guias/` (GUIA_MESTRE, MANUAL_GESTOR_API, TUTORIAL_GESTOR, diagnostics). State: `PROJECT_STATE.md`. Recovery procedure: `CONTINUITY.md`.
