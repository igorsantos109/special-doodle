import json
from pathlib import Path

from .checkpoints import CheckpointStore, RecoveryRequired
from .database import connect
from .real_graph import execute as real_execute
from .sessions import SessionController, SessionConflict


def _run_triage(root, project, session, task, attempt, prompt,
                *, driver=real_execute, profile="cpu-triage-v1"):
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

    if attempt != attempt_id:
        attempt = attempt_id

    try:
        result = driver(root, command, project, session, task, attempt, prompt,
                        profile=profile)
    except Exception:
        db = connect(database)
        try:
            controller = SessionController(db)
            with controller.transaction():
                db.execute(
                    """UPDATE attempts SET status='INDETERMINATE'
                    WHERE attempt_id=? AND status='RUNNING'""",
                    (attempt,),
                )
                db.execute(
                    "UPDATE tasks SET status='BLOCKED' WHERE task_id=?",
                    (task,),
                )
                controller._set(session, "RECOVERY_REQUIRED")
                controller._event(session, "ATTEMPT_INDETERMINATE", {
                    "attempt_id": attempt,
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
                raise RecoveryRequired("Manifesto invalido")
            confirmed = json.loads(
                (store.root / artifacts[0]["relative_path"]).read_bytes()
            )

            complete = confirmed.get("step") == "concluido"
            changed = db.execute(
                """UPDATE attempts SET status='SUCCEEDED',
                completed_at=CURRENT_TIMESTAMP
                WHERE attempt_id=? AND status='RUNNING'""",
                (attempt,),
            ).rowcount
            if changed != 1:
                raise SessionConflict("Tentativa nao esta mais em execucao")
            db.execute(
                "UPDATE tasks SET status=? WHERE task_id=?",
                ("REVIEW" if complete else "PENDING", task),
            )
            controller._set(session, "RUNNING")
            controller._event(session, "ATTEMPT_CHECKPOINTED", {
                "attempt_id": attempt,
                "checkpoint_id": latest["checkpoint_id"],
                "inference_id": confirmed.get("inference_id", ""),
                "complete": complete,
            })

        state = db.execute(
            "SELECT state FROM sessions WHERE session_id=?", (session,)
        ).fetchone()[0]
        return {
            **result,
            "attempt_id": attempt,
            "checkpoint_id": latest["checkpoint_id"],
            "session_state": state,
        }
    finally:
        db.close()


def run_triage(root, project, session, task, attempt, prompt,
               *, driver=real_execute, profile="cpu-triage-v1"):
    from .locking import database_lock
    root = Path(root).resolve()
    if not (root / "state.sqlite").is_file():
        raise SessionConflict("Banco de sessao ainda nao preparado")
    with database_lock(root / "executor-owner"):
        return _run_triage(
            root, project, session, task, attempt, prompt,
            driver=driver, profile=profile,
        )