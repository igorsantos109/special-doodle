"""Armazenamento de medida de VRAM por modelo e contexto."""
import sqlite3
from datetime import UTC, datetime


def _now():
    return datetime.now(UTC).isoformat(timespec="seconds")


class ModelVramStore:
    def __init__(self, db):
        self.db = db
        self.db.row_factory = sqlite3.Row

    def record(self, model_id, context_size, vram_used_mb):
        self.db.execute(
            """INSERT INTO model_vram(model_id, context_size, vram_used_mb, measured_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(model_id, context_size) DO UPDATE SET
            vram_used_mb=excluded.vram_used_mb,
            measured_at=excluded.measured_at""",
            (model_id, context_size, vram_used_mb, _now()),
        )
        self.db.commit()

    def get(self, model_id, context_size=None):
        if context_size is not None:
            row = self.db.execute(
                """SELECT model_id, context_size, vram_used_mb, measured_at
                FROM model_vram WHERE model_id=? AND context_size=?
                ORDER BY measured_at DESC LIMIT 1""",
                (model_id, context_size),
            ).fetchone()
            return dict(row) if row else None
        rows = self.db.execute(
            """SELECT model_id, context_size, vram_used_mb, measured_at
            FROM model_vram WHERE model_id=? ORDER BY measured_at DESC""",
            (model_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def all(self):
        rows = self.db.execute(
            """SELECT model_id, context_size, vram_used_mb, measured_at
            FROM model_vram ORDER BY model_id, context_size"""
        ).fetchall()
        return [dict(row) for row in rows]
