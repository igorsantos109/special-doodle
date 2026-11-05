"""Testes de injeção de falha (debugger) para cada modo de falha mapeado.

Todos os testes usam backends injetados (HTTP falso, systemctl falso,
nvidia-smi falso, llama-swap falso); nenhum requer hardware real.
"""
import io
import json
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from pcsala_agent.checkpoints import RecoveryRequired
from pcsala_agent.inference_adapter import InferenceAdapter, _urlrequest
from pcsala_agent.inference_contract import InferenceConfig, InferenceRequest
from pcsala_agent.locking import ExecutorBusy
from pcsala_agent.migrations import migrate
from pcsala_agent.model_manager import ModelCoordinator, ModelRegistry
from pcsala_agent.models_cli import ModelsCLI
from pcsala_agent.task_queue import enqueue, get, reserve, update


def _request(profile="cpu-triage-v1", prompt="teste"):
    return InferenceRequest(
        project_id="p", session_id="s", task_id="t", attempt_id="a",
        profile=profile, user_prompt=prompt,
    )


def _completion(finish="stop", text="ok", model="test"):
    return json.dumps(
        {"model": model, "choices": [{"message": {"content": text},
                                      "finish_reason": finish}]}
    ).encode()


# ---------------------------------------------------------------------------
# Inferência — modos de falha
# ---------------------------------------------------------------------------

class TestInferenciaFalhas:
    def test_read_levanta_timeout_depois_de_abrir(self):
        """resp.read() levanta TimeoutError após conexão aberta."""
        class Response(io.BytesIO):
            def read(self, n=-1):
                raise TimeoutError("read timed out")

        response = Response(b"")
        result = InferenceAdapter().query(
            _request(), _urlopen=lambda *a, **k: response
        )
        assert result.status == "TIMEOUT"

    def test_url_error_wrapped_timeout(self):
        """URLError com reason TimeoutError é classificado como TIMEOUT."""
        def transport(*a, **k):
            raise urllib.error.URLError(TimeoutError("wrapped"))

        result = InferenceAdapter().query(_request(), _urlopen=transport)
        assert result.status == "TIMEOUT"

    def test_corpo_excede_limite_eh_invalido(self):
        """Corpo maior que max_response_bytes é rejeitado."""
        result = InferenceAdapter(
            InferenceConfig(max_response_bytes=10)
        ).query(_request(), _urlopen=lambda *a, **k: io.BytesIO(_completion()))
        assert result.status == "INVALID_RESPONSE"

    def test_finish_reason_length_eh_invalido(self):
        """finish_reason=length (truncamento) não é sucesso."""
        result = InferenceAdapter().query(
            _request(), _urlopen=lambda *a, **k: io.BytesIO(_completion(finish="length"))
        )
        assert result.status == "INVALID_RESPONSE"

    def test_choices_vazio_eh_invalido(self):
        result = InferenceAdapter().query(
            _request(), _urlopen=lambda *a, **k: io.BytesIO(
                json.dumps({"model": "test", "choices": []}).encode())
        )
        assert result.status == "INVALID_RESPONSE"

    def test_choices_nulo_eh_invalido(self):
        result = InferenceAdapter().query(
            _request(), _urlopen=lambda *a, **k: io.BytesIO(
                json.dumps({"model": "test", "choices": None}).encode())
        )
        assert result.status == "INVALID_RESPONSE"

    def test_choices_contem_null_eh_invalido(self):
        result = InferenceAdapter().query(
            _request(), _urlopen=lambda *a, **k: io.BytesIO(
                json.dumps({"model": "test", "choices": [None]}).encode())
        )
        assert result.status == "INVALID_RESPONSE"

    def test_corpo_nao_json_eh_invalido(self):
        result = InferenceAdapter().query(
            _request(), _urlopen=lambda *a, **k: io.BytesIO(b"not json")
        )
        assert result.status == "INVALID_RESPONSE"

    def test_corpo_vazio_eh_invalido(self):
        result = InferenceAdapter().query(
            _request(), _urlopen=lambda *a, **k: io.BytesIO(b"")
        )
        assert result.status == "INVALID_RESPONSE"

    def test_default_transport_passa_timeout(self):
        captured = {}
        def transport(req, **kwargs):
            captured.update(kwargs)
            return "response"
        import urllib.request
        original = urllib.request.urlopen
        urllib.request.urlopen = transport
        try:
            _urlrequest("request", timeout=7)
        finally:
            urllib.request.urlopen = original
        assert captured["timeout"] == 7


# ---------------------------------------------------------------------------
# Modelo — modos de falha (start/stop/switch)
# ---------------------------------------------------------------------------

class _FakeGpuMonitor:
    def __init__(self, free_mb=None):
        self._free_mb = free_mb

    def free_mb(self):
        return self._free_mb


class TestModeloFalhas:
    def _coord(self, tmp_path):
        path = tmp_path / "state.sqlite"
        migrate(path)
        return ModelCoordinator(ModelRegistry(), database=path), path

    def test_start_falha_codigo_nao_zero(self, tmp_path, monkeypatch):
        coord, _ = self._coord(tmp_path)
        calls = []
        def systemctl(action, unit):
            calls.append((action, unit))
            return 1
        monkeypatch.setattr("pcsala_agent.models_cli._unit_inactive", lambda u: True)
        cli = ModelsCLI(
            coordinator=coord, systemctl=systemctl,
            skip_vram_guard=True, lock_dir=tmp_path / "locks",
        )
        cli._is_model_running = lambda m: False
        assert cli.run(["start", "bonsai-27b-gpu"]) == 1
        assert calls == [("start", "bonsai2-27b.service")]

    def test_systemctl_timeout_retorna_124(self, monkeypatch):
        import subprocess
        def failure(*a, **k):
            raise subprocess.TimeoutExpired("systemctl", 30)
        monkeypatch.setattr("subprocess.run", failure)
        assert ModelsCLI._run_systemctl("start", "test.service") == 124

    def test_health_timeout_retorna_failed(self, tmp_path, monkeypatch):
        coord, _ = self._coord(tmp_path)
        def systemctl(action, unit):
            return 0
        monkeypatch.setattr("pcsala_agent.models_cli._unit_inactive", lambda u: False)
        cli = ModelsCLI(
            coordinator=coord, systemctl=systemctl,
            skip_vram_guard=True, lock_dir=tmp_path / "locks",
        )
        cli._is_model_running = lambda m: False
        monkeypatch.setattr(
            "pcsala_agent.model_manager.ModelCoordinator.wait_for_health",
            lambda self, model_id, timeout=None: False,
        )
        cli._is_model_running = lambda model: False
        assert cli.run(["start", "bonsai-27b-gpu"]) == 1

    def test_switch_falha_alvo_nao_sobe_restaura_anterior(self, tmp_path, monkeypatch):
        coord, _ = self._coord(tmp_path)
        old = "bonsai-27b-gpu"
        new = "laguna-xs-2.1-gpu"
        coord.reserve_engine(old)
        active = {coord.registry.get(old).unit}
        calls = []

        def systemctl(action, unit):
            calls.append((action, unit))
            if action == "start" and unit == coord.registry.get(new).unit:
                return 1
            if action == "start":
                active.add(unit)
            elif action == "stop":
                active.discard(unit)
            return 0

        monkeypatch.setattr(
            "pcsala_agent.models_cli._unit_inactive",
            lambda u: u not in active,
        )
        monkeypatch.setattr(
            "pcsala_agent.model_manager._unit_active", lambda u: u in active,
        )
        # Evita esperar o /health real de 600s no rollback.
        coord.wait_for_health = lambda model_id, timeout=None: True
        cli = ModelsCLI(
            coordinator=coord, systemctl=systemctl,
            skip_vram_guard=True, lock_dir=tmp_path / "locks",
        )
        cli._await_vram_release = lambda: None
        assert cli.run(["switch", new]) == 1
        # A reserva do anterior deve ser mantida.
        assert coord.engine_reserved(old)
        assert not coord.engine_reserved(new)

    def test_vram_insuficiente_recusa_start(self, tmp_path, monkeypatch):
        coord, _ = self._coord(tmp_path)
        cli = ModelsCLI(
            coordinator=coord,
            systemctl=lambda *a: 0,
            gpu_monitor=_FakeGpuMonitor(free_mb=100),
            lock_dir=tmp_path / "locks",
        )
        # bonsai-27b-gpu é GPU e não está com skip_vram_guard.
        assert cli.run(["start", "bonsai-27b-gpu"]) == 3

    def test_nvidia_smi_indisponivel_falha_fechada(self, tmp_path, monkeypatch):
        coord, _ = self._coord(tmp_path)
        cli = ModelsCLI(
            coordinator=coord,
            systemctl=lambda *a: 0,
            gpu_monitor=_FakeGpuMonitor(free_mb=None),
            lock_dir=tmp_path / "locks",
        )
        assert cli.run(["start", "bonsai-27b-gpu"]) == 3

    def test_stop_sucesso_mas_unidade_ainda_ativa_mantem_reserva(self, tmp_path, monkeypatch):
        coord, _ = self._coord(tmp_path)
        coord.reserve_engine("bonsai-27b-gpu")
        cli = ModelsCLI(
            coordinator=coord, systemctl=lambda *a: 0,
            lock_dir=tmp_path / "locks",
        )
        monkeypatch.setattr(
            "pcsala_agent.models_cli._unit_inactive", lambda u: False,
        )
        assert cli.run(["stop", "bonsai-27b-gpu"]) == 1
        assert coord.engine_reserved("bonsai-27b-gpu")


# ---------------------------------------------------------------------------
# Fila — modos de falha
# ---------------------------------------------------------------------------

class TestFilaFalhas:
    def test_concorrencia_reserva_um_vencedor(self, tmp_path):
        path = tmp_path / "state.sqlite"
        migrate(path)
        # Uma única tarefa QUEUED disputada por duas threads: apenas uma
        # deve reservá-la; a outra recebe None (UPDATE condicional).
        enqueue(path, "concorrente")
        barrier = Barrier(2)

        def run():
            barrier.wait(timeout=5)
            try:
                return reserve(path) is not None
            except ExecutorBusy:
                return False

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sum(pool.map(lambda _: run(), [0, 1])) == 1

    def test_update_nao_sobrescreve_estado_terminal(self, tmp_path):
        path = tmp_path / "state.sqlite"
        task = enqueue(path, "terminal")
        reserve(path)
        update(path, task["id"], error="primeira falha")
        # update posterior não deve sobrescrever estado FAILED terminal.
        update(path, task["id"], inference_response="tarde", error="tarde")
        assert get(path, task["id"])["status"] == "FAILED"
        assert get(path, task["id"])["error"] == "primeira falha"

    def test_tarefa_reservada_nao_pode_ser_completada_sem_reserva(self, tmp_path):
        path = tmp_path / "state.sqlite"
        task = enqueue(path, "nao reservada")
        # Sem reserve, update não altera de QUEUED.
        update(path, task["id"], inference_response="tarde")
        assert get(path, task["id"])["status"] == "QUEUED"

    def test_idempotency_key_reusada_com_prompt_diferente_falha(self, tmp_path):
        path = tmp_path / "state.sqlite"
        enqueue(path, "prompt A", idempotency_key="chave")
        with pytest.raises(ValueError):
            enqueue(path, "prompt B", idempotency_key="chave")


# ---------------------------------------------------------------------------
# Grafo — modos de falha
# ---------------------------------------------------------------------------

class TestGrafoFalhas:
    def test_sessao_nao_running_retorna_pendente(self, tmp_path, monkeypatch):
        env = tmp_path
        db_path = env / "state.sqlite"
        migrate(db_path)
        from pcsala_agent.database import connect
        from pcsala_agent.real_graph import execute

        db = connect(db_path)
        try:
            with db:
                db.execute(
                    """INSERT OR IGNORE INTO projects(project_id,name,authorized_root)
                    VALUES (?, ?, ?)""",
                    ("p", "t", str(tmp_path)),
                )
                db.execute(
                    """INSERT OR IGNORE INTO sessions
                    (session_id,project_id,state,revision,api_mode)
                    VALUES (?,?, 'STOPPED', 0, 'OFFLINE')""",
                    ("s", "p"),
                )
        finally:
            db.close()

        resultado = execute(
            env, "iniciar", "p", "s", "t", "a", "prompt",
        )
        assert resultado["step"] == "sessao_nao_running"

    def test_indeterminate_pendente_levanta_runtime_error(self, tmp_path, monkeypatch):
        env = tmp_path
        db_path = env / "state.sqlite"
        migrate(db_path)
        from pcsala_agent.database import connect
        from pcsala_agent.real_graph import execute

        db = connect(db_path)
        try:
            with db:
                db.execute(
                    """INSERT OR IGNORE INTO projects(project_id,name,authorized_root)
                    VALUES (?, ?, ?)""",
                    ("p", "t", str(tmp_path)),
                )
                db.execute(
                    """INSERT OR IGNORE INTO sessions
                    (session_id,project_id,state,revision,api_mode)
                    VALUES (?,?, 'RUNNING', 0, 'OFFLINE')""",
                    ("s", "p"),
                )
                db.execute(
                    """INSERT OR IGNORE INTO operations
                    (operation_id,project_id,session_id,task_id,operation_type,
                     target,input_hash,status,result_reference,completed_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    ("op1", "p", "s", "t", "INFERENCE", "x", "h", "INDETERMINATE", None, None),
                )
        finally:
            db.close()

        with pytest.raises(RuntimeError, match="reconciliacao pendente"):
            execute(env, "iniciar", "p", "s", "t", "a", "prompt")


# ---------------------------------------------------------------------------
# Checkpoints — modos de falha
# ---------------------------------------------------------------------------

class TestCheckpointsFalhas:
    def test_commit_sem_artefato_levanta_recovery_required(self, tmp_path):
        from pcsala_agent.checkpoints import CheckpointStore
        from pcsala_agent.database import connect

        db_path = tmp_path / "state.sqlite"
        migrate(db_path)
        db = connect(db_path)
        try:
            store = CheckpointStore(db, tmp_path / "artifacts")
            cid = store.prepare("p", "s", "t")
            # Não adiciona artefato; commit deve falhar.
            with pytest.raises(RecoveryRequired, match="sem artefato"):
                store.commit(cid)
        finally:
            db.close()

    def test_artefato_alterado_hash_diverge_levanta_recovery_required(self, tmp_path):
        from pcsala_agent.checkpoints import CheckpointStore
        from pcsala_agent.database import connect

        db_path = tmp_path / "state.sqlite"
        migrate(db_path)
        db = connect(db_path)
        try:
            store = CheckpointStore(db, tmp_path / "artifacts")
            cid = store.prepare("p", "s", "t")
            store.add_artifact(cid, b"dados originais")
            # Corrompe o arquivo no disco.
            artefato = tmp_path / "artifacts" / f"{cid}.bin"
            artefato.write_bytes(b"dados corrompidos")
            with pytest.raises(RecoveryRequired, match="artefato alterado"):
                store.commit(cid)
        finally:
            db.close()
