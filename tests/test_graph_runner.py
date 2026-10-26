import json
import os
import subprocess
import sys

from pcsala_agent.graph_runner import execute as worker_execute, _check_model_server
from pcsala_agent.locking import database_lock


def _response(status=200, body=None):
    class FakeResponse:
        def __init__(self):
            self.status = status
            self.body = body if body is not None else b""
        def read(self, n=-1):
            return self.body[:n] if n >= 0 else self.body
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
    return FakeResponse()


def _chat_completion(text, model="test-model"):
    return json.dumps({
        "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
        "model": model,
    }).encode()


def _make_env(tmp_path):
    from pcsala_agent.database import connect, initialize
    from pcsala_agent.migrations import migrate
    db_path = tmp_path / "state.sqlite"
    migrate(db_path)
    conn = connect(db_path)
    with conn:
        conn.execute(
            "INSERT INTO projects(project_id,name,authorized_root)"
            " VALUES ('p','Teste','/tmp')"
        )
        conn.execute(
            "INSERT INTO sessions(session_id,project_id,state,revision)"
            " VALUES ('s','p','RUNNING',0)"
        )
        conn.execute(
            "INSERT INTO tasks(task_id,project_id,title,acceptance_criteria,status)"
            " VALUES ('t','p','Teste','Ok','RUNNING')"
        )
        conn.execute(
            "INSERT INTO attempts(attempt_id,project_id,session_id,task_id,status)"
            " VALUES ('a','p','s','t','RUNNING')"
        )
    conn.close()


def cli(root, command, attempt="a", prompt="prompt de teste"):
    return subprocess.run(
        [
            sys.executable, "-m", "pcsala_agent.graph_runner", command,
            "--root", str(root),
            "--project", "p", "--session", "s", "--task", "t",
            "--attempt", attempt, "--prompt", prompt,
        ],
        capture_output=True, text=True, timeout=30,
    )


class TestWorkerAPI:
    def test_worker_conclui_com_inferencia(self, tmp_path):
        os.environ["DSH_LOCAL_API_KEY"] = "test-key-worker"
        _make_env(tmp_path)
        result = worker_execute(
            tmp_path, "iniciar", "p", "s", "t", "a", "prompt",
            _skip_health_check=True,
            _urlopen=lambda *a, **kw: _response(
                body=_chat_completion("resposta do worker")
            ),
        )
        assert result["status"] == "CONCLUIDO"
        assert result["inference_response"] == "resposta do worker"

    def test_worker_retomar_nao_refaz_inferencia(self, tmp_path):
        os.environ["DSH_LOCAL_API_KEY"] = "test-key-retry"
        _make_env(tmp_path)
        calls = []

        def counting_open(*a, **kw):
            calls.append(1)
            return _response(body=_chat_completion("resultado unico"))

        worker_execute(
            tmp_path, "iniciar", "p", "s", "t", "a", "prompt",
            _skip_health_check=True,
            _urlopen=counting_open,
        )
        first_calls = len(calls)

        worker_execute(
            tmp_path, "retomar", "p", "s", "t", "a", "prompt",
            _skip_health_check=True,
            _urlopen=counting_open,
        )
        assert len(calls) == first_calls

    def test_worker_prompt_vazio_rejeitado(self, tmp_path):
        os.environ["DSH_LOCAL_API_KEY"] = "test-key-worker"
        _make_env(tmp_path)
        result = worker_execute(
            tmp_path, "iniciar", "p", "s", "t", "a", "",
            _skip_health_check=True,
            _urlopen=lambda *a, **kw: _response(
                body=_chat_completion("resposta")
            ),
        )
        assert result["status"] == "CONCLUIDO"
        assert "vazio" in result["error"].lower()

    def test_worker_respeita_bloqueio(self, tmp_path):
        with database_lock(tmp_path / "state.sqlite"):
            result = cli(tmp_path, "iniciar")
            assert result.returncode == 3, result.stderr


class TestWorkerHealthCheck:
    def test_worker_health_check_falha_quando_servidor_indisponivel(self):
        import socket
        original = socket.create_connection
        def failing_connect(*a, **kw):
            raise ConnectionRefusedError("Simulando servidor indisponivel")
        socket.create_connection = failing_connect
        try:
            assert not _check_model_server()
        finally:
            socket.create_connection = original

    def test_worker_health_check_pode_ser_pulado(self, tmp_path):
        os.environ["DSH_LOCAL_API_KEY"] = "test-key-worker"
        _make_env(tmp_path)
        result = worker_execute(
            tmp_path, "iniciar", "p", "s", "t", "a", "prompt",
            _skip_health_check=True,
            _urlopen=lambda *a, **kw: _response(
                body=_chat_completion("ok")
            ),
        )
        assert result["status"] == "CONCLUIDO"


class TestWorkerRecovery:
    def test_worker_detecta_operacao_incerta(self, tmp_path):
        _make_env(tmp_path)
        from pcsala_agent.database import connect
        conn = connect(tmp_path / "state.sqlite")
        conn.execute(
            """INSERT INTO operations
            (operation_id,project_id,session_id,task_id,operation_type,target,input_hash,status)
            VALUES ('oid','p','s','t','INFERENCE','a','hash','INDETERMINATE')"""
        )
        conn.commit()
        conn.close()

        result = cli(tmp_path, "iniciar")
        assert result.returncode == 2, result.stderr
        assert "reconciliacao" in result.stderr.lower()

    def test_worker_retomada_sem_artefato_exige_cli_retomar(self, tmp_path):
        os.environ["DSH_LOCAL_API_KEY"] = "test-key-worker"
        _make_env(tmp_path)
        worker_execute(
            tmp_path, "iniciar", "p", "s", "t", "a", "prompt",
            _skip_health_check=True,
            _urlopen=lambda *a, **kw: _response(
                body=_chat_completion("resultado")
            ),
        )
        result = cli(tmp_path, "iniciar")
        assert result.returncode == 2, result.stderr


class TestWorkerCLI:
    def test_cli_help(self, tmp_path):
        result = subprocess.run(
            [sys.executable, "-m", "pcsala_agent.graph_runner", "--help"],
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "PYTHONPATH": os.path.abspath("src")},
        )
        assert result.returncode == 0
        assert "Bonsai" in result.stdout or "worker" in result.stdout or "LangGraph" in result.stdout

    def test_cli_usage_string(self):
        result = subprocess.run(
            [sys.executable, "-m", "pcsala_agent.graph_runner", "--help"],
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "PYTHONPATH": os.path.abspath("src")},
        )
        assert result.returncode == 0
        assert "--attempt" in result.stdout
        assert "--prompt" in result.stdout