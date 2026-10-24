import json
from pathlib import Path

from .checkpoints import CheckpointStore, RecoveryRequired
from .database import connect
from .sessions import SessionController, SessionConflict
from .simulated import SimulationState, execute as simulated_execute

def _run_unit(root, project, session, task, *, driver=simulated_execute):
    """Uma unidade simulada. Nao executa ferramentas nem codigo de projetos."""
    root = Path(root).resolve()
    database = root / "state.sqlite"
    if not database.is_file():
        raise SessionConflict("Banco de sessao ainda nao preparado")

    db = connect(database)
    try:
        controller = SessionController(db)
        row = db.execute(
            "SELECT project_id,revision FROM sessions WHERE session_id=?",
            (session,),
        ).fetchone()
        if row is None or row["project_id"] != project:
            raise SessionConflict("Sessao nao pertence ao projeto")

        store = CheckpointStore(db, root / "artifacts")
        previous = store.latest(project, session, task)
        command = "iniciar" if previous is None else "retomar"
        dispatched = controller.dispatch(session, row["revision"], task)
        attempt_id = dispatched["attempt_id"]
    finally:
        db.close()

    try:
        result = driver(root, command, project, session, task)
    except Exception:
        db = connect(database)
        try:
            controller = SessionController(db)
            with controller.transaction():
                db.execute(
                    """UPDATE attempts SET status='INDETERMINATE'
                    WHERE attempt_id=? AND status='RUNNING'""",
                    (attempt_id,),
                )
                db.execute(
                    "UPDATE tasks SET status='BLOCKED' WHERE task_id=?",
                    (task,),
                )
                controller._set(session, "RECOVERY_REQUIRED")
                controller._event(session, "ATTEMPT_INDETERMINATE", {
                    "attempt_id": attempt_id,
                    "reason": "driver_exception",
                })
        finally:
            db.close()
        raise
        db = connect(database)
        try:
            controller = SessionController(db)
            with controller.transaction():
                db.execute(
                    """UPDATE attempts SET status='INDETERMINATE'
                    WHERE attempt_id=? AND status='RUNNING'""",
                    (attempt_id,),
                )
                db.execute(
                    "UPDATE tasks SET status='BLOCKED' WHERE task_id=?",
                    (task,),
                )
                controller._set(session, "RECOVERY_REQUIRED")
                controller._event(session, "ATTEMPT_INDETERMINATE", {
                    "attempt_id": attempt_id,
                    "reason": "driver_exception",
                })
        finally:
            db.close()
        raise

    db = connect(database)
    try:
        controller = SessionController(db)
        store = CheckpointStore(db, root / "artifacts")
        with controller.transaction():
            latest = store.latest(project, session, task)
            if latest is None:
                raise RecoveryRequired("Executor retornou sem checkpoint")
            artifacts = db.execute(
                "SELECT relative_path FROM artifacts WHERE checkpoint_id=?",
                (latest["checkpoint_id"],),
            ).fetchall()
            if len(artifacts) != 1:
                raise RecoveryRequired("Manifesto simulado invalido")
            saved = SimulationState.model_validate_json(
                (store.root / artifacts[0]["relative_path"]).read_bytes()
            )
            if (saved.project_id, saved.session_id, saved.task_id) != (
                project, session, task
            ):
                raise RecoveryRequired("Escopo divergente")
            if result.get("completed_steps") != saved.completed_steps:
                raise RecoveryRequired("Resultado diverge do checkpoint")

            complete = result.get("status") == "SIMULACAO_CONCLUIDA"
            if complete != (saved.completed_steps == 2):
                raise RecoveryRequired("Conclusao simulada inconsistente")

            changed = db.execute(
                """UPDATE attempts SET status='SUCCEEDED',
                completed_at=CURRENT_TIMESTAMP
                WHERE attempt_id=? AND status='RUNNING'""",
                (attempt_id,),
            ).rowcount
            if changed != 1:
                raise SessionConflict("Tentativa nao esta mais em execucao")
            db.execute(
                "UPDATE tasks SET status=? WHERE task_id=?",
                ("REVIEW" if complete else "PENDING", task),
            )
            current = db.execute(
                "SELECT state FROM sessions WHERE session_id=?", (session,)
            ).fetchone()
            controller._set(session, current["state"])
            controller._event(session, "ATTEMPT_CHECKPOINTED", {
                "attempt_id": attempt_id,
                "checkpoint_id": latest["checkpoint_id"],
                "simulated_complete": complete,
            })

        current = db.execute(
            "SELECT state,revision FROM sessions WHERE session_id=?", (session,)
        ).fetchone()
        if current["state"] == "PAUSE_REQUESTED":
            requests = db.execute(
                """SELECT request_id FROM control_requests
                WHERE session_id=? AND action='PAUSE' AND status='REQUESTED'""",
                (session,),
            ).fetchall()
            if len(requests) != 1:
                raise SessionConflict("Pedido de pausa ambiguo")
            controller.confirm_pause(
                session, current["revision"], requests[0]["request_id"],
                latest["checkpoint_id"], store,
            )

        state = db.execute(
            "SELECT state FROM sessions WHERE session_id=?", (session,)
        ).fetchone()[0]
        return {
            **result,
            "attempt_id": attempt_id,
            "checkpoint_id": latest["checkpoint_id"],
            "session_state": state,
        }
    finally:
        db.close()


def run_unit(root, project, session, task, *, driver=simulated_execute):
    from .locking import database_lock
    root = Path(root).resolve()
    if not (root / "state.sqlite").is_file():
        raise SessionConflict("Banco de sessao ainda nao preparado")
    with database_lock(root / "executor-owner"):
        return _run_unit(
            root, project, session, task, driver=driver
        )
