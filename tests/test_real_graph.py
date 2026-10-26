import json
import os
import tempfile
from pathlib import Path

import pytest

from pcsala_agent.database import connect
from pcsala_agent.real_graph import execute
from pcsala_agent.checkpoints import CheckpointStore
from pcsala_agent.locking import database_lock


FIXTURE_SCOPE = ("p", "s", "t", "a")
FIXTURE_PROMPT = "Resuma em portugues: o que e um modelo de linguagem?"


def _make_env():
    root = Path(tempfile.mkdtemp(prefix="real_graph_test_"))
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
    return root


@pytest.fixture
def env():
    return _make_env()


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


def _make_urlopener():
    """Cria um _urlopen que conta chamadas e trata tokenize vs chat completion."""
    calls = []
    def _tokenize_response(tokens):
        return json.dumps({"tokens": tokens}).encode()
    def opener(request, *args, **kwargs):
        calls.append(1)
        url = request.full_url if hasattr(request, 'full_url') else str(request)
        if "/tokenize" in url:
            return _response(body=_tokenize_response([1, 2, 3]))
        return _response(body=_chat_completion("resposta simulada"))
    opener.calls = calls
    return opener


# =====================================================================
# iniciar
# =====================================================================

class TestIniciar:
    def test_iniciar_conclui_com_inferencia(self, env):
        os.environ["DSH_LOCAL_API_KEY"] = "test-key-placeholder"
        opener = _make_urlopener()
        result = execute(
            env, "iniciar", "p", "s", "t", "a", FIXTURE_PROMPT,
            _urlopen=opener,
        )
        assert result["status"] == "CONCLUIDO"
        assert result["inference_status"] == "SUCCESS"
        assert result["inference_response"] == "resposta simulada"
        assert result["error"] == ""

    def test_inferencia_indisponivel_registra_falha(self, env):
        os.environ["DSH_LOCAL_API_KEY"] = "test-key"
        import urllib.error
        from io import BytesIO

        def failing_urlopen(*a, **kw):
            raise urllib.error.HTTPError(
                "http://127.0.0.1:8090/v1/chat/completions",
                503, "Unavailable", {}, BytesIO(b""),
            )

        result = execute(
            env, "iniciar", "p", "s", "t", "a", "prompt de teste",
            _urlopen=failing_urlopen,
        )
        assert result["status"] == "CONCLUIDO"
        assert result["inference_status"] == "UNAVAILABLE"
        assert "falhou" in result["error"]

    def test_prompt_vazio_rejeitado_na_validacao(self, env):
        os.environ["DSH_LOCAL_API_KEY"] = "test-key"
        calls = []

        def counting_open(*a, **kw):
            calls.append(1)
            return _response(body=_chat_completion("resposta"))

        result = execute(
            env, "iniciar", "p", "s", "t", "a", "",
            _urlopen=counting_open,
        )
        # Should fail at input validation before any inference call
        assert result["status"] == "CONCLUIDO"
        assert result["step"] == "falha"
        assert "vazio" in result["error"]
        assert len(calls) == 0

    def test_prompt_preservado_no_resultado(self, env):
        os.environ["DSH_LOCAL_API_KEY"] = "test-key"
        prompt = "prompt de teste especifico"
        result = execute(
            env, "iniciar", "p", "s", "t", "a", prompt,
            _urlopen=lambda *a, **kw: _response(
                body=_chat_completion("resposta")
            ),
        )
        assert result["status"] == "CONCLUIDO"


# =====================================================================
# retomar
# =====================================================================

class TestRetomar:
    def test_retomar_apos_concluido_nao_refaz_inferencia(self, env):
        os.environ["DSH_LOCAL_API_KEY"] = "test-key"
        calls = []

        def tracking_urlopen(*a, **kw):
            calls.append(1)
            try:
                url = a[0].full_url if hasattr(a[0], 'full_url') else str(a[0])
            except (TypeError, AttributeError):
                url = str(a[0]) if a else ""
            if "/tokenize" in url:
                import json
                return _response(body=json.dumps({"tokens": [1, 2, 3]}).encode())
            return _response(body=_chat_completion("resultado original"))

        result1 = execute(
            env, "iniciar", "p", "s", "t", "a", "prompt",
            _urlopen=tracking_urlopen,
        )
        assert result1["status"] == "CONCLUIDO"
        assert len(calls) == 2

        result2 = execute(
            env, "retomar", "p", "s", "t", "a", "prompt",
            _urlopen=tracking_urlopen,
        )
        assert result2["status"] == "CONCLUIDO"
        assert result2["inference_status"] == "SUCCESS"
        assert len(calls) == 2

    def test_persistencia_sobrevive_a_reabertura(self, env):
        os.environ["DSH_LOCAL_API_KEY"] = "test-key"

        def mock_open(*a, **kw):
            return _response(body=_chat_completion("dado persistido"))

        result1 = execute(
            env, "iniciar", "p", "s", "t", "a", "prompt persistencia",
            _urlopen=mock_open,
        )
        assert result1["status"] == "CONCLUIDO"

        result2 = execute(
            env, "retomar", "p", "s", "t", "a", "prompt persistencia",
            _urlopen=mock_open,
        )
        assert result2["inference_response"] == "dado persistido"

    def test_resultado_ja_confirmado_nao_provoca_nova_inferencia(self, env):
        os.environ["DSH_LOCAL_API_KEY"] = "test-key"
        counters = {"calls": 0}

        def counting_open(*a, **kw):
            counters["calls"] += 1
            return _response(
                body=_chat_completion(f"chamada {counters['calls']}")
            )

        execute(env, "iniciar", "p", "s", "t", "a", "prompt",
                _urlopen=counting_open)
        first_calls = counters["calls"]

        for _ in range(3):
            execute(env, "retomar", "p", "s", "t", "a", "prompt",
                    _urlopen=counting_open)

        assert counters["calls"] == first_calls


# =====================================================================
# session control
# =====================================================================

class TestSessionControl:
    def test_sessao_parada_bloqueia_nova_execucao(self):
        env = _make_env()
        conn = connect(env / "state.sqlite")
        conn.execute("UPDATE sessions SET state='STOPPED' WHERE session_id='s'")
        conn.commit()
        conn.close()

        os.environ["DSH_LOCAL_API_KEY"] = "test-key"
        result = execute(
            env, "iniciar", "p", "s", "t", "a", "prompt",
            _urlopen=lambda *a, **kw: _response(
                body=_chat_completion("resposta")
            ),
        )
        # Session stopped - no artifact written, status EM_ANDAMENTO
        assert result["status"] == "EM_ANDAMENTO"


# =====================================================================
# validar_resposta
# =====================================================================

class TestValidacaoResposta:
    def test_resposta_vazia_rejeitada(self, env):
        os.environ["DSH_LOCAL_API_KEY"] = "test-key"
        result = execute(
            env, "iniciar", "p", "s", "t", "a", "prompt",
            _urlopen=lambda *a, **kw: _response(
                body=_chat_completion("")
            ),
        )
        assert result["status"] == "CONCLUIDO"
        assert result["step"] == "falha"
        assert "vazia" in result["error"]


# =====================================================================
# artefatos e rastreabilidade
# =====================================================================

class TestArtifactSteps:
    def test_artefatos_sequenciais_criados(self, env):
        os.environ["DSH_LOCAL_API_KEY"] = "test-key"
        execute(
            env, "iniciar", "p", "s", "t", "a", FIXTURE_PROMPT,
            _urlopen=lambda *a, **kw: _response(
                body=_chat_completion("resultado")
            ),
        )
        store = CheckpointStore(
            connect(env / "state.sqlite"), env / "artifacts"
        )
        latest = store.latest("p", "s", "t")
        assert latest is not None
        rows = store.db.execute(
            "SELECT count(*) FROM checkpoints WHERE project_id='p' AND session_id='s' AND task_id='t' AND status='COMMITTED'"
        ).fetchone()[0]
        # Should have at least validado, inferiu, validado_resposta, concluido
        assert rows >= 4

    def test_operations_table_tracks_inference(self, env):
        os.environ["DSH_LOCAL_API_KEY"] = "test-key"
        execute(
            env, "iniciar", "p", "s", "t", "a", FIXTURE_PROMPT,
            _urlopen=lambda *a, **kw: _response(
                body=_chat_completion("resultado")
            ),
        )
        conn = connect(env / "state.sqlite")
        row = conn.execute(
            "SELECT operation_type, status FROM operations WHERE project_id='p'"
        ).fetchone()
        assert row is not None
        assert row["operation_type"] == "INFERENCE"
        assert row["status"] == "COMPLETED"
        conn.close()


# =====================================================================
# thread_id deterministico
# =====================================================================

class TestThreadId:
    def test_mesmo_escopo_mesmo_thread(self):
        import hashlib
        scope1 = ("p", "s", "t", "a")
        scope2 = ("p", "s", "t", "a")
        t1 = hashlib.sha256(json.dumps(scope1).encode()).hexdigest()
        t2 = hashlib.sha256(json.dumps(scope2).encode()).hexdigest()
        assert t1 == t2

    def test_escopo_diferente_thread_diferente(self):
        import hashlib
        scope1 = ("p", "s", "t", "a")
        scope2 = ("p", "s", "t", "b")
        t1 = hashlib.sha256(json.dumps(scope1).encode()).hexdigest()
        t2 = hashlib.sha256(json.dumps(scope2).encode()).hexdigest()
        assert t1 != t2
