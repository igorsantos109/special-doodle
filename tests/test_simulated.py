import json
import sqlite3
import subprocess
import sys

from pcsala_agent.locking import database_lock


def cli(root, command, session="s"):
    return subprocess.run(
        [
            sys.executable, "-m", "pcsala_agent.simulated", command,
            "--root", str(root),
            "--project", "p", "--session", session, "--task", "t",
        ],
        capture_output=True, text=True, timeout=20,
    )

def test_retomada_em_processos_separados(tmp_path):
    root = tmp_path / "run"
    first = cli(root, "iniciar")
    assert first.returncode == 0, first.stderr
    first_data = json.loads(first.stdout)
    assert first_data["status"] == "CHECKPOINT_SALVO"

    second = cli(root, "retomar")
    assert second.returncode == 0, second.stderr
    second_data = json.loads(second.stdout)
    assert second_data["status"] == "SIMULACAO_CONCLUIDA"
    assert first_data["checkpoint_id"] != second_data["checkpoint_id"]

    third = cli(root, "retomar")
    assert third.returncode == 0, third.stderr
    third_data = json.loads(third.stdout)
    assert third_data["nova_execucao"] is False
    assert third_data["checkpoint_id"] == second_data["checkpoint_id"]

    with sqlite3.connect(root / "state.sqlite") as db:
        assert db.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0] == 2

def test_recusa_segundo_inicio(tmp_path):
    assert cli(tmp_path, "iniciar").returncode == 0
    assert cli(tmp_path, "iniciar").returncode == 2

def test_recusa_escopo_inexistente(tmp_path):
    assert cli(tmp_path, "iniciar").returncode == 0
    assert cli(tmp_path, "retomar", session="outra").returncode == 2

def test_bloqueio_entre_processos(tmp_path):
    with database_lock(tmp_path / "state.sqlite"):
        result = cli(tmp_path, "iniciar")
        assert result.returncode == 3, result.stderr
    assert not (tmp_path / "state.sqlite").exists()

def test_artefato_alterado_bloqueia_retomada(tmp_path):
    assert cli(tmp_path, "iniciar").returncode == 0
    artifact = next((tmp_path / "artifacts").glob("*.bin"))
    artifact.write_bytes(b"alteracao posterior")
    result = cli(tmp_path, "retomar")
    assert result.returncode == 2, result.stderr
    with sqlite3.connect(tmp_path / "state.sqlite") as db:
        assert db.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0] == 1

def test_checkpoint_incompleto_bloqueia_sessao(tmp_path):
    assert cli(tmp_path, "iniciar").returncode == 0
    with sqlite3.connect(tmp_path / "state.sqlite") as db:
        db.execute(
            """INSERT INTO checkpoints
            (checkpoint_id, project_id, session_id, task_id, status)
            VALUES ('incompleto','p','s','t','PREPARING')"""
        )
    assert cli(tmp_path, "retomar").returncode == 2
    with sqlite3.connect(tmp_path / "state.sqlite") as db:
        status = db.execute(
            "SELECT status FROM checkpoints WHERE checkpoint_id='incompleto'"
        ).fetchone()[0]
        assert status == "NEEDS_RECOVERY"
    assert cli(tmp_path, "retomar").returncode == 2
