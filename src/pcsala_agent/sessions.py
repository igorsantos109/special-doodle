import json
from contextlib import contextmanager

from .checkpoints import new_id

class SessionConflict(RuntimeError):
    pass

class SessionController:
    """Controle cooperativo. Usar conexao exclusiva da thread chamadora."""

    def __init__(self, db):
        self.db = db

    @contextmanager
    def transaction(self):
        if self.db.in_transaction:
            raise SessionConflict("Transacao externa em curso")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def _session(self, session_id, revision):
        row = self.db.execute(
            "SELECT * FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        if row is None:
            raise SessionConflict("Sessao inexistente")
        if row["revision"] != revision:
            raise SessionConflict("Revisao desatualizada")
        return row

    def _event(self, session_id, event_type, details):
        self.db.execute(
            """INSERT INTO audit_events
            (event_id,session_id,event_type,details_json) VALUES (?,?,?,?)""",
            (new_id(), session_id, event_type, json.dumps(details)),
        )

    def _set(self, session_id, state):
        self.db.execute(
            "UPDATE sessions SET state=?, revision=revision+1 WHERE session_id=?",
            (state, session_id),
        )

    def advance(self, session_id, revision, target):
        allowed = {
            ("STOPPED", "STARTING"),
            ("STARTING", "READY"),
            ("READY", "RUNNING"),
            ("PAUSED", "READY"),
        }
        with self.transaction():
            session = self._session(session_id, revision)
            if (session["state"], target) not in allowed:
                raise SessionConflict("Transicao nao permitida")
            self._set(session_id, target)
            self._event(session_id, "STATE_CHANGED", {
                "from": session["state"], "to": target,
            })
        return revision + 1

    def request_pause(self, session_id, revision):
        request_id = new_id()
        with self.transaction():
            session = self._session(session_id, revision)
            if session["state"] not in ("RUNNING", "READY"):
                raise SessionConflict("Estado nao permite pedido de pausa")
            self.db.execute(
                """INSERT INTO control_requests
                (request_id,session_id,action) VALUES (?,?,'PAUSE')""",
                (request_id, session_id),
            )
            self._set(session_id, "PAUSE_REQUESTED")
            self._event(session_id, "PAUSE_REQUESTED", {"request_id": request_id})
        return {"request_id": request_id, "revision": revision + 1}

    def dispatch(self, session_id, revision, task_id):
        attempt_id = new_id()
        with self.transaction():
            session = self._session(session_id, revision)
            pending = self.db.execute(
                """SELECT COUNT(*) FROM control_requests
                WHERE session_id=? AND status='REQUESTED'""",
                (session_id,),
            ).fetchone()[0]
            active = self.db.execute(
                """SELECT COUNT(*) FROM attempts
                WHERE session_id=? AND status IN ('RUNNING','INDETERMINATE')""",
                (session_id,),
            ).fetchone()[0]
            if session["state"] != "RUNNING" or pending or active:
                raise SessionConflict("Despacho bloqueado")

            task = self.db.execute(
                "SELECT * FROM tasks WHERE task_id=?", (task_id,)
            ).fetchone()
            if (
                task is None
                or task["project_id"] != session["project_id"]
                or task["status"] != "PENDING"
            ):
                raise SessionConflict("Tarefa nao apta para esta sessao")

            self.db.execute(
                """INSERT INTO attempts
                (attempt_id,project_id,session_id,task_id,status)
                VALUES (?,?,?,?,'RUNNING')""",
                (attempt_id, session["project_id"], session_id, task_id),
            )
            self.db.execute(
                "UPDATE tasks SET status='RUNNING' WHERE task_id=?", (task_id,)
            )
            self._set(session_id, "RUNNING")
            self._event(session_id, "ATTEMPT_DISPATCHED", {
                "task_id": task_id, "attempt_id": attempt_id,
            })
        return {"attempt_id": attempt_id, "revision": revision + 1}

    def confirm_pause(self, session_id, revision, request_id, checkpoint_id, store):
        if store.db is not self.db:
            raise SessionConflict("CheckpointStore deve usar a mesma conexao")
        with self.transaction():
            session = self._session(session_id, revision)
            request = self.db.execute(
                """SELECT * FROM control_requests
                WHERE request_id=? AND session_id=?""",
                (request_id, session_id),
            ).fetchone()
            if (
                session["state"] != "PAUSE_REQUESTED"
                or request is None
                or request["action"] != "PAUSE"
                or request["status"] != "REQUESTED"
            ):
                raise SessionConflict("Pedido de pausa invalido")

            for table, condition in (
                ("attempts", "status IN ('RUNNING','INDETERMINATE')"),
                ("operations", "status IN ('STARTED','INDETERMINATE')"),
                ("checkpoints", "status IN ('PREPARING','NEEDS_RECOVERY')"),
            ):
                count = self.db.execute(
                    f"""SELECT COUNT(*) FROM {table}
                    WHERE project_id=? AND session_id=? AND {condition}""",
                    (session["project_id"], session_id),
                ).fetchone()[0]
                if count:
                    raise SessionConflict("Sessao ainda nao esta em ponto seguro")

            checkpoint = self.db.execute(
                """SELECT * FROM checkpoints WHERE checkpoint_id=?
                AND project_id=? AND session_id=? AND status='COMMITTED'""",
                (checkpoint_id, session["project_id"], session_id),
            ).fetchone()
            if checkpoint is None:
                raise SessionConflict("Checkpoint confirmado nao pertence a sessao")

            latest = store.latest(
                session["project_id"], session_id, checkpoint["task_id"]
            )
            if latest is None or latest["checkpoint_id"] != checkpoint_id:
                raise SessionConflict("Checkpoint nao e o mais recente da tarefa")

            store.verify(checkpoint_id)
            self.db.execute(
                """UPDATE control_requests SET status='APPLIED',
                completed_at=CURRENT_TIMESTAMP WHERE request_id=?""",
                (request_id,),
            )
            self._set(session_id, "PAUSED")
            self._event(session_id, "PAUSED", {
                "request_id": request_id, "checkpoint_id": checkpoint_id,
            })
        return revision + 1
