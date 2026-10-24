from pathlib import Path
from uuid import uuid4

from .database import connect
from .locking import database_lock

class MigrationError(RuntimeError):
    pass

MIGRATIONS = (
    (1, "001_checkpoints.sql"),
    (2, "002_sessions.sql"),
    (3, "003_execution_acceptances.sql"),
    (4, "004_task_queue.sql"),
    (5, "005_model_operations.sql"),
)

def migrate(database_path, migrations_dir=None):
    """Migracao local exclusiva. Backups sao preservados, nunca apagados."""
    path = Path(database_path).resolve()
    directory = (
        Path(migrations_dir)
        if migrations_dir is not None
        else Path(__file__).resolve().parents[2] / "migrations"
    )

    scripts = {}
    for version, filename in MIGRATIONS:
        scripts[version] = (directory / filename).read_text(encoding="utf-8")

    path.parent.mkdir(parents=True, exist_ok=True)
    with database_lock(path):
        existed = path.exists()
        db = connect(path)
        backup_path = None
        try:
            tables = {
                row[0] for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if "schema_migrations" not in tables:
                if tables:
                    raise MigrationError("Banco existente sem esquema reconhecido")
                applied = []
            else:
                applied = [
                    row[0] for row in db.execute(
                        "SELECT version FROM schema_migrations ORDER BY version"
                    )
                ]
                known = [item[0] for item in MIGRATIONS]
                if applied != known[:len(applied)] or not applied:
                    raise MigrationError("Sequencia de versoes desconhecida")

            pending = [
                version for version, _ in MIGRATIONS if version not in applied
            ]
            if not pending:
                return {"version": applied[-1], "applied": [], "backup": None}

            integrity = [row[0] for row in db.execute("PRAGMA integrity_check")]
            if integrity != ["ok"]:
                raise MigrationError("Integridade do banco nao confirmada")

            if existed:
                backup_path = path.with_name(
                    path.name + ".backup-" + str(uuid4()) + ".sqlite"
                )
                backup = connect(backup_path)
                try:
                    db.backup(backup)
                finally:
                    backup.close()

            completed = []
            for version in pending:
                try:
                    db.executescript(scripts[version])
                    if db.in_transaction:
                        raise MigrationError("Script deixou transacao aberta")
                    completed.append(version)
                except BaseException:
                    db.rollback()
                    raise

            return {
                "version": completed[-1],
                "applied": completed,
                "backup": str(backup_path) if backup_path else None,
            }
        finally:
            db.close()
