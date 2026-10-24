import json
from pathlib import Path

from .database import connect
from .locking import database_lock
from .migrations import migrate


def _db(database):
    return connect(database)


def enqueue(database, prompt, *, profile="gpu-triage-v1", idempotency_key=None):
    database = Path(database).resolve()
    migrate(database)
    with database_lock(database):
        db = _db(database)
        try:
            if idempotency_key is not None:
                existing = db.execute(
                    "SELECT id, prompt, status, inference_response"
                    " FROM task_queue WHERE idempotency_key=?",
                    (idempotency_key,),
                ).fetchone()
                if existing is not None:
                    if existing["prompt"] != prompt:
                        raise ValueError(
                            "Chave de idempotencia ja usada com prompt diferente"
                        )
                    return {
                        "id": existing["id"],
                        "status": existing["status"],
                        "inference_response": (
                            existing["inference_response"] or ""
                        ),
                    }

            if idempotency_key is not None:
                db.execute(
                    "INSERT INTO task_queue (idempotency_key, profile, prompt)"
                    " VALUES (?,?,?)",
                    (idempotency_key, profile, prompt),
                )
            else:
                db.execute(
                    "INSERT INTO task_queue (profile, prompt) VALUES (?,?)",
                    (profile, prompt),
                )
            db.commit()
            row = db.execute(
                "SELECT id, attempt_id, status FROM task_queue"
                " WHERE id = last_insert_rowid()"
            ).fetchone()
            return {
                "id": row["id"],
                "attempt_id": row["attempt_id"],
                "status": row["status"],
            }
        finally:
            db.close()


def reserve(database):
    database = Path(database).resolve()
    migrate(database)
    with database_lock(database):
        db = _db(database)
        try:
            row = db.execute(
                "SELECT id FROM task_queue WHERE status='QUEUED'"
                " ORDER BY id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            task_id = row["id"]
            db.execute(
                """UPDATE task_queue SET status='RESERVED',
                   reserved_at=strftime('%Y-%m-%dT%H:%M:%S','now')
                   WHERE id=? AND status='QUEUED'""",
                (task_id,),
            )
            if db.total_changes == 0:
                db.rollback()
                return None
            db.commit()
            row = db.execute(
                "SELECT * FROM task_queue WHERE id=?", (task_id,)
            ).fetchone()
            return dict(row)
        finally:
            db.close()


def update(database, task_id, *, inference_response="", inference_id="",
           inference_model="", inference_status="", error=""):
    database = Path(database).resolve()
    with database_lock(database):
        db = _db(database)
        try:
            status = "FAILED" if error else "COMPLETED"
            db.execute(
                """UPDATE task_queue
                   SET status=?,
                       inference_response=?,
                       inference_id=?,
                       inference_model=?,
                       inference_status=?,
                       error=?,
                       completed_at=strftime('%Y-%m-%dT%H:%M:%S','now')
                   WHERE id=?""",
                (status, inference_response, inference_id,
                 inference_model, inference_status, error, task_id),
            )
            db.commit()
        finally:
            db.close()


def list_tasks(database, *, status=None, limit=20):
    database = Path(database).resolve()
    with database_lock(database):
        db = _db(database)
        try:
            if status:
                rows = db.execute(
                    "SELECT * FROM task_queue WHERE status=? ORDER BY id DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM task_queue ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            db.close()


def get(database, task_id):
    database = Path(database).resolve()
    with database_lock(database):
        db = _db(database)
        try:
            row = db.execute(
                "SELECT * FROM task_queue WHERE id=?", (task_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            db.close()


def cancel(database, task_id):
    database = Path(database).resolve()
    with database_lock(database):
        db = _db(database)
        try:
            db.execute(
                """UPDATE task_queue SET status='CANCELLED',
                   completed_at=strftime('%Y-%m-%dT%H:%M:%S','now')
                   WHERE id=? AND status='QUEUED'""",
                (task_id,),
            )
            db.commit()
            row = db.execute(
                "SELECT COUNT(*) AS cnt FROM task_queue"
                " WHERE id=? AND status='CANCELLED'",
                (task_id,),
            ).fetchone()
            return row["cnt"] > 0
        finally:
            db.close()


def reconcile(database, task_id, *, graph_root, graph_attempt_id):
    """Reconcilia resultado do grafo confirmado na fila sem re-inferir."""
    from .checkpoints import CheckpointStore
    from .database import connect as db_connect

    graph_root = Path(graph_root).resolve()
    gdb = db_connect(graph_root / "state.sqlite")
    try:
        store = CheckpointStore(gdb, graph_root / "artifacts")
        task_session = f"queue-{task_id}"
        graph_task_id = f"task-{task_id}"
        latest = store.latest("default", task_session, graph_task_id)
        if latest is None:
            return False
        artifact_row = gdb.execute(
            "SELECT relative_path FROM artifacts WHERE checkpoint_id=?",
            (latest["checkpoint_id"],),
        ).fetchone()
        if artifact_row is None:
            return False
        artifact = json.loads(
            (store.root / artifact_row["relative_path"]).read_bytes()
        )
        if artifact.get("step") not in ("concluido", "falha"):
            return False
        update(
            database, task_id,
            inference_response=artifact.get("inference_response", ""),
            inference_id=artifact.get("inference_id", ""),
            inference_model=artifact.get("inference_model", ""),
            inference_status=artifact.get("inference_status", ""),
            error=artifact.get("error", ""),
        )
        return True
    finally:
        gdb.close()