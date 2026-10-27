import pytest

from pcsala_agent.checkpoints import CheckpointStore, RecoveryRequired
from pcsala_agent.database import connect
from pcsala_agent.migrations import migrate
from pcsala_agent.sessions import SessionConflict, SessionController


@pytest.fixture
def setup(tmp_path):
    path = tmp_path / "state.sqlite"
    migrate(path)
    db = connect(path)
    with db:
        db.execute(
            """INSERT INTO projects(project_id,name,authorized_root)
            VALUES ('p','Projeto','/somente-referencia')"""
        )
        db.execute(
            "INSERT INTO sessions(session_id,project_id) VALUES ('s','p')"
        )
        db.execute(
            """INSERT INTO tasks
            (task_id,project_id,title,acceptance_criteria)
            VALUES ('t','p','Tarefa','Criterio definido')"""
        )
    controller = SessionController(db)
    store = CheckpointStore(db, tmp_path / "artifacts")
    try:
        yield db, controller, store
    finally:
        db.close()

def running(controller):
    revision = controller.advance("s", 0, "STARTING")
    revision = controller.advance("s", revision, "READY")
    return controller.advance("s", revision, "RUNNING")

def checkpoint(store):
    cid = store.prepare("p", "s", "t")
    path = store.add_artifact(cid, b"estado para pausa")
    store.commit(cid)
    return cid, path

def test_transicoes_e_revisao_antiga(setup):
    db, controller, _ = setup
    assert controller.advance("s", 0, "STARTING") == 1
    with pytest.raises(SessionConflict):
        controller.advance("s", 0, "READY")
    with pytest.raises(SessionConflict):
        controller.advance("s", 1, "RUNNING")
    assert db.execute(
        "SELECT state FROM sessions WHERE session_id='s'"
    ).fetchone()[0] == "STARTING"

def test_pedido_de_pausa_bloqueia_despacho(setup):
    db, controller, _ = setup
    revision = running(controller)
    request = controller.request_pause("s", revision)
    with pytest.raises(SessionConflict):
        controller.dispatch("s", request["revision"], "t")
    assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0
    assert db.execute(
        "SELECT state FROM sessions WHERE session_id='s'"
    ).fetchone()[0] == "PAUSE_REQUESTED"

def test_pausa_confirmada_e_auditada(setup):
    db, controller, store = setup
    revision = running(controller)
    cid, _ = checkpoint(store)
    request = controller.request_pause("s", revision)
    revision = controller.confirm_pause(
        "s", request["revision"], request["request_id"], cid, store
    )
    row = db.execute("SELECT state, revision FROM sessions").fetchone()
    assert tuple(row) == ("PAUSED", revision)
    assert db.execute(
        "SELECT status FROM control_requests"
    ).fetchone()[0] == "APPLIED"
    assert db.execute(
        "SELECT COUNT(*) FROM audit_events WHERE event_type='PAUSED'"
    ).fetchone()[0] == 1

def test_tentativa_ativa_impede_confirmacao(setup):
    _, controller, store = setup
    revision = running(controller)
    attempt = controller.dispatch("s", revision, "t")
    cid, _ = checkpoint(store)
    request = controller.request_pause("s", attempt["revision"])
    with pytest.raises(SessionConflict):
        controller.confirm_pause(
            "s", request["revision"], request["request_id"], cid, store
        )

def test_artefato_alterado_nao_confirma_pausa(setup):
    db, controller, store = setup
    revision = running(controller)
    cid, path = checkpoint(store)
    request = controller.request_pause("s", revision)
    path.write_bytes(b"alterado")
    with pytest.raises(RecoveryRequired):
        controller.confirm_pause(
            "s", request["revision"], request["request_id"], cid, store
        )
    assert db.execute(
        "SELECT state FROM sessions"
    ).fetchone()[0] == "PAUSE_REQUESTED"
    assert db.execute(
        "SELECT status FROM control_requests"
    ).fetchone()[0] == "REQUESTED"

def test_offline_padrao_e_despacho_unico(setup):
    db, controller, _ = setup
    assert db.execute(
        "SELECT api_mode FROM sessions"
    ).fetchone()[0] == "OFFLINE"
    revision = running(controller)
    attempt = controller.dispatch("s", revision, "t")
    with pytest.raises(SessionConflict):
        controller.dispatch("s", attempt["revision"], "t")
    assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 1
