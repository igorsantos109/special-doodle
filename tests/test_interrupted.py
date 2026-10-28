import subprocess
import sys

import pytest

from pcsala_agent.checkpoints import CheckpointStore
from pcsala_agent.controlled import run_unit
from pcsala_agent.database import connect
from pcsala_agent.locking import ExecutorBusy, database_lock
from pcsala_agent.migrations import migrate
from pcsala_agent.recovery import classify_interrupted
from pcsala_agent.sessions import SessionConflict, SessionController


@pytest.fixture
def environment(tmp_path):
    migrate(tmp_path / "state.sqlite")
    db = connect(tmp_path / "state.sqlite")
    try:
        with db:
            db.execute(
                """INSERT INTO projects(project_id,name,authorized_root)
                VALUES ('p','Simulacao','/referencia')"""
            )
            db.execute(
                "INSERT INTO sessions(session_id,project_id) VALUES ('s','p')"
            )
            db.execute(
                """INSERT INTO tasks
                (task_id,project_id,title,acceptance_criteria)
                VALUES ('t','p','Simulacao','Checkpoint confirmado')"""
            )
        controller = SessionController(db)
        revision = controller.advance("s", 0, "STARTING")
        revision = controller.advance("s", revision, "READY")
        controller.advance("s", revision, "RUNNING")
    finally:
        db.close()
    return tmp_path

def test_morte_apos_checkpoint_preserva_e_bloqueia(environment):
    script = """
import os
import sys
from pcsala_agent.controlled import run_unit
from pcsala_agent.simulated import execute

def crash_after_graph(*args):
    execute(*args)
    os._exit(75)

run_unit(sys.argv[1], "p", "s", "t", driver=crash_after_graph)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(environment)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 75, result.stderr

    report = classify_interrupted(environment, "p", "s")
    assert report["attempts_classified"] == 1
    assert report["checkpoints_classified"] == 0
    assert report["unresolved_records"] == 1

    db = connect(environment / "state.sqlite")
    try:
        store = CheckpointStore(db, environment / "artifacts")
        assert store.latest("p", "s", "t") is not None
        assert db.execute(
            "SELECT COUNT(*) FROM checkpoints"
        ).fetchone()[0] == 1
        assert db.execute(
            "SELECT status FROM tasks"
        ).fetchone()[0] == "BLOCKED"
        assert db.execute(
            "SELECT state FROM sessions"
        ).fetchone()[0] == "RECOVERY_REQUIRED"
    finally:
        db.close()

    with pytest.raises(SessionConflict):
        run_unit(environment, "p", "s", "t")

    repeated = classify_interrupted(environment, "p", "s")
    assert repeated["attempts_classified"] == 0
    assert repeated["unresolved_records"] == 1

def test_recuperacao_recusa_executor_com_bloqueio(environment):
    with database_lock(environment / "executor-owner"), pytest.raises(ExecutorBusy):
        classify_interrupted(environment, "p", "s")

def test_classificacao_sem_pendencias_preserva_estado(environment):
    result = classify_interrupted(environment, "p", "s")
    assert result["unresolved_records"] == 0
    db = connect(environment / "state.sqlite")
    try:
        assert db.execute(
            "SELECT state FROM sessions"
        ).fetchone()[0] == "RUNNING"
    finally:
        db.close()
