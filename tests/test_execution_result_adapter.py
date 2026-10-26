import dataclasses

import pytest
from pydantic import ValidationError

from pcsala_agent.execution_contract import ExecutionRequest, ExecutionResult
from pcsala_agent.execution_result_adapter import (
    InvalidCollectedOutput,
    SignalTerminationUnsupported,
    adapt_collected_output,
)
from pcsala_agent.output_collector import CollectedOutput, OutputCollectionError


@pytest.fixture(params=["diagnostic-v1", "diagnostic-v2"])
def req(request):
    return ExecutionRequest(
        project_id="p", session_id="s", task_id="t",
        attempt_id="a", profile=request.param,
    )


def collected(**changes):
    values = dict(
        status="SUCCESS",
        returncode=0,
        stdout=b"OK",
        stderr=b"NOTE",
        elapsed_seconds=0.1,
    )
    values.update(changes)
    return CollectedOutput(**values)


def test_success_and_request_preservation(req):
    result = adapt_collected_output(req, collected())
    assert isinstance(result, ExecutionResult)
    assert result.request == req
    assert result.request.profile == req.profile
    assert result.status == "SUCCESS"
    assert result.exit_code == 0
    assert result.output_bytes == 6


@pytest.mark.parametrize("code", [1, 7, 255])
def test_command_error_preserves_code(req, code):
    result = adapt_collected_output(
        req, collected(status="COMMAND_ERROR", returncode=code),
    )
    assert result.status == "COMMAND_ERROR"
    assert result.exit_code == code


@pytest.mark.parametrize("status", ["TIMEOUT", "OUTPUT_LIMIT"])
@pytest.mark.parametrize("code", [0, 7, -9])
def test_control_status_has_no_contract_exit_code(req, status, code):
    result = adapt_collected_output(
        req, collected(status=status, returncode=code),
    )
    assert result.status == status
    assert result.exit_code is None
    assert result.output_bytes == 6


@pytest.mark.parametrize("code", [-1, -9, -15])
def test_signal_is_explicitly_refused_not_reclassified(req, code):
    with pytest.raises(SignalTerminationUnsupported) as caught:
        adapt_collected_output(
            req, collected(status="COMMAND_ERROR", returncode=code),
        )
    assert caught.value.returncode == code


@pytest.mark.parametrize("status,code", [
    ("SUCCESS", 1),
    ("SUCCESS", -9),
    ("COMMAND_ERROR", 0),
    ("COMMAND_ERROR", 256),
])
def test_inconsistent_status_and_code(req, status, code):
    with pytest.raises(InvalidCollectedOutput):
        adapt_collected_output(
            req, collected(status=status, returncode=code),
        )


@pytest.mark.parametrize("field,value", [
    ("status", "OOM"),
    ("status", "STORAGE_LIMIT"),
    ("status", "INFRA_ERROR"),
    ("status", None),
    ("returncode", True),
    ("returncode", "0"),
    ("returncode", None),
    ("stdout", bytearray(b"x")),
    ("stdout", "text"),
    ("stderr", memoryview(b"x")),
    ("stderr", None),
    ("elapsed_seconds", True),
    ("elapsed_seconds", "1"),
    ("elapsed_seconds", -1),
    ("elapsed_seconds", float("nan")),
    ("elapsed_seconds", float("inf")),
])
def test_dataclass_fields_are_revalidated(req, field, value):
    raw = dataclasses.replace(collected(), **{field: value})
    with pytest.raises(InvalidCollectedOutput):
        adapt_collected_output(req, raw)


@pytest.mark.parametrize("status", [
    "SUCCESS", "COMMAND_ERROR", "TIMEOUT", "OUTPUT_LIMIT",
])
def test_combined_output_boundary(req, status):
    code = 7 if status == "COMMAND_ERROR" else 0
    raw = collected(
        status=status,
        returncode=code,
        stdout=b"x" * 32768,
        stderr=b"y" * 32768,
    )
    assert adapt_collected_output(req, raw).output_bytes == 65536

    oversized = dataclasses.replace(raw, stderr=raw.stderr + b"z")
    with pytest.raises(InvalidCollectedOutput):
        adapt_collected_output(req, oversized)


def test_empty_and_binary_output(req):
    empty = collected(stdout=b"", stderr=b"")
    assert adapt_collected_output(req, empty).output_bytes == 0
    binary = collected(stdout=bytes([0, 255, 254]), stderr=b"\x00")
    assert adapt_collected_output(req, binary).output_bytes == 4


def test_error_without_partial_output_is_not_fabricated_result(req):
    error = OutputCollectionError("partial output unavailable")
    with pytest.raises(InvalidCollectedOutput):
        adapt_collected_output(req, error)


def test_alternative_object_is_refused(req):
    with pytest.raises(InvalidCollectedOutput):
        adapt_collected_output(req, collected().__dict__)


def test_forged_request_is_revalidated(req):
    data = req.model_dump()
    data["project_id"] = "../escape"
    forged = ExecutionRequest.model_construct(**data)
    with pytest.raises(ValidationError):
        adapt_collected_output(forged, collected())


def test_input_is_preserved_and_result_is_frozen(req):
    raw = collected()
    before = dataclasses.asdict(raw)
    result = adapt_collected_output(req, raw)
    assert dataclasses.asdict(raw) == before
    with pytest.raises(ValidationError):
        result.output_bytes = 0


def test_adapter_has_no_process_or_file_operations(req, monkeypatch):
    import builtins
    import os
    import subprocess
    from pathlib import Path

    raw = collected()

    def forbidden(*args, **kwargs):
        raise AssertionError("Efeito colateral no adaptador")

    with monkeypatch.context() as patch:
        for name in ("Popen", "run", "call", "check_call", "check_output"):
            patch.setattr(subprocess, name, forbidden)
        for name in ("open", "read_bytes", "write_bytes", "mkdir"):
            patch.setattr(Path, name, forbidden)
        patch.setattr(builtins, "open", forbidden)
        patch.setattr(os, "system", forbidden)
        result = adapt_collected_output(req, raw)

    assert result.status == "SUCCESS"
