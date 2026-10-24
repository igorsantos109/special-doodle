import json
from pathlib import Path

from .checkpoints import CheckpointStore, new_id
from .database import connect
from .locking import database_lock
from .sessions import SessionController, SessionConflict

class ShutdownController:
    """Encerramento logico de uma sessao simulada de tarefa unica."""

    def __init__(self, root):
        self.root = Path(root).resolve()
        self.database = self.root / "state.sqlite"
        if not self.database.is_file():
            raise SessionConflict("Banco inexistente")

    def request(self, session_id, revision):
        db = connect(self.database)
        try:
            controller = SessionController(db)
            request_id = new_id()
            with controller.transaction():
                session = controller._session(session_id, revision)
                if session["state"] not in ("RUNNING", "READY", "PAUSED"):
                    raise SessionConflict("Estado nao permite encerramento")
                pending = db.execute(
                    """SELECT COUNT(*) FROM control_requests
                    WHERE session_id=? AND status='REQUESTED'""",
                    (session_id,),
                ).fetchone()[0]
                if pending:
                    raise SessionConflict("Existe pedido de controle pendente")
                db.execute(
                    """INSERT INTO control_requests
                    (request_id,session_id,action) VALUES (?,?,'DRAIN')""",
                    (request_id, session_id),
                )
                controller._set(session_id, "DRAINING")
                controller._event(session_id, "DRAIN_REQUESTED", {
                    "request_id": request_id,
                })
            return {"request_id": request_id, "revision": revision + 1}
        finally:
            db.close()

    def _safe(self, db, session, checkpoint_id):
        for table, condition in (
            ("attempts", "status IN ('RUNNING','INDETERMINATE')"),
            ("operations", "status IN ('STARTED','INDETERMINATE')"),
            ("checkpoints", "status IN ('PREPARING','NEEDS_RECOVERY')"),
        ):
            count = db.execute(
                f"""SELECT COUNT(*) FROM {table}
                WHERE project_id=? AND session_id=? AND {condition}""",
                (session["project_id"], session["session_id"]),
            ).fetchone()[0]
            if count:
                raise SessionConflict("Sessao ainda nao esta em ponto seguro")

        tasks = db.execute(
            """SELECT COUNT(DISTINCT task_id) FROM checkpoints
            WHERE project_id=? AND session_id=?""",
            (session["project_id"], session["session_id"]),
        ).fetchone()[0]
        if tasks != 1:
            raise SessionConflict(
                "Encerramento atual exige manifesto de uma unica tarefa"
            )

        row = db.execute(
            """SELECT * FROM checkpoints WHERE checkpoint_id=?
            AND project_id=? AND session_id=? AND status='COMMITTED'""",
            (checkpoint_id, session["project_id"], session["session_id"]),
        ).fetchone()
        if row is None:
            raise SessionConflict("Checkpoint nao pertence a sessao")
        store = CheckpointStore(db, self.root / "artifacts")
        latest = store.latest(
            session["project_id"], session["session_id"], row["task_id"]
        )
        if latest is None or latest["checkpoint_id"] != checkpoint_id:
            raise SessionConflict("Checkpoint nao e o mais recente da tarefa")

    def _request(self, db, session_id, request_id):
        request = db.execute(
            """SELECT * FROM control_requests
            WHERE request_id=? AND session_id=?
            AND action='DRAIN' AND status='REQUESTED'""",
            (request_id, session_id),
        ).fetchone()
        if request is None:
            raise SessionConflict("Pedido de encerramento invalido")

    def prepare(self, session_id, revision, request_id, checkpoint_id):
        with database_lock(self.root / "executor-owner"):
            db = connect(self.database)
            try:
                controller = SessionController(db)
                with controller.transaction():
                    session = controller._session(session_id, revision)
                    if session["state"] != "DRAINING":
                        raise SessionConflict("Sessao nao esta DRAINING")
                    self._request(db, session_id, request_id)
                    self._safe(db, session, checkpoint_id)
                    db.execute(
                        """INSERT INTO audit_events
                        (event_id,session_id,event_type,details_json)
                        VALUES (?,?,'SHUTDOWN_CHECKPOINTED',?)""",
                        (
                            request_id + ":checkpoint", session_id,
                            json.dumps({"checkpoint_id": checkpoint_id}),
                        ),
                    )
                    controller._set(session_id, "CHECKPOINTING")
                return revision + 1
            finally:
                db.close()

    def confirm(self, session_id, revision, request_id):
        with database_lock(self.root / "executor-owner"):
            db = connect(self.database)
            try:
                controller = SessionController(db)
                with controller.transaction():
                    session = controller._session(session_id, revision)
                    if session["state"] != "CHECKPOINTING":
                        raise SessionConflict("Sessao nao esta CHECKPOINTING")
                    self._request(db, session_id, request_id)
                    event = db.execute(
                        """SELECT details_json FROM audit_events
                        WHERE event_id=? AND session_id=?
                        AND event_type='SHUTDOWN_CHECKPOINTED'""",
                        (request_id + ":checkpoint", session_id),
                    ).fetchone()
                    if event is None:
                        raise SessionConflict("Referencia de checkpoint ausente")
                    checkpoint_id = json.loads(event[0])["checkpoint_id"]
                    self._safe(db, session, checkpoint_id)
                    db.execute(
                        """UPDATE control_requests SET status='APPLIED',
                        completed_at=CURRENT_TIMESTAMP WHERE request_id=?""",
                        (request_id,),
                    )
                    controller._set(session_id, "STOPPED")
                    controller._event(session_id, "SESSION_STOPPED", {
                        "request_id": request_id,
                        "checkpoint_id": checkpoint_id,
                        "physical_shutdown": False,
                    })
                return revision + 1
            finally:
                db.close()
