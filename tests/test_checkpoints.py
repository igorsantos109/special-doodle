from pathlib import Path

import pytest

from pcsala_agent.database import connect, initialize
from pcsala_agent.checkpoints import CheckpointStore, RecoveryRequired

MIGRATION = Path(__file__).resolve().parents[1] / "migrations/001_checkpoints.sql"

@pytest.fixture
def store(tmp_path):
    db = connect(tmp_path / "state.sqlite")
    initialize(db, MIGRATION)
    try:
        yield CheckpointStore(db, tmp_path / "artifacts")
    finally:
        db.close()

def committed(store, project="p", session="s", task="t"):
    cid = store.prepare(project, session, task)
    path = store.add_artifact(cid, b"estado confirmado")
    store.commit(cid)
    return cid, path

def test_confirmacao_e_escopo(store):
    cid, _ = committed(store)
    committed(store, project="outro")
    committed(store, session="outra")
    committed(store, task="outra")
    assert store.latest("p", "s", "t")["checkpoint_id"] == cid
    assert store.latest("inexistente", "s", "t") is None

@pytest.mark.parametrize("change", ["alterado", "ausente"])
def test_bloqueia_artefato_invalido(store, change):
    _, path = committed(store)
    if change == "alterado":
        path.write_bytes(b"alteracao posterior")
    else:
        path.unlink()
    with pytest.raises(RecoveryRequired):
        store.latest("p", "s", "t")

def test_nao_confirma_sem_artefato(store):
    cid = store.prepare("p", "s", "t")
    with pytest.raises(RecoveryRequired):
        store.commit(cid)
    assert store.latest("p", "s", "t") is None

def test_recuperacao_preserva_escopo_e_confirmados(store):
    good, _ = committed(store)
    pending = store.prepare("p", "s", "t")
    other = store.prepare("outro", "s", "t")
    assert store.recover("p", "s") == {"checkpoints": 1, "operations": 0}
    status = dict(store.db.execute(
        "SELECT checkpoint_id, status FROM checkpoints"
    ).fetchall())
    assert status[pending] == "NEEDS_RECOVERY"
    assert status[other] == "PREPARING"
    assert status[good] == "COMMITTED"
    assert store.latest("p", "s", "t")["checkpoint_id"] == good

def test_operacao_indeterminada_nao_reexecutada(store):
    with store.db:
        store.db.execute(
            """INSERT INTO operations
            (operation_id, project_id, session_id, task_id,
             operation_type, target, input_hash, status)
            VALUES ('op1','p','s','t','SIMULATED','alvo','hash-teste','STARTED')"""
        )
    assert store.recover("p", "s")["operations"] == 1
    row = store.db.execute(
        "SELECT status, result_reference FROM operations WHERE operation_id='op1'"
    ).fetchone()
    assert row["status"] == "INDETERMINATE"
    assert row["result_reference"] is None
    assert store.recover("p", "s")["operations"] == 0

def test_checkpoint_reaberto_em_disco(store):
    cid, _ = committed(store)
    db_path = store.db.execute("PRAGMA database_list").fetchone()["file"]
    db2 = connect(db_path)
    try:
        reopened = CheckpointStore(db2, store.root)
        assert reopened.latest("p", "s", "t")["checkpoint_id"] == cid
        assert db2.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        db2.close()
