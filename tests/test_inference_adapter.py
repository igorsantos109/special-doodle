import json
import urllib.error
from io import BytesIO

import pytest

from pcsala_agent.inference_adapter import (
    InferenceAdapter,
    InferenceEndpointError,
)
from pcsala_agent.inference_contract import (
    InferenceConfig,
    InferenceRequest,
)


def make_request(**overrides):
    return InferenceRequest(
        project_id="p",
        session_id="s",
        task_id="t",
        attempt_id="a",
        profile="cpu-triage-v1",
        user_prompt="teste",
        **overrides,
    )


def _response(status=200, body=None, headers=None):
    """Retorna um objeto simulando HTTPResponse."""

    class FakeResponse:
        def __init__(self):
            self.status = status
            self.body = body if body is not None else b""
            self._headers = headers or {}

        def read(self, n=-1):
            return self.body[:n] if n >= 0 else self.body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    return FakeResponse()


def _chat_completion(text, model="test-model"):
    return json.dumps({
        "id": "test",
        "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
        "model": model,
        "usage": {"total_tokens": 10},
    }).encode()


class TestValidResponse:
    def test_preserves_scope(self):
        req = make_request()
        adapter = InferenceAdapter(InferenceConfig())
        mock = lambda *a, **kw: _response(body=_chat_completion("ok"))
        resp = adapter.query(req, _urlopen=mock)
        assert resp.status == "SUCCESS"
        assert resp.request == req
        assert resp.text == "ok"
        assert resp.model == "test-model"
        assert resp.output_bytes > 0

    def test_system_prompt_included(self):
        req = make_request(system_prompt="Seja util")
        adapter = InferenceAdapter(InferenceConfig())
        captured = {}

        def mock(req_obj, **kw):
            body = json.loads(req_obj.data)
            captured["messages"] = body["messages"]
            return _response(body=_chat_completion("resposta"))

        adapter.query(req, _urlopen=mock)
        assert captured["messages"] == [
            {"role": "system", "content": "Seja util"},
            {"role": "user", "content": "teste"},
        ]

    def test_empty_config_model_is_sent(self):
        req = make_request()
        adapter = InferenceAdapter(InferenceConfig(model="cfg-model"))
        captured = {}

        def mock(req_obj, **kw):
            captured["model"] = json.loads(req_obj.data)["model"]
            return _response(body=_chat_completion("ok"))

        adapter.query(req, _urlopen=mock)
        assert captured["model"] == "cfg-model"


class TestUnavailable:
    def test_http_error_is_unavailable(self):
        req = make_request()
        adapter = InferenceAdapter(InferenceConfig())

        def mock(*a, **kw):
            raise urllib.error.HTTPError(
                "http://127.0.0.1:8080/v1/chat/completions",
                503, "Service Unavailable", {}, BytesIO(b"overload"),
            )

        resp = adapter.query(req, _urlopen=mock)
        assert resp.status == "UNAVAILABLE"
        assert resp.text == ""

    def test_url_error_is_unavailable(self):
        req = make_request()
        adapter = InferenceAdapter(InferenceConfig())

        def mock(*a, **kw):
            raise urllib.error.URLError("connection refused")

        resp = adapter.query(req, _urlopen=mock)
        assert resp.status == "UNAVAILABLE"
        assert resp.text == ""


class TestTimeout:
    def test_timeout_returns_timeout_status(self):
        req = make_request()
        adapter = InferenceAdapter(InferenceConfig(timeout_seconds=1))

        def mock(*a, **kw):
            raise TimeoutError("timed out")

        resp = adapter.query(req, _urlopen=mock)
        assert resp.status == "TIMEOUT"


class TestInvalidResponse:
    def test_response_exceeds_limit(self):
        req = make_request()
        adapter = InferenceAdapter(
            InferenceConfig(max_response_bytes=10)
        )

        def mock(*a, **kw):
            return _response(body=b"x" * 20)

        resp = adapter.query(req, _urlopen=mock)
        assert resp.status == "INVALID_RESPONSE"

    def test_invalid_json(self):
        req = make_request()

        adapter = InferenceAdapter(InferenceConfig())

        def mock(*a, **kw):
            return _response(body=b"not json")

        resp = adapter.query(req, _urlopen=mock)
        assert resp.status == "INVALID_RESPONSE"

    def test_missing_choices_key(self):
        req = make_request()
        adapter = InferenceAdapter(InferenceConfig())

        def mock(*a, **kw):
            return _response(body=json.dumps({"id": "x"}).encode())

        resp = adapter.query(req, _urlopen=mock)
        assert resp.status == "INVALID_RESPONSE"

    def test_content_is_not_text(self):
        req = make_request()
        adapter = InferenceAdapter(InferenceConfig())

        def mock(*a, **kw):
            return _response(body=json.dumps({
                "choices": [{"message": {"content": {"nested": True}}}],
            }).encode())

        resp = adapter.query(req, _urlopen=mock)
        assert resp.status == "INVALID_RESPONSE"

    def test_tool_calls_rejected(self):
        req = make_request()
        adapter = InferenceAdapter(InferenceConfig())

        def mock(*a, **kw):
            return _response(body=json.dumps({
                "choices": [{
                    "message": {"content": "tool time"},
                    "finish_reason": "tool_calls",
                }],
                "tool_calls": [{"id": "call_1"}],
            }).encode())

        resp = adapter.query(req, _urlopen=mock)
        assert resp.status == "INVALID_RESPONSE"


class TestEndpointValidation:
    def test_rejects_non_local(self):
        req = make_request()
        adapter = InferenceAdapter(
            InferenceConfig(endpoint="http://192.168.1.1:8080")
        )

        with pytest.raises(InferenceEndpointError):
            adapter.query(req)

    def test_rejects_https(self):
        req = make_request()
        adapter = InferenceAdapter(
            InferenceConfig(endpoint="https://127.0.0.1:8080")
        )

        with pytest.raises(InferenceEndpointError):
            adapter.query(req)


class TestConfigDefaults:
    def test_default_endpoint_is_localhost(self):
        cfg = InferenceConfig()
        assert "127.0.0.1" in cfg.endpoint
        assert cfg.timeout_seconds == 60
        assert cfg.max_response_bytes == 65536