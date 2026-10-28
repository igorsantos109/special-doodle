from pathlib import Path

from .checkpoints import CheckpointStore
from .database import connect
from .locking import database_lock


def classify_interrupted(root, project=None, session=None):
    root = Path(root)
    db = connect(root / "state.sqlite")
    try:
        with database_lock(root / "executor-owner"):
            attempts = db.execute(
                """SELECT attempt_id, task_id, project_id FROM attempts
                WHERE status='RUNNING' AND project_id=? AND session_id=?""",
                (project, session),
            ).fetchall()

            attempts_classified = 0
            for att in attempts:
                db.execute(
                    "UPDATE attempts SET status='INDETERMINATE', completed_at=? "
                    "WHERE attempt_id=?",
                    (db.execute(
                        "SELECT strftime('%Y-%m-%dT%H:%M:%S','now')").fetchone()[0],
                     att["attempt_id"]),
                )
                db.execute(
                    "UPDATE tasks SET status='BLOCKED' WHERE task_id=? AND project_id=?",
                    (att["task_id"], att["project_id"]),
                )
                attempts_classified += 1

            with db:
                store = CheckpointStore(db, root / "artifacts")
                recovered = store.recover(project, session)
                checkpoints_classified = recovered["checkpoints"]
            operations_marked = recovered["operations"]

            unresolved = db.execute(
                """SELECT COUNT(*) FROM attempts
                WHERE status='INDETERMINATE' AND project_id=? AND session_id=?""",
                (project, session),
            ).fetchone()[0]

            if attempts_classified or checkpoints_classified:
                db.execute(
                    "UPDATE sessions SET state='RECOVERY_REQUIRED' "
                    "WHERE state='RUNNING' AND project_id=? AND session_id=?",
                    (project, session),
                )
            db.commit()
    finally:
        db.close()

    return {
        "attempts_classified": attempts_classified,
        "checkpoints_classified": checkpoints_classified,
        "operations_marked": operations_marked,
        "unresolved_records": unresolved,
    }
