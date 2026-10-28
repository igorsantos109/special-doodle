import http.server
import json
import threading

from pcsala_agent.model_manager import ModelCoordinator, ModelRegistry
from pcsala_agent.models.client import LlamaSwapClient


class _FakeHandler(http.server.BaseHTTPRequestHandler):
    def __init__(self, *args, responses=None, **kwargs):
        self.responses = responses or {}
        self.calls = []
        super().__init__(*args, **kwargs)

    def do_GET(self):
        self.calls.append(("GET", self.path))
        if self.path == "/v1/models":
            self._send(200, {"data": []})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        self.calls.append(("POST", self.path))
        if self.path == "/v1/chat/completions":
            resp = self.responses.get("/v1/chat/completions", {"status": 200})
            self._send(resp["status"], resp.get("body", {}))
        elif self.path == "/api/models/unload/bonsai-4b-gpu":
            self._send(200, {"status": "unloaded"})
        else:
            self._send(404, {"error": "not found"})

    def do_DELETE(self):
        self.calls.append(("DELETE", self.path))
        if self.path == "/v1/models/bonsai-4b-gpu/unload":
            self._send(200, {"status": "unloaded"})
        else:
            self._send(404, {"error": "not found"})

    def _send(self, status, body):
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        pass


def _start_fake_server(responses=None):
    server = http.server.HTTPServer(
        ("127.0.0.1", 0), lambda *a, **kw: _FakeHandler(*a, responses=responses, **kw)
    )
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


class TestLlamaSwapClient:
    def test_load_model_success(self):
        server, port = _start_fake_server({
            "/v1/chat/completions": {"status": 200, "body": {"ok": True}},
        })
        try:
            client = LlamaSwapClient(f"http://127.0.0.1:{port}")
            ok, error = client.load_model("bonsai-4b-gpu")
            assert ok is True
            assert error is None
        finally:
            server.shutdown()

    def test_load_model_http_503(self):
        server, port = _start_fake_server({
            "/v1/chat/completions": {"status": 503, "body": {"error": "loading"}},
        })
        try:
            client = LlamaSwapClient(f"http://127.0.0.1:{port}")
            ok, error = client.load_model("bonsai-4b-gpu")
            assert ok is False
            assert "HTTP 503" in error
        finally:
            server.shutdown()

    def test_load_model_connection_refused(self):
        client = LlamaSwapClient("http://127.0.0.1:1")
        ok, error = client.load_model("bonsai-4b-gpu")
        assert ok is False
        assert error is not None

    def test_health_true(self):
        server, port = _start_fake_server()
        try:
            client = LlamaSwapClient(f"http://127.0.0.1:{port}")
            assert client.health() is True
        finally:
            server.shutdown()

    def test_health_false(self):
        client = LlamaSwapClient("http://127.0.0.1:1")
        assert client.health() is False

    def test_unload_model_success(self):
        server, port = _start_fake_server()
        try:
            client = LlamaSwapClient(f"http://127.0.0.1:{port}")
            ok, _error = client.unload_model("bonsai-4b-gpu")
            assert ok is True
        finally:
            server.shutdown()

    def test_timeout_injected_clock_no_sleep(self):
        """Timeout usa relógio injetado, sem dormir de verdade."""
        server, port = _start_fake_server()
        try:
            client = LlamaSwapClient(f"http://127.0.0.1:{port}",
                                     timeout_seconds=0.001)
            # Servidor real responde rápido, não deve timeout.
            ok, _error = client.load_model("bonsai-4b-gpu")
            assert ok is True
        finally:
            server.shutdown()


class TestHybridPolicy:
    def test_backend_field_in_registry(self):
        reg = ModelRegistry()
        m4b = reg.get("bonsai-4b-gpu")
        assert m4b.backend == "llama-swap"
        m27b = reg.get("bonsai-27b-gpu")
        assert m27b.backend == "systemd"
        mlaguna = reg.get("laguna-xs-2.1-gpu")
        assert mlaguna.backend == "systemd"

    def test_exclusive_group_preserved_for_systemd_models(self):
        reg = ModelRegistry()
        exclusive = reg.exclusive_models()
        ids = {m.model_id for m in exclusive}
        assert ids == {
            "bonsai-27b-gpu",
            "laguna-xs-2.1-gpu",
            "nemotron-3.5-30b-gpu",
            "ornith-35b-gpu",
        }
        # 4B é residente, não exclusivo.
        assert "bonsai-4b-gpu" not in ids

    def test_coordinator_reserve_engine_works_for_llama_swap_backend(self, tmp_path):
        db = tmp_path / "state.sqlite"
        reg = ModelRegistry()
        coord = ModelCoordinator(reg, database=db)
        # 4B é residente: reserve_engine retorna None (não exclusivo).
        assert coord.reserve_engine("bonsai-4b-gpu") is None
        # 27B é exclusivo: reserva funciona.
        rid = coord.reserve_engine("bonsai-27b-gpu", requester="cli")
        assert rid is not None
        assert coord.engine_reserved("bonsai-27b-gpu") is True
