import sqlite3
from pathlib import Path


def connect(path):
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def initialize(db, script_path):
    db.executescript(Path(script_path).read_text(encoding="utf-8"))
    db.commit()
