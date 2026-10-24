import json

import pytest

from pcsala_agent.context_budget import (
    AUX_BUDGET, AUX_CONTEXT, AUX_INPUT_BUDGET,
    PRIMARY_BUDGET, PRIMARY_CONTEXT, PRIMARY_INPUT_BUDGET,
    BudgetCheck, check_budget,
    count_tokens,
    _clean_compression_output,
    FACTS_TO_PRESERVE_TEMPLATE,
    COMPRESSION_PROMPT,
    ContextOverflow, CompressionError, TokenizerError,
)


def _make_tokenize_response(body):
    class FakeResponse:
        def read(self, limit=None):
            return json.dumps(body).encode("utf-8")
    return FakeResponse()


def test_budget_constants():
    assert PRIMARY_CONTEXT == 64000
    assert AUX_CONTEXT == 32768
    assert PRIMARY_BUDGET < PRIMARY_CONTEXT
    assert AUX_BUDGET < AUX_CONTEXT
    assert PRIMARY_INPUT_BUDGET > 0
    assert AUX_INPUT_BUDGET > 0


def _make_tokenize_response(body):
    import json
    class FakeResponse:
        def read(self, limit=None):
            return json.dumps(body).encode("utf-8")
    return FakeResponse()


def test_count_tokens_mocked():
    fake = _make_tokenize_response({"tokens": [1, 2, 3]})
    assert count_tokens("test", _urlopen=lambda *a, **kw: fake) == 3


def test_count_tokens_empty():
    fake = _make_tokenize_response({"tokens": []})
    assert count_tokens("", _urlopen=lambda *a, **kw: fake) == 0


def test_count_tokens_error_raises():
    def error_opener(*a, **kw):
        import urllib.error
        raise urllib.error.HTTPError("http://x", 500, "err", {}, None)
    with pytest.raises(TokenizerError):
        count_tokens("test", _urlopen=error_opener)


def test_budget_check_under():
    fake = _make_tokenize_response({"tokens": [1] * 5})
    bc = check_budget("hello", budget=1000, _urlopen=lambda *a, **kw: fake)
    assert bc.over_budget is False
    assert bc.deficit == 0


def test_budget_check_over():
    fake = _make_tokenize_response({"tokens": [1] * 200})
    bc = check_budget("X" * 1000, budget=100, _urlopen=lambda *a, **kw: fake)
    assert bc.over_budget


def test_budget_check_ratio():
    fake = _make_tokenize_response({"tokens": [1] * 7})
    bc = check_budget("hello world", budget=100, _urlopen=lambda *a, **kw: fake)
    assert bc.ratio > 0


def test_clean_compression_output():
    raw = "thinking\nresponse\nOBJECTIVO: teste\nDECISOES: nenhuma\n"
    cleaned = _clean_compression_output(raw)
    assert "thinking" not in cleaned
    assert "response" not in cleaned
    assert "OBJECTIVO" in cleaned
    assert "DECISOES" in cleaned


def test_clean_preserves_facts():
    raw = "DECISOES: usar 27B\nCAMINHOS: /home/teste\n"
    cleaned = _clean_compression_output(raw)
    assert "DECISOES" in cleaned
    assert "CAMINHOS" in cleaned


def test_clean_empty_returns_empty():
    assert _clean_compression_output("") == ""
    assert _clean_compression_output("  \n  ") == ""


def test_facts_template_has_required_fields():
    required = ["objective", "decisions", "authorizations",
                 "prohibitions", "paths", "identifiers",
                 "results", "errors", "next_action"]
    for field in required:
        assert ("{" + field + "}") in FACTS_TO_PRESERVE_TEMPLATE


def test_compression_prompt_has_facts_instruction():
    assert "PRESERVAR" in COMPRESSION_PROMPT
    assert "Objectivo" in COMPRESSION_PROMPT
    assert "Decisoes" in COMPRESSION_PROMPT or "Decisões" in COMPRESSION_PROMPT
    assert "Proibicoes" in COMPRESSION_PROMPT or "Proibições" in COMPRESSION_PROMPT
    assert "Caminhos" in COMPRESSION_PROMPT
    assert "Erros" in COMPRESSION_PROMPT
    assert "Proxima accao" in COMPRESSION_PROMPT