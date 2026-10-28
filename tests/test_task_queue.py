import json
import os
import tempfile
from pathlib import Path

from pcsala_agent.task_queue import (
    cancel, enqueue, get, list_tasks, reserve, update,
)
from pcsala_agent.migrations import migrate


def _init():
    tmp = tempfile.mkdtemp()
    db = Path(tmp) / "state.sqlite"
    migrate(db)
    return db, tmp


def test_duas_tarefas_identidades_distintas():
    db, tmp = _init()
    t1 = enqueue(db, "Primeira tarefa")
    t2 = enqueue(db, "Segunda tarefa")
    assert t1["id"] != t2["id"]
    assert t1["attempt_id"] != t2["attempt_id"]
    assert t1["status"] == "QUEUED"
    assert t2["status"] == "QUEUED"


def test_submissao_idempotente():
    db, tmp = _init()
    t1 = enqueue(db, "Mesmo texto", idempotency_key="k1")
    t2 = enqueue(db, "Mesmo texto", idempotency_key="k1")
    assert t1["id"] == t2["id"]


def test_submissao_idempotente_conteudo_diferente():
    db, tmp = _init()
    enqueue(db, "Texto A", idempotency_key="k1")
    import pytest
    with pytest.raises(ValueError):
        enqueue(db, "Texto B", idempotency_key="k1")


def test_reserva_atomica_nao_duplica():
    db, tmp = _init()
    enqueue(db, "Unica tarefa")
    r1 = reserve(db)
    r2 = reserve(db)
    assert r1 is not None
    assert r2 is None
    assert r1["status"] == "RESERVED"


def test_reserva_seleciona_ordem_correta():
    db, tmp = _init()
    enqueue(db, "Primeira")
    enqueue(db, "Segunda")
    r1 = reserve(db)
    r2 = reserve(db)
    assert r1["id"] == 1
    assert r2["id"] == 2


def test_atualizacao_completa():
    db, tmp = _init()
    enqueue(db, "Tarefa")
    task = reserve(db)
    update(db, task["id"],
           inference_response="Resposta X",
           inference_id="inf-001",
           inference_model="gpu-model",
           inference_status="SUCCESS")
    result = get(db, task["id"])
    assert result["status"] == "COMPLETED"
    assert result["inference_response"] == "Resposta X"
    assert result["inference_id"] == "inf-001"


def test_atualizacao_falha():
    db, tmp = _init()
    enqueue(db, "Tarefa")
    task = reserve(db)
    update(db, task["id"], error="Erro simulado")
    result = get(db, task["id"])
    assert result["status"] == "FAILED"
    assert "Erro simulado" in result["error"]


def test_cancelamento():
    db, tmp = _init()
    enqueue(db, "Cancelavel")
    ok = cancel(db, 1)
    assert ok
    task = get(db, 1)
    assert task["status"] == "CANCELLED"


def test_cancelamento_tarefa_reservada_bloqueia():
    db, tmp = _init()
    enqueue(db, "Nao cancelavel")
    reserve(db)
    ok = cancel(db, 1)
    assert not ok


def test_listagem_filtrada():
    db, tmp = _init()
    for i in range(3):
        enqueue(db, f"Tarefa {i}")
    reserve(db)
    all_tasks = list_tasks(db)
    queued = list_tasks(db, status="QUEUED")
    completed = list_tasks(db, status="COMPLETED")
    assert len(all_tasks) == 3
    assert len(queued) == 2
    assert len(completed) == 0


def test_fila_vazia_retorna_none():
    db, tmp = _init()
    task = reserve(db)
    assert task is None


def test_consulta_tarefa_inexistente():
    db, tmp = _init()
    task = get(db, 999)
    assert task is None