import sqlite3
from pathlib import Path

def connect(path, *, check_same_thread=True):
    db = sqlite3.connect(
        Path(path), timeout=10, check_same_thread=check_same_thread
    )
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA synchronous=FULL")
    return db

def initialize(db, migration):
    db.executescript(Path(migration).read_text(encoding="utf-8"))
