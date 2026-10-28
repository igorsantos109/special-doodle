import shutil
import sqlite3
from pathlib import Path


class MigrationError(Exception):
    pass


def _known_versions(migrations_dir):
    versions = []
    for f in sorted(migrations_dir.glob("[0-9]*_*.sql")):
        try:
            versions.append(int(f.stem.split("_")[0]))
        except ValueError:
            continue
    return versions


def _current_version(conn):
    return conn.execute(
        "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
    ).fetchone()[0]


def _create_backup(database_path):
    backup_path = database_path.with_suffix(database_path.suffix + ".bak")
    shutil.copy2(database_path, backup_path)
    return str(backup_path)


def migrate(database_path, migrations_dir=None):
    database_path = Path(database_path)
    if migrations_dir is None:
        migrations_dir = Path(__file__).resolve().parents[2] / "migrations"
    migrations_dir = Path(migrations_dir)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(database_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        has_table = conn.execute(
            """SELECT name FROM sqlite_master
            WHERE type='table' AND name='schema_migrations'"""
        ).fetchone() is not None
        if has_table:
            current = _current_version(conn)
        else:
            current = 0
        known = _known_versions(migrations_dir)
        if current not in known and current != 0:
            raise MigrationError(f"versao desconhecida {current}")
        applied = []
        backup_path = None
        pending = [v for v in known if v > current]
        if pending:
            backup_path = _create_backup(database_path)
            for version in sorted(pending):
                matches = sorted(
                    migrations_dir.glob(f"{version:03d}_*.sql")
                )
                if not matches:
                    matches = sorted(
                        migrations_dir.glob(f"{version}_*.sql")
                    )
                if not matches:
                    conn.rollback()
                    shutil.copy2(backup_path, database_path)
                    raise MigrationError(f"Sem migration para versão {version}")
                script = matches[0]
                try:
                    conn.executescript(script.read_text(encoding="utf-8"))
                    conn.commit()
                except sqlite3.Error:
                    conn.rollback()
                    if backup_path:
                        shutil.copy2(backup_path, database_path)
                    raise
                applied.append(version)
        return {
            "version": current if not applied else applied[-1],
            "applied": applied,
            "backup": backup_path,
        }
    finally:
        conn.close()
