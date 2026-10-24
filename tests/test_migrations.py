import shutil
import sqlite3
from pathlib import Path

import pytest

from pcsala_agent.checkpoints import CheckpointStore
from pcsala_agent.database import connect, initialize
from pcsala_agent.migrations import migrate, MigrationError

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"

def make_v1(path):
    db = connect(path)
    initialize(db, MIGRATIONS / "001_checkpoints.sql")
    return db

def test_cria_esquema_e_repeticao_segura(tmp_path):
    path = tmp_path / "state.sqlite"
    first = migrate(path)
    assert first["version"] == 5
    assert first["applied"] == [1, 2, 3, 4, 5]
    second = migrate(path)
    assert second == {"version": 5, "applied": [], "backup": None}
    with connect(path) as db:
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        tables = {
            row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {
            "projects", "sessions", "tasks", "attempts",
            "control_requests", "audit_events", "execution_acceptances",
        } <= tables

def test_preserva_checkpoint_e_cria_backup(tmp_path):
    path = tmp_path / "state.sqlite"
    db = make_v1(path)
    store = CheckpointStore(db, tmp_path / "artifacts")
    cid = store.prepare("p", "s", "t")
    store.add_artifact(cid, b"preservar")
    store.commit(cid)
    db.close()

    result = migrate(path)
    assert result["applied"] == [2, 3, 4, 5]
    backup_path = Path(result["backup"])
    assert backup_path.is_file()

    db = connect(path)
    try:
        store = CheckpointStore(db, tmp_path / "artifacts")
        assert store.latest("p", "s", "t")["checkpoint_id"] == cid
    finally:
        db.close()

    backup = connect(backup_path)
    try:
        versions = [
            row[0] for row in backup.execute("SELECT version FROM schema_migrations")
        ]
        assert versions == [1]
        assert backup.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0] == 1
    finally:
        backup.close()

def test_recusa_versao_desconhecida(tmp_path):
    path = tmp_path / "state.sqlite"
    db = make_v1(path)
    with db:
        db.execute("INSERT INTO schema_migrations(version) VALUES (99)")
    db.close()
    with pytest.raises(MigrationError):
        migrate(path)

def test_falha_reverte_migracao_pendente(tmp_path):
    path = tmp_path / "state.sqlite"
    db = make_v1(path)
    db.close()

    directory = tmp_path / "migration-scripts"
    shutil.copytree(MIGRATIONS, directory)
    (directory / "002_sessions.sql").write_text(
        "BEGIN IMMEDIATE;\n"
        "CREATE TABLE nao_deve_persistir (id INTEGER);\n"
        "INSERT INTO tabela_inexistente VALUES (1);\n"
        "COMMIT;\n",
        encoding="utf-8",
    )
    with pytest.raises(sqlite3.Error):
        migrate(path, directory)

    db = connect(path)
    try:
        assert db.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='nao_deve_persistir'"
        ).fetchone()[0] == 0
        assert [
            row[0] for row in db.execute("SELECT version FROM schema_migrations")
        ] == [1]
    finally:
        db.close()

def test_tentativa_nao_pode_cruzar_projetos(tmp_path):
    path = tmp_path / "state.sqlite"
    migrate(path)
    db = connect(path)
    try:
        with db:
            db.executemany(
                "INSERT INTO projects(project_id,name,authorized_root) VALUES (?,?,?)",
                [("p1", "Primeiro", "/autorizado/p1"),
                 ("p2", "Segundo", "/autorizado/p2")],
            )
            db.execute(
                "INSERT INTO sessions(session_id,project_id) VALUES ('s1','p1')"
            )
            db.execute(
                """INSERT INTO tasks
                (task_id,project_id,title,acceptance_criteria)
                VALUES ('t2','p2','Teste','Criterio explicito')"""
            )
        with pytest.raises(sqlite3.IntegrityError):
            with db:
                db.execute(
                    """INSERT INTO attempts
                    (attempt_id,project_id,session_id,task_id)
                    VALUES ('a1','p1','s1','t2')"""
                )
    finally:
        db.close()
