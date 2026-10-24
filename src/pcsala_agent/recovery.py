from pathlib import Path

from .database import connect
from .locking import database_lock
from .sessions import SessionController, SessionConflict

def classify_interrupted(root, project, session):
    """Classifica interrupcoes. Nao executa nem reconcilia efeitos externos."""
    root = Path(root).resolve()
    database = root / "state.sqlite"
    if not database.is_file():
        raise SessionConflict("Banco inexistente")

    with database_lock(root / "executor-owner"):
        with database_lock(database):
            db = connect(database)
            try:
                controller = SessionController(db)
                with controller.transaction():
                    row = db.execute(
                        """SELECT * FROM sessions
                        WHERE session_id=? AND project_id=?""",
                        (session, project),
                    ).fetchone()
                    if row is None:
                        raise SessionConflict("Sessao nao pertence ao projeto")

                    attempts = db.execute(
                        """UPDATE attempts SET status='INDETERMINATE'
                        WHERE project_id=? AND session_id=? AND status='RUNNING'""",
                        (project, session),
                    ).rowcount
                    operations = db.execute(
                        """UPDATE operations SET status='INDETERMINATE'
                        WHERE project_id=? AND session_id=? AND status='STARTED'""",
                        (project, session),
                    ).rowcount
                    checkpoints = db.execute(
                        """UPDATE checkpoints SET status='NEEDS_RECOVERY'
                        WHERE project_id=? AND session_id=? AND status='PREPARING'""",
                        (project, session),
                    ).rowcount

                    blocked_tasks = db.execute(
                        """UPDATE tasks SET status='BLOCKED'
                        WHERE project_id=? AND task_id IN (
                            SELECT task_id FROM attempts
                            WHERE project_id=? AND session_id=?
                            AND status='INDETERMINATE'
                        )""",
                        (project, project, session),
                    ).rowcount

                    unresolved = 0
                    for table, condition in (
                        ("attempts", "status='INDETERMINATE'"),
                        ("operations", "status='INDETERMINATE'"),
                        ("checkpoints", "status='NEEDS_RECOVERY'"),
                    ):
                        unresolved += db.execute(
                            f"""SELECT COUNT(*) FROM {table}
                            WHERE project_id=? AND session_id=? AND {condition}""",
                            (project, session),
                        ).fetchone()[0]

                    result = {
                        "attempts_classified": attempts,
                        "operations_classified": operations,
                        "checkpoints_classified": checkpoints,
                        "tasks_blocked": blocked_tasks,
                        "unresolved_records": unresolved,
                    }
                    if unresolved:
                        controller._set(session, "RECOVERY_REQUIRED")
                        controller._event(
                            session, "INTERRUPTION_CLASSIFIED", result
                        )
                return result
            finally:
                db.close()
