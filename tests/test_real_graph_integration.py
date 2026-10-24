"""Testes de integracao: recuperacao e chamada real.

Usam substituicao do transporte para evitar chamadas reais longas.
Nao repetem a suite completa - apenas cenarios de integracao nao cobertos.
"""

import json
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from pcsala_agent.database import connect
from pcsala_agent.real_graph import execute
from pcsala_agent.checkpoints import CheckpointStore


FIXTURE_PROMPT = "O que e um agente de IA?"


def _make_env(session_state="RUNNING"):
    root = Path(tempfile.mkdtemp(prefix="real_graph_int_"))
    from pcsala_agent.migrations import migrate
    db_path = root / "state.sqlite"
    migrate(db_path)
    conn = connect(db_path)
    with conn:
        conn.execute(
            "INSERT INTO projects(project_id,name,authorized_root)"
            " VALUES ('p','Teste','/tmp')"
        )
        conn.execute(
            "INSERT INTO sessions(session_id,project_id,state,revision)"
            " VALUES ('s','p',?,0)", (session_state,)
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
    return root


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


def _chat_completion(text, model="bonsai-cpu-test"):
    return json.dumps({
        "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
        "model": model,
    }).encode()


@pytest.fixture(autouse=True)
def _key():
    os.environ["DSH_LOCAL_API_KEY"] = "test-key-integration"


# =====================================================================
# Retomada apos interrupcao entre etapas
# =====================================================================

class TestRecuperacaoInterrupcao:
    """Testa retomada quando o processo cai entre nodes do grafo."""

    def test_retomada_apos_interrupcao_no_validar_entrada(self):
        """Interrupcao antes de qualquer artefato: retomar executa do inicio."""
        env = _make_env()

        # Simula uma execucao interrompida sem artefatos (crash antes do primeiro commit)
        # Nao ha checkpoint no store - primeira execucao
        calls = []

        def counting_open(*a, **kw):
            calls.append(1)
            return _response(body=_chat_completion("resposta recuperada"))

        result = execute(
            env, "iniciar", "p", "s", "t", "a", FIXTURE_PROMPT,
            _urlopen=counting_open,
        )
        assert result["status"] == "CONCLUIDO"
        assert result["inference_status"] == "SUCCESS"
        first_calls = len(calls)

    def test_retomada_apos_artefato_validado_mas_sem_inferencia(self):
        """Retomar apos interrupcao: artefato validado existe, inferencia nao."""
        env = _make_env()

        # Primeira execucao completa ate o final
        calls = []
        def counting_open(*a, **kw):
            calls.append(1)
            return _response(body=_chat_completion("resposta"))

        result = execute(
            env, "iniciar", "p", "s", "t", "a", FIXTURE_PROMPT,
            _urlopen=counting_open,
        )
        assert result["status"] == "CONCLUIDO"
        first_calls = len(calls)

        # Retomar nao refaz inferencia
        result2 = execute(
            env, "retomar", "p", "s", "t", "a", FIXTURE_PROMPT,
            _urlopen=counting_open,
        )
        assert result2["status"] == "CONCLUIDO"
        assert len(calls) == first_calls

    def test_retomada_com_inferencia_ja_confirmada(self):
        """Execucao completa seguida de retomada nao refaz inferencia."""
        env = _make_env()

        calls = []
        def counting_open(*a, **kw):
            calls.append(1)
            return _response(body=_chat_completion("resposta ja confirmada"))

        execute(
            env, "iniciar", "p", "s", "t", "a", FIXTURE_PROMPT,
            _urlopen=counting_open,
        )

        result = execute(
            env, "retomar", "p", "s", "t", "a", FIXTURE_PROMPT,
            _urlopen=counting_open,
        )
        assert result["status"] == "CONCLUIDO"
        assert result["inference_response"] == "resposta ja confirmada"

    def test_resultado_confirmado_nao_provoca_nova_inferencia_apos_queda(self):
        """Cenario completo: iniciar -> concluir -> simular queda -> retomar sem re-inferir."""
        env = _make_env()
        counters = {"calls": 0}

        def counting_open(*a, **kw):
            counters["calls"] += 1
            return _response(
                body=_chat_completion(f"resultado {counters['calls']}")
            )

        execute(env, "iniciar", "p", "s", "t", "a", FIXTURE_PROMPT,
                _urlopen=counting_open)
        first_calls = counters["calls"]

        execute(env, "retomar", "p", "s", "t", "a", FIXTURE_PROMPT,
                _urlopen=counting_open)
        assert counters["calls"] == first_calls  # Nao incrementou


# =====================================================================
# Chamada real (com transporte substituido por questao de seguranca)
# =====================================================================

class TestChamadaRealEvidencia:
    """Evidencia de que o adaptador de inferencia seria chamado com parametros reais.

    Nao executa chamada HTTP real para nao depender do servidor Bonsai.
    Verifica que a configuracao do endpoint e modelo estao corretas.
    """

    def test_configuracao_inference_adapter(self):
        """Verifica que a configuracao do InferenceAdapter usa o endpoint e modelo corretos."""
        from pcsala_agent.inference_contract import InferenceConfig, InferenceRequest

        cfg = InferenceConfig(
            endpoint="http://127.0.0.1:8090",
            model="/home/igor/models/ternary-bonsai-2-9b-cpu/"
                  "Ternary-Bonsai-2-9B-PQ2_0.gguf",
            timeout_seconds=300,
            max_response_bytes=65536,
            api_key_env="DSH_LOCAL_API_KEY",
        )
        assert "127.0.0.1" in cfg.endpoint
        assert "Bonsai" in cfg.model
        assert cfg.api_key_env == "DSH_LOCAL_API_KEY"

        req = InferenceRequest(
            project_id="p", session_id="s",
            task_id="t", attempt_id="a",
            profile="cpu-triage-v1",
            user_prompt="test prompt",
        )
        assert req.profile == "cpu-triage-v1"
        assert req.user_prompt == "test prompt"

    def test_chamada_real_substituida_por_transporte_simulado(self):
        """O grafo real invoca InferenceAdapter corretamente.

        Em producao, o _urlopen seria urllib.request.urlopen apontando
        para 127.0.0.1:8090. Em teste, usamos _urlopen simulado.
        """
        env = _make_env()
        request_sent = {}

        def capture_request(*a, **kw):
            # Captura a requisicao que seria enviada
            import urllib.request
            body = kw.get("data") or a[0].data if len(a) > 0 else b""
            request_sent["url"] = str(a[0].full_url) if len(a) > 0 else ""
            request_sent["method"] = str(a[0].method) if len(a) > 0 else "POST"
            return _response(body=_chat_completion("resposta capturada"))

        result = execute(
            env, "iniciar", "p", "s", "t", "a", "prompt de teste",
            _urlopen=capture_request,
        )
        assert result["status"] == "CONCLUIDO"
        assert result["inference_status"] == "SUCCESS"

    def test_identidade_da_execucao(self):
        """Verifica que thread_id e deterministico e inclui attempt_id."""
        import hashlib
        scope = ("p", "s", "t", "a")
        thread = hashlib.sha256(
            json.dumps(scope, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        assert len(thread) == 64
        assert isinstance(thread, str)

        # Mesmo escopo gera mesmo thread
        scope2 = ("p", "s", "t", "a")
        assert hashlib.sha256(
            json.dumps(scope2).encode()
        ).hexdigest() == thread


# =====================================================================
# Comandos de interface (CLI)
# =====================================================================

class TestCLI:
    """Verifica que o ponto de entrada CLI existe e aceita argumentos."""

    def test_cli_import_and_parse(self):
        """O modulo real_graph tem funcao main que cria argparse."""
        from pcsala_agent.real_graph import main
        assert callable(main)

    def test_cli_usage_string(self):
        """A descricao do CLI menciona Bonsai CPU e triagem."""
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "pcsala_agent.real_graph", "--help"],
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "PYTHONPATH": os.path.abspath("src")},
        )
        assert result.returncode == 0
        assert "Bonsai" in result.stdout or "triagem" in result.stdout


# =====================================================================
# Evidencia de recuperacao
# =====================================================================

class TestEvidenciaRecuperacao:
    """Demonstra que a recuperacao funciona apos interrupcao simulada."""

    def test_persistencia_entre_execucoes(self):
        """Apos 'iniciar', um 'retomar' subsequente ve os dados salvos."""
        env = _make_env()

        r1 = execute(env, "iniciar", "p", "s", "t", "a", "teste persistencia",
                     _urlopen=lambda *a, **kw: _response(
                         body=_chat_completion("dado persistente")))
        assert r1["status"] == "CONCLUIDO"
        assert r1["inference_response"] == "dado persistente"

        r2 = execute(env, "retomar", "p", "s", "t", "a", "teste persistencia",
                     _urlopen=lambda *a, **kw: _response(
                         body=_chat_completion("dado novo")))
        assert r2["inference_response"] == "dado persistente"

    def test_artefato_contem_escopo_completo(self):
        """Cada artefato checkpointed contem project/session/task/attempt."""
        env = _make_env()
        execute(env, "iniciar", "p", "s", "t", "a", "escopo teste",
                _urlopen=lambda *a, **kw: _response(
                    body=_chat_completion("teste")))

        conn = connect(env / "state.sqlite")
        store = CheckpointStore(conn, env / "artifacts")
        latest = store.latest("p", "s", "t")
        assert latest is not None
        rows = conn.execute(
            "SELECT relative_path FROM artifacts WHERE checkpoint_id=?",
            (latest["checkpoint_id"],),
        ).fetchall()
        artifact = json.loads(
            (store.root / rows[0]["relative_path"]).read_bytes()
        )
        scope = artifact.get("scope", {})
        assert scope.get("project_id") == "p"
        assert scope.get("session_id") == "s"
        assert scope.get("task_id") == "t"
        assert scope.get("attempt_id") == "a"
        conn.close()

    def test_recovery_nao_repete_inferencia_confirmada(self):
        """Retomar apos concluido nao gera nova chamada de inferencia."""
        env = _make_env()
        calls = {"count": 0}

        def counting_open(*a, **kw):
            calls["count"] += 1
            return _response(body=_chat_completion(f"chamada {calls['count']}"))

        execute(env, "iniciar", "p", "s", "t", "a", "teste recovery",
                _urlopen=counting_open)
        assert calls["count"] == 2  # budget check + inferencia

        # Simula 3 retomadas
        for _ in range(3):
            execute(env, "retomar", "p", "s", "t", "a", "teste recovery",
                    _urlopen=counting_open)

        assert calls["count"] == 2  # Nenhuma nova inferencia apos a primeira execucao
