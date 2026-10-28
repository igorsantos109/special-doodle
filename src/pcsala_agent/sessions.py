import secrets
from datetime import UTC, datetime

VALID_SESSION_STATES = (
    "STOPPED", "STARTING", "READY", "RUNNING",
    "PAUSE_REQUESTED", "PAUSED", "DRAINING", "CHECKPOINTING",
    "ERROR", "RECOVERY_REQUIRED",
)

TRANSITIONS = {
    "STOPPED": {"STARTING"},
    "STARTING": {"READY"},
    "READY": {"RUNNING"},
    "RUNNING": set(),
    "PAUSED": {"RUNNING"},
    "PAUSE_REQUESTED": {"PAUSED"},
    "DRAINING": {"CHECKPOINTING"},
    "CHECKPOINTING": {"STOPPED"},
}


class SessionConflict(Exception):
    pass


def _now():
    return datetime.now(UTC).isoformat(timespec="seconds")


class SessionController:
    def __init__(self, db):
        self.db = db

    def advance(self, session_id, expected_revision, state):
        row = self.db.execute(
            "SELECT revision, state FROM sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()
        if row is None:
            raise SessionConflict("sessao inexistente")
        if row["revision"] != expected_revision:
            raise SessionConflict("revisao desatualizada")
        current_state = row["state"]
        if current_state not in TRANSITIONS:
            raise SessionConflict("sessao em estado invalido")
        if state not in TRANSITIONS[current_state]:
            raise SessionConflict("transicao invalida")
        new_revision = row["revision"] + 1
        with self.db:
            self.db.execute(
                "UPDATE sessions SET state=?, revision=? WHERE session_id=?",
                (state, new_revision, session_id),
            )
        return new_revision

    def request_pause(self, session_id, revision):
        session = self.db.execute(
            "SELECT state, revision FROM sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()
        if session is None:
            raise SessionConflict("sessao inexistente")
        if session["revision"] != revision:
            raise SessionConflict("revisao desatualizada")
        if session["state"] != "RUNNING":
            raise SessionConflict("sessao nao RUNNING")
        request_id = secrets.token_hex(8)
        new_revision = revision + 1
        with self.db:
            self.db.execute(
                """INSERT INTO control_requests
                (request_id, session_id, action) VALUES (?, ?, 'PAUSE')""",
                (request_id, session_id),
            )
            self.db.execute(
                "UPDATE sessions SET state='PAUSE_REQUESTED', revision=? WHERE session_id=?",
                (new_revision, session_id),
            )
        return {"request_id": request_id, "revision": new_revision}

    def dispatch(self, session_id, revision, task_id):
        row = self.db.execute(
            "SELECT revision, state FROM sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()
        if row is None:
            raise SessionConflict("sessao inexistente")
        if row["revision"] != revision:
            raise SessionConflict("revisao desatualizada")
        if row["state"] != "RUNNING":
            raise SessionConflict("sessao nao RUNNING")
        existing = self.db.execute(
            "SELECT 1 FROM attempts WHERE session_id=? AND task_id=? AND status='RUNNING' LIMIT 1",
            (session_id, task_id),
        ).fetchone()
        if existing is not None:
            raise SessionConflict("tentativa ativa")
        attempt_id = secrets.token_hex(8)
        project_id = self.db.execute(
            "SELECT project_id FROM sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()["project_id"]
        new_revision = revision + 1
        with self.db:
            self.db.execute(
                """INSERT INTO attempts
                (attempt_id, project_id, session_id, task_id, status)
                VALUES (?, ?, ?, ?, 'RUNNING')""",
                (attempt_id, project_id, session_id, task_id),
            )
            self.db.execute(
                "UPDATE sessions SET revision=? WHERE session_id=?",
                (new_revision, session_id),
            )
        return {"attempt_id": attempt_id, "revision": new_revision}

    def confirm_pause(self, session_id, revision, request_id, checkpoint_id, store):
        session = self.db.execute(
            "SELECT revision, state FROM sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()
        if session is None:
            raise SessionConflict("sessao inexistente")
        if session["revision"] != revision:
            raise SessionConflict("revisao desatualizada")
        if session["state"] != "PAUSE_REQUESTED":
            raise SessionConflict("sessao nao PAUSE_REQUESTED")
        active = self.db.execute(
            "SELECT 1 FROM attempts WHERE session_id=? AND status='RUNNING' LIMIT 1",
            (session_id,),
        ).fetchone()
        if active is not None:
            raise SessionConflict("tentativa ativa")
        project_id = self.db.execute(
            "SELECT project_id FROM sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()["project_id"]
        ckpt = self.db.execute(
            "SELECT project_id, task_id FROM checkpoints WHERE checkpoint_id=?",
            (checkpoint_id,),
        ).fetchone()
        if ckpt is None:
            raise SessionConflict("checkpoint inexistente")
        store.latest(ckpt["project_id"], session_id, ckpt["task_id"])
        req = self.db.execute(
            "SELECT checkpoint_id FROM checkpoints WHERE checkpoint_id=?",
            (checkpoint_id,),
        ).fetchone()
        if req is None:
            raise SessionConflict("checkpoint inexistente")
        new_revision = session["revision"] + 1
        with self.db:
            self.db.execute(
                "UPDATE sessions SET state='PAUSED', revision=? WHERE session_id=?",
                (new_revision, session_id),
            )
            self.db.execute(
                "UPDATE control_requests SET status='APPLIED' WHERE request_id=?",
                (request_id,),
            )
            self.db.execute(
                """INSERT INTO audit_events
                (event_id, session_id, event_type, details_json)
                VALUES (?, ?, 'PAUSED', ?)""",
                (secrets.token_hex(8), session_id, "{}"),
            )
        return new_revision
