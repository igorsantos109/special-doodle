import secrets
from pathlib import Path

from .database import connect
from .migrations import migrate
from .sessions import SessionConflict


def run_unit(root, project, session, task, attempt=None, prompt="",
             driver=None, profile="gpu-triage-v1", _urlopen=None):
    root = Path(root)
    migrate(root / "state.sqlite")
    db = connect(root / "state.sqlite")
    try:
        sess = db.execute(
            "SELECT state FROM sessions WHERE session_id=?", (session,)
        ).fetchone()
        if sess is None or sess["state"] != "RUNNING":
            raise SessionConflict("sessao nao RUNNING")
        row = db.execute(
            "SELECT 1 FROM attempts WHERE session_id=? AND task_id=? AND attempt_id=?",
            (session, task, attempt or ""),
        ).fetchone()
        attempt = attempt or secrets.token_hex(8)
        if row is None:
            db.execute(
                """INSERT INTO attempts (attempt_id, project_id, session_id,
                task_id, status, created_at)
                VALUES (?, ?, ?, ?, 'RUNNING', datetime('now'))""",
                (attempt, project, session, task),
            )
            db.commit()
        if driver is None:
            from .real_graph import execute as driver
        args = (root, "iniciar", project, session, task, attempt, prompt, profile)
        kwargs = {}
        if _urlopen is not None:
            kwargs["_urlopen"] = _urlopen
        return driver(*args, **kwargs)
    finally:
        db.close()
