import hashlib
import os
from datetime import UTC, datetime

CHECKPOINT_STATES = ("PREPARING", "COMMITTED", "NEEDS_RECOVERY")
OPERATION_STATES = (
    "NOT_STARTED", "STARTED", "COMPLETED", "FAILED", "INDETERMINATE",
)


class RecoveryRequired(Exception):
    pass


def _now():
    return datetime.now(UTC).isoformat(timespec="seconds")


class CheckpointStore:
    def __init__(self, db, root):
        self.db = db
        self.root = root

    def prepare(self, project_id, session_id, task_id):
        checkpoint_id = hashlib.sha256(
            f"{project_id}/{session_id}/{task_id}/{_now()}/{os.urandom(8).hex()}".encode()
        ).hexdigest()
        with self.db:
            self.db.execute(
                """INSERT INTO checkpoints
                (checkpoint_id, project_id, session_id, task_id, status)
                VALUES (?, ?, ?, ?, 'PREPARING')""",
                (checkpoint_id, project_id, session_id, task_id),
            )
        return checkpoint_id

    def add_artifact(self, checkpoint_id, data):
        rel = self._relative_path(checkpoint_id)
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        with self.db:
            self.db.execute(
                """INSERT INTO artifacts
                (artifact_id, checkpoint_id, relative_path, sha256, size_bytes)
                VALUES (?, ?, ?, ?, ?)""",
                (
                    checkpoint_id + ":" + rel,
                    checkpoint_id,
                    rel,
                    digest,
                    len(data),
                ),
            )
        return path

    def _relative_path(self, checkpoint_id):
        return f"{checkpoint_id}.bin"

    def commit(self, checkpoint_id):
        row = self.db.execute(
            "SELECT artifact_id FROM artifacts WHERE checkpoint_id=? AND sha256 IS NOT NULL",
            (checkpoint_id,),
        ).fetchone()
        if row is None:
            raise RecoveryRequired("sem artefato")
        artifacts = self.db.execute(
            "SELECT relative_path, sha256 FROM artifacts WHERE checkpoint_id=?",
            (checkpoint_id,),
        ).fetchall()
        for art in artifacts:
            path = self.root / art["relative_path"]
            if not path.exists():
                raise RecoveryRequired(f"artefato ausente {art['relative_path']}")
            if hashlib.sha256(path.read_bytes()).hexdigest() != art["sha256"]:
                raise RecoveryRequired(f"artefato alterado {art['relative_path']}")
        with self.db:
            self.db.execute(
                """UPDATE checkpoints SET status='COMMITTED',
                committed_at=? WHERE checkpoint_id=?""",
                (_now(), checkpoint_id),
            )

    def latest(self, project_id, session_id, task_id):
        row = self.db.execute(
            """SELECT checkpoint_id FROM checkpoints
            WHERE project_id=? AND session_id=? AND task_id=?
            AND status='COMMITTED'
            ORDER BY seq DESC LIMIT 1""",
            (project_id, session_id, task_id),
        ).fetchone()
        if row is None:
            return None
        checkpoint_id = row["checkpoint_id"]
        artifacts = self.db.execute(
            "SELECT relative_path, sha256 FROM artifacts WHERE checkpoint_id=?",
            (checkpoint_id,),
        ).fetchall()
        for art in artifacts:
            path = self.root / art["relative_path"]
            if not path.exists():
                raise RecoveryRequired("artefato ausente")
            if hashlib.sha256(path.read_bytes()).hexdigest() != art["sha256"]:
                raise RecoveryRequired("artefato alterado")
        return {"checkpoint_id": checkpoint_id}

    def recover(self, project_id, session_id):
        checkpoints_marked = 0
        with self.db:
            rows = self.db.execute(
                """SELECT checkpoint_id FROM checkpoints
                WHERE project_id=? AND session_id=?
                AND status='PREPARING'""",
                (project_id, session_id),
            ).fetchall()
            for row in rows:
                self.db.execute(
                    """UPDATE checkpoints SET status='NEEDS_RECOVERY'
                    WHERE checkpoint_id=?""",
                    (row["checkpoint_id"],),
                )
            checkpoints_marked = len(rows)
            op_rows = self.db.execute(
                """SELECT operation_id FROM operations
                WHERE project_id=? AND session_id=?
                AND status='STARTED'""",
                (project_id, session_id),
            ).fetchall()
            for row in op_rows:
                self.db.execute(
                    """UPDATE operations SET status='INDETERMINATE',
                    result_reference=NULL WHERE operation_id=?""",
                    (row["operation_id"],),
                )
            operations_marked = len(op_rows)
        return {"checkpoints": checkpoints_marked, "operations": operations_marked}
