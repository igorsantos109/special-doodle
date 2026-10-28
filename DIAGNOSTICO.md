# DIAGNOSTICO — FASE 0 (2026-10-26)

## 1. Estado do repositório

`git ls-files | grep -c '^src/'` → **0**. `git check-ignore -v src` → nada (não está
ignorado). O diretório `src/pcsala_agent/` existe no working tree mas contém apenas
`__pycache__/` vazio — **todo o código-fonte está ausente**.

### Raiz do problema

O `.git` foi corrompido (objects ausentes) e recriado no momento da refatoração da
documentação. Os arquivos de `src/` e `configs/`, `scripts/` foram apagados do working
tree e não puderam ser restaurados do índice (não há commits).

### Proposta de correção (FASE 1)

- Recuperar o código de backups locais (ver `registros/` e cópias em `$HOME`) ou
  recriar a partir dos testes + migrações SQL + script `pcsala`.
- Se não houver cópia, o repositório deve ser reconstruído; não é possível diagnosticar
  módulos inexistente.

## 2. Clone limpo / venv / pytest

- `python3 -m venv .venv` → ok (Python 3.13.5).
- `pip install -r requirements.lock` → **falha com hash mismatch** em
  `charset-normalizer==3.5.2` (esperado `34276fd7…`, obtido `7218e8f3…`).
  A lock file tem hashes desatualizados para a plataforma atual.
- `pip install -r requirements.in` → ok.
- `PYTHONPATH=src pytest -q tests` → **23 erros de coleta**, todos
  `ModuleNotFoundError: No module named 'pcsala_agent.<modulo>'`.

## 3. Módulos esperados (a partir dos imports nos testes)

```
pcsala_agent.attempt_directories
pcsala_agent.checkpoints
pcsala_agent.context_budget
pcsala_agent.controlled
pcsala_agent.database
pcsala_agent.document_flow
pcsala_agent.execution_acceptance
pcsala_agent.execution_contract
pcsala_agent.execution_eligibility
pcsala_agent.execution_plan
pcsala_agent.execution_result_adapter
pcsala_agent.graph_runner
pcsala_agent.inference_adapter
pcsala_agent.inference_contract
pcsala_agent.inference_profiles
pcsala_agent.locking
pcsala_agent.migrations
pcsala_agent.output_collector
pcsala_agent.output_probe
pcsala_agent.real_graph
pcsala_agent.recovery
pcsala_agent.sessions
pcsala_agent.shutdown
pcsala_agent.simulated
```

Grafo de dependências (inferido dos imports nos testes, não pode ser verificado no código):

```
cli (pcsala) ──► models_cli, queue_cli, model_manager, graph_runner
database ──► checkpoints, sessions, migrations, execution_acceptance, model_operations
checkpoints ──► recovery, shutdown
graph_runner ──► inference_adapter, execution_contract, execution_runner, locking
inference_adapter ──► inference_contract, inference_profiles
document_flow ──► output_collector, output_probe
```

## 4. I/O fixo em caminhos absolutos (detectado nos testes e docs)

- `tests/test_document_flow.py` — `AUTHORIZED_ROOTS` contém `/home/igor/pc-sala-agent`
  (caminho hardcodado do host).
- `pcsala` (raiz) — `WORKER_ROOT = Path("/var/lib/pcsala-worker")`,
  `BACKUP_DIR = Path("/home/igor/.config/pcsala-bonsai")`.
- `CONTINUITY.md` — `Raiz: /home/igor/pc-sala-agent`.
- `guias/GUIA_MESTRE.md` — `Projeto: /home/igor/pc-sala-agent`.

## 5. Código morto / arquivos `.bak` removidos

Removidos em 2026-10-26: `CONTINUITY.md.bak`, `PROJECT_STATE.md.bak`,
`pcsala.bak`, `tests/test_models_laguna.py.bak`,
`src/pcsala_agent/inference_profiles.py.bak` e backups em `registros/`.

## 6. Bloqueio atual

Sem o código-fonte não é possível produzir: árvore de módulos real, funções acima de
60 linhas, nem verificar imports circulares. A FASE 1 (incluir `src/`, pyproject.toml,
unificar caminhos) depende da recuperação do código.

## 7. Próximos passos

1. Recuperar `src/pcsala_agent/*.py` (cópia local ou recriação).
2. Recriar `pyproject.toml` com `pythonpath=["src"]` e entry point `pcsala`.
3. Parametrizar caminhos por `PCSALA_HOME` / `PCSALA_ROOT` / `PCSALA_BACKUP_DIR`.
4. Re-executar `pytest -q` e `pcsala health`.