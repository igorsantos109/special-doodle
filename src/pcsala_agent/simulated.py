import argparse
import json
import sys
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .checkpoints import CheckpointStore, RecoveryRequired
from .database import connect, initialize
from .locking import ExecutorBusy, database_lock

class SimulationState(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    project_id: str
    session_id: str
    task_id: str
    completed_steps: int = Field(ge=1, le=2)

def execute(root, command, project, session, task):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    database = root / "state.sqlite"

    with database_lock(database):
        existed = database.exists()
        db = connect(database)
        try:
            if not existed:
                migration = (
                    Path(__file__).resolve().parents[2]
                    / "migrations/001_checkpoints.sql"
                )
                initialize(db, migration)

            store = CheckpointStore(db, root / "artifacts")
            scope = (project, session, task)

            if command == "retomar":
                store.recover(project, session)

            blocked = db.execute(
                """SELECT COUNT(*) FROM checkpoints
                WHERE project_id=? AND session_id=?
                  AND status='NEEDS_RECOVERY'""",
                (project, session),
            ).fetchone()[0]
            uncertain = db.execute(
                """SELECT COUNT(*) FROM operations
                WHERE project_id=? AND session_id=?
                  AND status IN ('STARTED', 'INDETERMINATE')""",
                (project, session),
            ).fetchone()[0]
            if blocked or uncertain:
                raise RecoveryRequired(
                    "Sessao bloqueada: checkpoint incompleto ou operacao incerta"
                )

            latest = store.latest(*scope)

            if command == "iniciar":
                if latest is not None:
                    raise RecoveryRequired(
                        "Trabalho ja iniciado; use retomar com os mesmos IDs"
                    )
                state = SimulationState(
                    project_id=project, session_id=session,
                    task_id=task, completed_steps=1,
                )
            else:
                if latest is None:
                    raise RecoveryRequired("Nenhum checkpoint confirmado neste escopo")
                rows = db.execute(
                    "SELECT relative_path FROM artifacts WHERE checkpoint_id=?",
                    (latest["checkpoint_id"],),
                ).fetchall()
                if len(rows) != 1:
                    raise RecoveryRequired("Manifesto simulado invalido")
                state = SimulationState.model_validate_json(
                    (store.root / rows[0]["relative_path"]).read_bytes()
                )
                if (state.project_id, state.session_id, state.task_id) != scope:
                    raise RecoveryRequired("Artefato pertence a outro escopo")
                if state.completed_steps == 2:
                    return {
                        "status": "SIMULACAO_CONCLUIDA",
                        "checkpoint_id": latest["checkpoint_id"],
                        "nova_execucao": False,
                    }
                state = state.model_copy(update={"completed_steps": 2})

            cid = store.prepare(*scope)
            store.add_artifact(cid, state.model_dump_json().encode("utf-8"))
            store.commit(cid)
            return {
                "status": (
                    "SIMULACAO_CONCLUIDA"
                    if state.completed_steps == 2 else "CHECKPOINT_SALVO"
                ),
                "checkpoint_id": cid,
                "completed_steps": state.completed_steps,
                "nova_execucao": True,
            }
        finally:
            db.close()

def main():
    parser = argparse.ArgumentParser(description="Executor simulado local")
    parser.add_argument("command", choices=["iniciar", "retomar"])
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--project", required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument("--task", required=True)
    args = parser.parse_args()
    try:
        result = execute(
            args.root, args.command, args.project, args.session, args.task
        )
    except ExecutorBusy as error:
        print(str(error), file=sys.stderr)
        return 3
    except RecoveryRequired as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
