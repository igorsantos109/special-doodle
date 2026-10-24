import pytest

from pcsala_agent.checkpoints import RecoveryRequired
from pcsala_agent.controlled import run_unit
from pcsala_agent.database import connect
from pcsala_agent.locking import database_lock, ExecutorBusy
from pcsala_agent.migrations import migrate
from pcsala_agent.sessions import SessionController, SessionConflict
from pcsala_agent.shutdown import ShutdownController

@pytest.fixture
def environment(tmp_path):
    migrate(tmp_path / "state.sqlite")
    db = connect(tmp_path / "state.sqlite")
    try:
        with db:
            db.execute(
                """INSERT INTO projects(project_id,name,authorized_root)
                VALUES ('p','Simulado','/referencia')"""
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
    result = run_unit(tmp_path, "p", "s", "t")
    return tmp_path, result["checkpoint_id"]

def current(root):
    db = connect(root / "state.sqlite")
    try:
        return dict(db.execute(
            "SELECT * FROM sessions WHERE session_id='s'"
        ).fetchone())
    finally:
        db.close()

def test_encerramento_e_reabertura_do_controlador(environment):
    root, cid = environment
    controller = ShutdownController(root)
    request = controller.request("s", current(root)["revision"])
    assert current(root)["state"] == "DRAINING"

    with pytest.raises(SessionConflict):
        run_unit(root, "p", "s", "t")

    revision = controller.prepare(
        "s", request["revision"], request["request_id"], cid
    )
    assert current(root)["state"] == "CHECKPOINTING"

    reopened = ShutdownController(root)
    reopened.confirm("s", revision, request["request_id"])
    assert current(root)["state"] == "STOPPED"

    db = connect(root / "state.sqlite")
    try:
        assert db.execute(
            "SELECT status FROM control_requests WHERE request_id=?",
            (request["request_id"],),
        ).fetchone()[0] == "APPLIED"
    finally:
        db.close()

def test_checkpoint_alterado_impede_stop(environment):
    root, cid = environment
    controller = ShutdownController(root)
    request = controller.request("s", current(root)["revision"])
    revision = controller.prepare(
        "s", request["revision"], request["request_id"], cid
    )
    artifact = next((root / "artifacts").glob("*.bin"))
    artifact.write_bytes(b"alterado apos preparacao")
    with pytest.raises(RecoveryRequired):
        controller.confirm("s", revision, request["request_id"])
    assert current(root)["state"] == "CHECKPOINTING"

def test_executor_vivo_impede_preparacao(environment):
    root, cid = environment
    controller = ShutdownController(root)
    request = controller.request("s", current(root)["revision"])
    with database_lock(root / "executor-owner"):
        with pytest.raises(ExecutorBusy):
            controller.prepare(
                "s", request["revision"], request["request_id"], cid
            )
    assert current(root)["state"] == "DRAINING"

def test_revisao_antiga_nao_encerra(environment):
    root, cid = environment
    controller = ShutdownController(root)
    old = current(root)["revision"]
    request = controller.request("s", old)
    with pytest.raises(SessionConflict):
        controller.prepare("s", old, request["request_id"], cid)
    assert current(root)["state"] == "DRAINING"

def test_tentativa_ativa_bloqueia_ponto_seguro(environment):
    root, cid = environment
    db = connect(root / "state.sqlite")
    try:
        SessionController(db).dispatch("s", current(root)["revision"], "t")
    finally:
        db.close()
    controller = ShutdownController(root)
    request = controller.request("s", current(root)["revision"])
    with pytest.raises(SessionConflict):
        controller.prepare(
            "s", request["revision"], request["request_id"], cid
        )
    assert current(root)["state"] == "DRAINING"
