import hashlib
import os
from uuid import uuid4

class RecoveryRequired(RuntimeError):
    pass

def new_id():
    return str(uuid4())

class CheckpointStore:
    """Uso inicial exclusivo: sem escritores concorrentes ou codigo nao confiavel."""

    def __init__(self, db, artifact_root):
        self.db = db
        self.root = artifact_root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def prepare(self, project_id, session_id, task_id):
        checkpoint_id = new_id()
        with self.db:
            self.db.execute(
                """INSERT INTO checkpoints
                (checkpoint_id, project_id, session_id, task_id, status)
                VALUES (?, ?, ?, ?, 'PREPARING')""",
                (checkpoint_id, project_id, session_id, task_id),
            )
        return checkpoint_id

    def _preparing(self, checkpoint_id):
        row = self.db.execute(
            "SELECT status FROM checkpoints WHERE checkpoint_id=?",
            (checkpoint_id,),
        ).fetchone()
        if row is None or row["status"] != "PREPARING":
            raise RecoveryRequired("Checkpoint inexistente ou nao esta PREPARING")

    def add_artifact(self, checkpoint_id, content):
        self._preparing(checkpoint_id)
        artifact_id = new_id()
        relative_path = artifact_id + ".bin"
        path = self.root / relative_path
        with path.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        with self.db:
            self._preparing(checkpoint_id)
            self.db.execute(
                "INSERT INTO artifacts VALUES (?, ?, ?, ?, ?)",
                (
                    artifact_id, checkpoint_id, relative_path,
                    hashlib.sha256(content).hexdigest(), len(content),
                ),
            )
        return path

    def verify(self, checkpoint_id):
        rows = self.db.execute(
            "SELECT * FROM artifacts WHERE checkpoint_id=?",
            (checkpoint_id,),
        ).fetchall()
        if not rows:
            raise RecoveryRequired("Checkpoint sem artefatos")
        for row in rows:
            path = self.root / row["relative_path"]
            if path.is_symlink() or path.resolve().parent != self.root:
                raise RecoveryRequired("Caminho de artefato invalido")
            try:
                data = path.read_bytes()
            except OSError as error:
                raise RecoveryRequired("Artefato indisponivel") from error
            if (
                len(data) != row["size_bytes"]
                or hashlib.sha256(data).hexdigest() != row["sha256"]
            ):
                raise RecoveryRequired("Artefato alterado")

    def commit(self, checkpoint_id):
        with self.db:
            self._preparing(checkpoint_id)
            self.verify(checkpoint_id)
            self.db.execute(
                """UPDATE checkpoints
                SET status='COMMITTED', committed_at=CURRENT_TIMESTAMP
                WHERE checkpoint_id=?""",
                (checkpoint_id,),
            )

    def latest(self, project_id, session_id, task_id):
        row = self.db.execute(
            """SELECT * FROM checkpoints
            WHERE project_id=? AND session_id=? AND task_id=?
              AND status='COMMITTED'
            ORDER BY seq DESC LIMIT 1""",
            (project_id, session_id, task_id),
        ).fetchone()
        if row is not None:
            self.verify(row["checkpoint_id"])
            return dict(row)
        return None

    def recover(self, project_id, session_id):
        """Executar apenas com a sessao parada e sem escritor ativo."""
        with self.db:
            checkpoints = self.db.execute(
                """UPDATE checkpoints SET status='NEEDS_RECOVERY'
                WHERE project_id=? AND session_id=? AND status='PREPARING'""",
                (project_id, session_id),
            ).rowcount
            operations = self.db.execute(
                """UPDATE operations SET status='INDETERMINATE'
                WHERE project_id=? AND session_id=? AND status='STARTED'""",
                (project_id, session_id),
            ).rowcount
        return {"checkpoints": checkpoints, "operations": operations}
