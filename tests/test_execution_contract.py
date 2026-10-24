import pytest
from pydantic import ValidationError

from pcsala_agent.execution_contract import (
    ExecutionRequest, ExecutionResult, resolve_profile,
)

def payload():
    return {
        "project_id": "p1",
        "session_id": "s1",
        "task_id": "t1",
        "attempt_id": "a1",
        "profile": "diagnostic-v1",
    }

def test_request_roundtrip():
    request = ExecutionRequest(**payload())
    assert ExecutionRequest.model_validate_json(
        request.model_dump_json()
    ) == request

@pytest.mark.parametrize("field", [
    "command", "argv", "user", "group", "cwd", "env",
    "mounts", "network", "systemd_properties", "memory_bytes",
])
def test_extra_fields_rejected(field):
    with pytest.raises(ValidationError):
        ExecutionRequest(**{**payload(), field: "nao-permitido"})

@pytest.mark.parametrize("value", [
    "", "../p", "/tmp/p", "p/q", "p\\q", "p\n",
    "p;id", "p q", "á", "a" * 65, 123, True,
])
def test_invalid_identifiers(value):
    with pytest.raises(ValidationError):
        ExecutionRequest(**{**payload(), "project_id": value})

@pytest.mark.parametrize("profile", ["shell", "pytest", "", None])
def test_unknown_profiles(profile):
    with pytest.raises(ValidationError):
        ExecutionRequest(**{**payload(), "profile": profile})

def test_fixed_profile():
    profile = resolve_profile(ExecutionRequest(**payload()))
    assert profile.argv == (
        "/usr/bin/python3", "-I", "-u", "-c",
        "print('PCSALA_DIAGNOSTIC_V1')",
    )
    assert profile.memory_bytes == 256 * 1024 * 1024
    assert profile.swap_bytes == 0
    assert profile.tasks_max == 32
    assert profile.cpu_percent == 50
    assert profile.runtime_seconds == 15
    assert profile.network == "disabled"

def test_models_frozen():
    request = ExecutionRequest(**payload())
    with pytest.raises(ValidationError):
        request.profile = "diagnostic-v1"
    profile = resolve_profile(request)
    with pytest.raises(ValidationError):
        profile.cpu_percent = 100

@pytest.mark.parametrize("status,code", [
    ("SUCCESS", 0), ("COMMAND_ERROR", 1),
    ("TIMEOUT", None), ("OOM", None),
    ("OUTPUT_LIMIT", None), ("STORAGE_LIMIT", None),
    ("INFRA_ERROR", None),
])
def test_valid_results(status, code):
    result = ExecutionResult(
        request=ExecutionRequest(**payload()),
        status=status, exit_code=code, output_bytes=0,
    )
    assert result.status == status

@pytest.mark.parametrize("status,code", [
    ("SUCCESS", None), ("SUCCESS", 1),
    ("COMMAND_ERROR", 0), ("COMMAND_ERROR", None),
    ("TIMEOUT", 0), ("OOM", 137),
])
def test_inconsistent_results(status, code):
    with pytest.raises(ValidationError):
        ExecutionResult(
            request=ExecutionRequest(**payload()),
            status=status, exit_code=code, output_bytes=0,
        )

@pytest.mark.parametrize("size", [-1, 65537, "12", True])
def test_output_size_validation(size):
    with pytest.raises(ValidationError):
        ExecutionResult(
            request=ExecutionRequest(**payload()),
            status="SUCCESS", exit_code=0, output_bytes=size,
        )
