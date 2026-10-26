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
pcsala exec-demo
pcsala models {list,status,health,start,stop,switch}
```

## Models (GPU is exclusive — one at a time)

| Model | Port | Ctx | Gen tok/s | Notes |
|---|---|---|---|---|
| Bonsai 27B GPU + MTP | 8080 | 55K | 28-48 | Primary |
| Bonsai 9B CPU | 8090 | 32K | 6.08 | No MTP |
| Laguna XS 2.1 CPU | 8091 | — | — | Disabled (frees RAM) |
| Laguna XS 2.1 GPU | 8082 | 128K | ~47 | Pascal build |
| Ornith 35B GPU | 8092 | — | ~40 | PrismML runtime; MTP experimental |

Switch: `./pcsala models switch <model-id>` (e.g. `bonsai-27b-gpu`).

## Architecture

- SQLite persistence, versioned migrations (`migrations/`), checkpoints with SHA-256 artifacts.
- Persistent sessions, attempts, pause/resume, audit trail.
- Strict request/result contracts; deterministic planner (no command execution).
- Interrupt classification without automatic retry; logical shutdown DRAINING -> CHECKPOINTING -> STOPPED.
- Continuous worker + persistent task queue; reconciliation of RESERVED tasks.
- Model manager for exclusive GPU switching.
- Document flow (pdfminer optional) and output collection/probing.

## Operations

Services: `bonsai2-27b.service` (8080), `pcsala-worker.service`, optional `laguna-gpu.service` (8082), `ornith.service` (8092).

```bash
sudo systemctl {start|stop|status} bonsai2-27b.service pcsala-worker.service
./pcsala health
./pcsala reconcile
./pcsala backup
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
""" , "filePath": "/home/igor/ia-sh/pc-sala-agent/README.md"}