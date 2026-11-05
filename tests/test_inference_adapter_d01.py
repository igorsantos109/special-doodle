import json

from pcsala_agent.inference_adapter import InferenceAdapter
from pcsala_agent.inference_contract import InferenceConfig, InferenceRequest


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


class TimeoutOnReadResponse:
    def read(self, n=-1):
        raise TimeoutError("timed out during read")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class BodyResponse:
    def __init__(self, body):
        self.body = body

    def read(self, n=-1):
        return self.body[:n] if n >= 0 else self.body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def test_timeout_during_read_returns_timeout_status():
    req = make_request()
    adapter = InferenceAdapter(InferenceConfig())

    def mock(*a, **kw):
        return TimeoutOnReadResponse()

    resp = adapter.query(req, _urlopen=mock)
    assert resp.status == "TIMEOUT"


def test_finish_reason_length_is_not_success():
    req = make_request()
    adapter = InferenceAdapter(InferenceConfig())
    body = json.dumps({
        "choices": [{
            "message": {"content": "texto truncado"},
            "finish_reason": "length",
        }],
        "model": "test-model",
    }).encode()

    def mock(*a, **kw):
        return BodyResponse(body)

    resp = adapter.query(req, _urlopen=mock)
    assert resp.status != "SUCCESS"


def test_empty_choices_returns_invalid_response_without_exception():
    req = make_request()
    adapter = InferenceAdapter(InferenceConfig())
    body = json.dumps({"choices": []}).encode()

    def mock(*a, **kw):
        return BodyResponse(body)

    resp = adapter.query(req, _urlopen=mock)
    assert resp.status == "INVALID_RESPONSE"
