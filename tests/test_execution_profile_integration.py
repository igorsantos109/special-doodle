import json
import sqlite3

import pytest

from pcsala_agent.database import connect
from pcsala_agent.execution_acceptance import (
    ExecutionAlreadyAccepted, accept_execution,
)
from pcsala_agent.execution_contract import ExecutionRequest
from pcsala_agent.execution_eligibility import (
    ExecutionNotEligible, check_execution_eligibility,
)
from pcsala_agent.execution_plan import build_execution_plan
from pcsala_agent.migrations import migrate
from pcsala_agent.sessions import SessionController


def make_request(profile):
    return ExecutionRequest(
        project_id="p", session_id="s", task_id="t",
        attempt_id="a", profile=profile,
    )


@pytest.fixture(params=["diagnostic-v1", "diagnostic-v2"])
def environment(tmp_path, request):
    path = tmp_path / "state.sqlite"
    migrate(path)
    connection = connect(path)
    try:
        with connection:
            connection.execute(
                """INSERT INTO projects(project_id,name,authorized_root)
                VALUES ('p','Teste','/referencia')"""
            )
            connection.execute(
                """INSERT INTO sessions(session_id,project_id,state,revision)
                VALUES ('s','p','RUNNING',7)"""
            )
            connection.execute(
                """INSERT INTO tasks
                (task_id,project_id,title,acceptance_criteria,status)
                VALUES ('t','p','Teste','Criterio','RUNNING')"""
            )
            connection.execute(
                """INSERT INTO attempts
                (attempt_id,project_id,session_id,task_id,status)
                VALUES ('a','p','s','t','RUNNING')"""
            )
    finally:
        connection.close()
    return path, make_request(request.param)


@pytest.fixture
def db(environment):
    connection = connect(environment[0])
    try:
        yield connection
    finally:
        connection.close()


def test_profile_eligibility_is_read_only(environment, db):
    req = environment[1]
    before = list(db.iterdump())
    changes = db.total_changes
    observation = check_execution_eligibility(db, req)
    assert observation.request == req
    assert observation.session_revision == 7
    assert db.total_changes == changes
    assert list(db.iterdump()) == before
    assert not db.in_transaction


def test_profile_acceptance_survives_reopen(environment):
    path, req = environment
    connection = connect(path)
    try:
        accepted = accept_execution(connection, req)
        assert not connection.in_transaction
    finally:
        connection.close()

    connection = connect(path)
    try:
        row = connection.execute(
            "SELECT * FROM execution_acceptances"
        ).fetchone()
        stored = ExecutionRequest.model_validate_json(row["request_json"])
        assert stored == req
        assert stored.profile == req.profile
        assert row["execution_id"] == accepted.execution_id
        assert row["session_revision"] == 7
        assert row["status"] == "ACCEPTED"

        events = connection.execute(
            """SELECT details_json FROM audit_events
            WHERE event_type='EXECUTION_ACCEPTED'"""
        ).fetchall()
        assert len(events) == 1
        details = json.loads(events[0]["details_json"])
        assert details["execution_id"] == accepted.execution_id
        assert details["attempt_id"] == "a"
        assert details["session_revision"] == 7

        with pytest.raises(ExecutionAlreadyAccepted):
            accept_execution(connection, req)
        assert not connection.in_transaction
    finally:
        connection.close()


def test_changing_profile_cannot_replace_acceptance(environment, db):
    req = environment[1]
    accepted = accept_execution(db, req)
    before = list(db.iterdump())
    other_profile = (
        "diagnostic-v2"
        if req.profile == "diagnostic-v1"
        else "diagnostic-v1"
    )

    with pytest.raises(ExecutionAlreadyAccepted):
        accept_execution(db, make_request(other_profile))

    assert not db.in_transaction
    assert list(db.iterdump()) == before
    row = db.execute(
        "SELECT execution_id,request_json FROM execution_acceptances"
    ).fetchone()
    assert row["execution_id"] == accepted.execution_id
    assert ExecutionRequest.model_validate_json(row["request_json"]) == req


@pytest.mark.parametrize("action", ["PAUSE", "DRAIN", "RESUME"])
def test_pending_control_blocks_both_profile_operations(
    environment, db, action,
):
    req = environment[1]
    with db:
        db.execute(
            """INSERT INTO control_requests
            (request_id,session_id,action)
            VALUES ('r','s',?)""",
            (action,),
        )
    before = list(db.iterdump())

    with pytest.raises(ExecutionNotEligible):
        check_execution_eligibility(db, req)
    assert not db.in_transaction

    with pytest.raises(ExecutionNotEligible):
        accept_execution(db, req)
    assert not db.in_transaction
    assert list(db.iterdump()) == before


def test_pause_blocks_both_profile_operations(environment, db):
    req = environment[1]
    SessionController(db).request_pause("s", 7)
    before = list(db.iterdump())

    with pytest.raises(ExecutionNotEligible):
        check_execution_eligibility(db, req)
    with pytest.raises(ExecutionNotEligible):
        accept_execution(db, req)

    assert not db.in_transaction
    assert list(db.iterdump()) == before


def test_audit_failure_preserves_database_for_each_profile(environment, db):
    req = environment[1]
    db.executescript("""
    CREATE TRIGGER reject_profile_acceptance_audit
    BEFORE INSERT ON audit_events
    WHEN NEW.event_type='EXECUTION_ACCEPTED'
    BEGIN SELECT RAISE(ABORT, 'profile audit failure'); END;
    """)
    before = list(db.iterdump())

    with pytest.raises(sqlite3.IntegrityError):
        accept_execution(db, req)

    assert not db.in_transaction
    assert list(db.iterdump()) == before
    assert db.execute(
        "SELECT COUNT(*) FROM execution_acceptances"
    ).fetchone()[0] == 0


def test_acceptance_does_not_make_plan_executable(environment, db):
    req = environment[1]
    before = build_execution_plan(req)
    accept_execution(db, req)
    after = build_execution_plan(req)

    assert after == before
    assert after.executable is True
    after.require_executable()

    if req.profile == "diagnostic-v2":
        assert after.argv == ()
        assert after.privileged_preparation_required is True


def test_profile_operations_do_not_launch_processes(
    environment, db, monkeypatch,
):
    import os
    import subprocess

    req = environment[1]

    def forbidden(*args, **kwargs):
        raise AssertionError("Processo iniciado durante consulta ou aceitacao")

    with monkeypatch.context() as patch:
        for name in ("run", "Popen", "call", "check_call", "check_output"):
            patch.setattr(subprocess, name, forbidden)
        patch.setattr(os, "system", forbidden)

        observation = check_execution_eligibility(db, req)
        accepted = accept_execution(db, req)
        plan = build_execution_plan(req)

    assert observation.request == req
    assert accepted.attempt_id == req.attempt_id
    assert plan.executable is True
    plan.require_executable()


@pytest.mark.parametrize("operation", [
    check_execution_eligibility, accept_execution,
])
def test_external_transaction_preserved_for_each_profile(
    environment, db, operation,
):
    req = environment[1]
    db.execute("BEGIN")
    db.execute("UPDATE sessions SET revision=8")
    try:
        with pytest.raises(ExecutionNotEligible):
            operation(db, req)
        assert db.in_transaction
        assert db.execute(
            "SELECT revision FROM sessions"
        ).fetchone()[0] == 8
    finally:
        db.rollback()

    assert db.execute(
        "SELECT revision FROM sessions"
    ).fetchone()[0] == 7
    assert db.execute(
        "SELECT COUNT(*) FROM execution_acceptances"
    ).fetchone()[0] == 0
