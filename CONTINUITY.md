# Recuperação (atualizado 2026-10-23)

**Testes:** `PYTHONPATH="$PWD/src" .venv/bin/python -m pytest tests/ -v --tb=short`

## Última ação — Bonsai 27B: "Output token limit reached"

- Contexto do modelo: `-c 64000` (era 55000). Margem ~59,9K tok.
- `context_budget.PRIMARY_CONTEXT = 64000`.
- Context shift e `-kvu` inertes para este modelo (rope MROPE); removidos do drop-in.
- dsh remoto: `contextWindow: 58000`, `maxTokens: 4096` (atualizar à mão).

## Limites

- O servidor NÃO trunca prompt maior que o ctx (só erro).
- Compactação é obrigatoriamente do lado do dsh.

## Recuperação pós-reboot

- `sudo systemctl start bonsai2-27b.service pcsala-worker.service`
- `./pcsala reconcile` e `./pcsala backup`.
- Verificar GPU exclusiva: apenas um modelo por vez.

## Serviços

| Serviço | Porta | Estado |
|---|---|---|
| `bonsai2-27b.service` | 8080 | active (primário) |
| `laguna-gpu.service` | 8082 | disabled |
| `ornith.service` | 8092 | disabled |
| `pcsala-worker.service` | — | worker contínuo |