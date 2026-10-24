import pytest

from pcsala_agent.controlled import run_unit
from pcsala_agent.database import connect
from pcsala_agent.migrations import migrate
from pcsala_agent.sessions import SessionController, SessionConflict

@pytest.fixture
def environment(tmp_path):
    path = tmp_path / "state.sqlite"
    migrate(path)
    db = connect(path)
    try:
        with db:
            db.execute(
                """INSERT INTO projects(project_id,name,authorized_root)
                VALUES ('p','Simulacao','/referencia-sem-acesso')"""
            )
            db.execute(
                "INSERT INTO sessions(session_id,project_id) VALUES ('s','p')"
            )
            db.execute(
                """INSERT INTO tasks
                (task_id,project_id,title,acceptance_criteria)
                VALUES ('t','p','Simulacao','Duas etapas confirmadas')"""
            )
        controller = SessionController(db)
        revision = controller.advance("s", 0, "STARTING")
        revision = controller.advance("s", revision, "READY")
        controller.advance("s", revision, "RUNNING")
    finally:
        db.close()
    return tmp_path

def query(root, sql):
    db = connect(root / "state.sqlite")
    try:
        return [tuple(row) for row in db.execute(sql)]
    finally:
        db.close()

def test_duas_unidades_e_revisao(environment):
    first = run_unit(environment, "p", "s", "t")
    assert first["completed_steps"] == 1
    assert first["session_state"] == "RUNNING"
    second = run_unit(environment, "p", "s", "t")
    assert second["status"] == "SIMULACAO_CONCLUIDA"
    assert query(environment, "SELECT status FROM tasks") == [("REVIEW",)]
    assert query(environment, "SELECT status FROM attempts") == [
        ("SUCCEEDED",), ("SUCCEEDED",)
    ]
    with pytest.raises(SessionConflict):
        run_unit(environment, "p", "s", "t")
    assert query(environment, "SELECT COUNT(*) FROM attempts") == [(2,)]

def test_pausa_apos_despacho_e_retomada(environment):
    from pcsala_agent.simulated import execute as sim_execute

    def pause_then_execute(root, command, project, session, task):
        db = connect(root / "state.sqlite")
        try:
            revision = db.execute(
                "SELECT revision FROM sessions WHERE session_id=?", (session,)
            ).fetchone()[0]
            SessionController(db).request_pause(session, revision)
        finally:
            db.close()
        return sim_execute(root, command, project, session, task)

    result = run_unit(
        environment, "p", "s", "t", driver=pause_then_execute
    )
    assert result["session_state"] == "PAUSED"
    assert result["completed_steps"] == 1
    assert query(environment, "SELECT status FROM attempts") == [("SUCCEEDED",)]
    assert query(environment, "SELECT status FROM control_requests") == [("APPLIED",)]

    with pytest.raises(SessionConflict):
        run_unit(environment, "p", "s", "t")

    db = connect(environment / "state.sqlite")
    try:
        controller = SessionController(db)
        revision = db.execute(
            "SELECT revision FROM sessions WHERE session_id='s'"
        ).fetchone()[0]
        revision = controller.advance("s", revision, "READY")
        controller.advance("s", revision, "RUNNING")
    finally:
        db.close()

    final = run_unit(environment, "p", "s", "t")
    assert final["status"] == "SIMULACAO_CONCLUIDA"

def test_falha_exige_recuperacao(environment):
    def failing_driver(*args):
        raise RuntimeError("Falha controlada do executor")

    with pytest.raises(RuntimeError):
        run_unit(environment, "p", "s", "t", driver=failing_driver)
    assert query(environment, "SELECT state FROM sessions") == [
        ("RECOVERY_REQUIRED",)
    ]
    assert query(environment, "SELECT status FROM attempts") == [
        ("INDETERMINATE",)
    ]
    assert query(environment, "SELECT status FROM tasks") == [("BLOCKED",)]
    with pytest.raises(SessionConflict):
        run_unit(environment, "p", "s", "t")
