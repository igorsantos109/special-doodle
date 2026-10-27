from pathlib import Path

from .database import connect
from .locking import database_lock
from .sessions import SessionConflict, SessionController


class ShutdownController:
    def __init__(self, root):
        self.root = Path(root)
        self.db = connect(self.root / "state.sqlite")
        self.controller = SessionController(self.db)

    def request(self, session_id, revision):
        row = self.db.execute(
            "SELECT revision FROM sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()
        if row is None:
            raise SessionConflict("sessao inexistente")
        if row["revision"] != revision:
            raise SessionConflict("revisao desatualizada")
        new_revision = revision + 1
        request_id = "shutdown-" + revision.__str__()
        with self.db:
            self.db.execute(
                """INSERT INTO control_requests
                (request_id, session_id, action) VALUES (?, ?, 'DRAIN')""",
                (request_id, session_id),
            )
            self.db.execute(
                "UPDATE sessions SET state='DRAINING', revision=? WHERE session_id=?",
                (new_revision, session_id),
            )
        return {"request_id": request_id, "revision": new_revision}

    def prepare(self, session_id, revision, request_id, checkpoint_id):
        with database_lock(self.root / "executor-owner"):
            row = self.db.execute(
                "SELECT revision, state FROM sessions WHERE session_id=?",
                (session_id,),
            ).fetchone()
            if row is None:
                raise SessionConflict("sessao inexistente")
            if row["revision"] != revision:
                raise SessionConflict("revisao desatualizada")
            if row["state"] != "DRAINING":
                raise SessionConflict("sessao nao DRAINING")
            active = self.db.execute(
                "SELECT 1 FROM attempts WHERE session_id=? AND status='RUNNING' LIMIT 1",
                (session_id,),
            ).fetchone()
            if active is not None:
                raise SessionConflict("tentativa ativa")
            new_revision = revision + 1
            with self.db:
                self.db.execute(
                    "UPDATE sessions SET state='CHECKPOINTING', revision=? WHERE session_id=?",
                    (new_revision, session_id),
                )
            return new_revision

    def confirm(self, session_id, revision, request_id):
        from .checkpoints import CheckpointStore
        with database_lock(self.root / "executor-owner"):
            row = self.db.execute(
                "SELECT revision, state FROM sessions WHERE session_id=?",
                (session_id,),
            ).fetchone()
            if row is None:
                raise SessionConflict("sessao inexistente")
            if row["revision"] != revision:
                raise SessionConflict("revisao desatualizada")
            if row["state"] != "CHECKPOINTING":
                raise SessionConflict("sessao nao CHECKPOINTING")
            ckpt = self.db.execute(
                """SELECT checkpoint_id FROM checkpoints
                WHERE session_id=? AND status='COMMITTED'
                ORDER BY seq DESC LIMIT 1""",
                (session_id,),
            ).fetchone()
            if ckpt is None:
                raise SessionConflict("checkpoint inexistente")
            store = CheckpointStore(self.db, self.root / "artifacts")
            store.commit(ckpt["checkpoint_id"])
            new_revision = revision + 1
            with self.db:
                self.db.execute(
                    "UPDATE sessions SET state='STOPPED', revision=? WHERE session_id=?",
                    (new_revision, session_id),
                )
                self.db.execute(
                    "UPDATE control_requests SET status='APPLIED' WHERE request_id=?",
                    (request_id,),
                )
            return new_revision
