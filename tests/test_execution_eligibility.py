import pytest

from pcsala_agent.database import connect
from pcsala_agent.execution_contract import ExecutionRequest
from pcsala_agent.execution_eligibility import (
    ExecutionNotEligible,
    check_execution_eligibility,
)
from pcsala_agent.migrations import migrate


def request(**changes):
    values = dict(
        project_id="p", session_id="s", task_id="t",
        attempt_id="a", profile="diagnostic-v1",
    )
    values.update(changes)
    return ExecutionRequest(**values)

@pytest.fixture
def db(tmp_path):
    path = tmp_path / "state.sqlite"
    migrate(path)
    connection = connect(path)
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
    try:
        yield connection
    finally:
        connection.close()

def test_eligible_observation_does_not_write(db):
    before = list(db.iterdump())
    changes = db.total_changes
    result = check_execution_eligibility(db, request())
    assert result.request == request()
    assert result.session_revision == 7
    assert db.total_changes == changes
    assert not db.in_transaction
    assert list(db.iterdump()) == before

@pytest.mark.parametrize("field", [
    "project_id", "session_id", "task_id", "attempt_id",
])
def test_missing_or_wrong_scope(db, field):
    with pytest.raises(ExecutionNotEligible):
        check_execution_eligibility(db, request(**{field: "outro"}))
    assert not db.in_transaction

@pytest.mark.parametrize("state", [
    "STOPPED", "STARTING", "READY", "PAUSE_REQUESTED", "PAUSED",
    "DRAINING", "CHECKPOINTING", "ERROR", "RECOVERY_REQUIRED",
])
def test_session_state_blocks(db, state):
    with db:
        db.execute("UPDATE sessions SET state=?", (state,))
    with pytest.raises(ExecutionNotEligible):
        check_execution_eligibility(db, request())

@pytest.mark.parametrize("status", [
    "PENDING", "BLOCKED", "REVIEW", "VALIDATED",
])
def test_task_status_blocks(db, status):
    with db:
        db.execute("UPDATE tasks SET status=?", (status,))
    with pytest.raises(ExecutionNotEligible):
        check_execution_eligibility(db, request())

@pytest.mark.parametrize("status", [
    "PREPARED", "SUCCEEDED", "FAILED", "INDETERMINATE",
])
def test_attempt_status_blocks(db, status):
    with db:
        db.execute("UPDATE attempts SET status=?", (status,))
    with pytest.raises(ExecutionNotEligible):
        check_execution_eligibility(db, request())

@pytest.mark.parametrize("action", ["PAUSE", "DRAIN", "RESUME"])
def test_pending_control_blocks_even_if_session_running(db, action):
    with db:
        db.execute(
            """INSERT INTO control_requests
            (request_id,session_id,action) VALUES ('r','s',?)""",
            (action,),
        )
    with pytest.raises(ExecutionNotEligible):
        check_execution_eligibility(db, request())

@pytest.mark.parametrize("status", ["APPLIED", "REJECTED"])
def test_closed_control_does_not_block(db, status):
    with db:
        db.execute(
            """INSERT INTO control_requests
            (request_id,session_id,action,status)
            VALUES ('r','s','PAUSE',?)""",
            (status,),
        )
    assert check_execution_eligibility(db, request()).session_revision == 7

def test_existing_attempt_cannot_be_reassigned_by_request(db):
    with db:
        db.execute(
            """INSERT INTO tasks
            (task_id,project_id,title,acceptance_criteria,status)
            VALUES ('other','p','Outra','Criterio','RUNNING')"""
        )
    with pytest.raises(ExecutionNotEligible):
        check_execution_eligibility(db, request(task_id="other"))

def test_external_transaction_preserved(db):
    db.execute("BEGIN")
    db.execute("UPDATE sessions SET revision=8")
    with pytest.raises(ExecutionNotEligible):
        check_execution_eligibility(db, request())
    assert db.in_transaction
    assert db.execute("SELECT revision FROM sessions").fetchone()[0] == 8
    db.rollback()
    assert db.execute("SELECT revision FROM sessions").fetchone()[0] == 7

def test_observation_is_not_a_reservation(db):
    observed = check_execution_eligibility(db, request())
    with db:
        db.execute(
            "UPDATE sessions SET state='DRAINING',revision=revision+1"
        )
    assert observed.session_revision == 7
    with pytest.raises(ExecutionNotEligible):
        check_execution_eligibility(db, request())
