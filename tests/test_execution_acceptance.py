import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from pcsala_agent.database import connect
from pcsala_agent.execution_contract import ExecutionRequest
from pcsala_agent.execution_acceptance import (
    ExecutionAlreadyAccepted, accept_execution,
)
from pcsala_agent.execution_eligibility import ExecutionNotEligible
from pcsala_agent.migrations import migrate
from pcsala_agent.sessions import SessionController

@pytest.fixture
def environment(tmp_path):
    path = tmp_path / "state.sqlite"
    migrate(path)
    db = connect(path)
    try:
        with db:
            db.execute(
                """INSERT INTO projects(project_id,name,authorized_root)
                VALUES ('p','Teste','/referencia')"""
            )
            db.execute(
                """INSERT INTO sessions(session_id,project_id,state,revision)
                VALUES ('s','p','RUNNING',7)"""
            )
            db.execute(
                """INSERT INTO tasks
                (task_id,project_id,title,acceptance_criteria,status)
                VALUES ('t','p','Teste','Criterio','RUNNING')"""
            )
            db.execute(
                """INSERT INTO attempts
                (attempt_id,project_id,session_id,task_id,status)
                VALUES ('a','p','s','t','RUNNING')"""
            )
    finally:
        db.close()
    return path

def request():
    return ExecutionRequest(
        project_id="p", session_id="s", task_id="t",
        attempt_id="a", profile="diagnostic-v1",
    )

def test_acceptance_and_audit(environment):
    db = connect(environment)
    try:
        result = accept_execution(db, request())
        assert result.session_revision == 7
        row = db.execute("SELECT * FROM execution_acceptances").fetchone()
        assert row["execution_id"] == result.execution_id
        assert row["status"] == "ACCEPTED"
        assert ExecutionRequest.model_validate_json(row["request_json"]) == request()
        assert db.execute(
            "SELECT COUNT(*) FROM audit_events WHERE event_type='EXECUTION_ACCEPTED'"
        ).fetchone()[0] == 1
        assert not db.in_transaction
    finally:
        db.close()

def test_reopen_does_not_allow_replay(environment):
    db = connect(environment)
    first = accept_execution(db, request())
    db.close()
    db = connect(environment)
    try:
        with pytest.raises(ExecutionAlreadyAccepted):
            accept_execution(db, request())
        assert db.execute(
            "SELECT execution_id FROM execution_acceptances"
        ).fetchone()[0] == first.execution_id
    finally:
        db.close()

def test_database_unique_constraint(environment):
    db = connect(environment)
    try:
        accept_execution(db, request())
        with pytest.raises(sqlite3.IntegrityError):
            with db:
                db.execute(
                    """INSERT INTO execution_acceptances
                    (execution_id,attempt_id,request_json,session_revision)
                    VALUES ('duplicate','a','{}',7)"""
                )
    finally:
        db.close()

def test_concurrent_acceptance(environment):
    barrier = Barrier(2)
    def worker():
        db = connect(environment)
        try:
            barrier.wait(timeout=5)
            try:
                accept_execution(db, request())
                return "accepted"
            except ExecutionAlreadyAccepted:
                return "duplicate"
        finally:
            db.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: worker(), range(2)))
    assert sorted(results) == ["accepted", "duplicate"]

def test_pause_before_acceptance(environment):
    db = connect(environment)
    try:
        SessionController(db).request_pause("s", 7)
        with pytest.raises(ExecutionNotEligible):
            accept_execution(db, request())
        assert db.execute(
            "SELECT COUNT(*) FROM execution_acceptances"
        ).fetchone()[0] == 0
    finally:
        db.close()

def test_acceptance_before_pause_is_preserved(environment):
    db = connect(environment)
    try:
        accepted = accept_execution(db, request())
        SessionController(db).request_pause("s", 7)
        assert db.execute(
            "SELECT execution_id FROM execution_acceptances"
        ).fetchone()[0] == accepted.execution_id
        assert db.execute(
            "SELECT state FROM sessions"
        ).fetchone()[0] == "PAUSE_REQUESTED"
    finally:
        db.close()

@pytest.mark.parametrize("action", ["PAUSE", "DRAIN", "RESUME"])
def test_pending_control_blocks(environment, action):
    db = connect(environment)
    try:
        with db:
            db.execute(
                """INSERT INTO control_requests
                (request_id,session_id,action) VALUES ('r','s',?)""",
                (action,),
            )
        with pytest.raises(ExecutionNotEligible):
            accept_execution(db, request())
    finally:
        db.close()

def test_audit_failure_rolls_back_acceptance(environment):
    db = connect(environment)
    try:
        db.executescript("""
        CREATE TRIGGER reject_acceptance_audit
        BEFORE INSERT ON audit_events
        WHEN NEW.event_type='EXECUTION_ACCEPTED'
        BEGIN SELECT RAISE(ABORT, 'audit failure'); END;
        """)
        with pytest.raises(sqlite3.IntegrityError):
            accept_execution(db, request())
        assert not db.in_transaction
        assert db.execute(
            "SELECT COUNT(*) FROM execution_acceptances"
        ).fetchone()[0] == 0
    finally:
        db.close()

def test_external_transaction_preserved(environment):
    db = connect(environment)
    try:
        db.execute("BEGIN")
        db.execute("UPDATE sessions SET revision=8")
        with pytest.raises(ExecutionNotEligible):
            accept_execution(db, request())
        assert db.in_transaction
        assert db.execute("SELECT revision FROM sessions").fetchone()[0] == 8
        db.rollback()
    finally:
        db.close()

def test_upgrade_from_v2_preserves_data(tmp_path):
    path = tmp_path / "v2.sqlite"
    scripts = Path(__file__).resolve().parents[1] / "migrations"
    db = connect(path)
    try:
        for name in ("001_checkpoints.sql", "002_sessions.sql"):
            db.executescript((scripts / name).read_text())
        with db:
            db.execute(
                """INSERT INTO projects(project_id,name,authorized_root)
                VALUES ('keep','Preservar','/referencia')"""
            )
    finally:
        db.close()

    result = migrate(path)
    assert result["applied"] == [3, 4, 5]
    assert Path(result["backup"]).is_file()
    db = connect(path)
    try:
        assert db.execute("SELECT project_id FROM projects").fetchone()[0] == "keep"
    finally:
        db.close()
    backup = connect(result["backup"])
    try:
        assert [r[0] for r in backup.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        )] == [1, 2]
    finally:
        backup.close()
