import pytest

from pcsala_agent.output_probe import run_output_probe

def test_success_and_streams():
    result = run_output_probe("success", timeout_seconds=5)
    assert result.status == "SUCCESS"
    assert result.returncode == 0
    assert result.stdout == b"OK\n"
    assert result.stderr == b"NOTE\n"
    assert result.retained_bytes == 8

def test_command_error():
    result = run_output_probe("error", timeout_seconds=5)
    assert result.status == "COMMAND_ERROR"
    assert result.returncode == 7
    assert result.stderr == b"ERROR\n"

def test_binary_output_preserved():
    result = run_output_probe("binary", timeout_seconds=5)
    assert result.status == "SUCCESS"
    assert result.stdout == bytes([0, 255, 254])

def test_exact_limit_is_not_overflow():
    result = run_output_probe("exact", timeout_seconds=5)
    assert result.status == "SUCCESS"
    assert result.retained_bytes == 65536

@pytest.mark.parametrize("scenario", [
    "stdout_flood", "stderr_flood", "both_flood",
])
def test_shared_output_limit(scenario):
    result = run_output_probe(
        scenario, output_limit=5000, timeout_seconds=5,
    )
    assert result.status == "OUTPUT_LIMIT"
    assert result.retained_bytes == 5000
    assert result.returncode != 0

@pytest.mark.parametrize("scenario", ["sleep", "inherited_pipe"])
def test_timeout_including_inherited_pipes(scenario):
    result = run_output_probe(scenario, timeout_seconds=0.5)
    assert result.status == "TIMEOUT"
    assert result.elapsed_seconds < 5
    assert result.retained_bytes == 0

@pytest.mark.parametrize("value", [0, -1, 65537, True, "100"])
def test_invalid_output_limit(value):
    with pytest.raises(ValueError):
        run_output_probe("success", output_limit=value)

@pytest.mark.parametrize("value", [
    0, -1, 16, True, "1", float("inf"), float("nan"),
])
def test_invalid_timeout(value):
    with pytest.raises(ValueError):
        run_output_probe("success", timeout_seconds=value)

@pytest.mark.parametrize("scenario", [
    "shell", "pytest", "/bin/sh", "", None,
])
def test_unknown_scenario(scenario):
    with pytest.raises(ValueError):
        run_output_probe(scenario)

def test_repeated_probe_after_overflow():
    assert run_output_probe(
        "stdout_flood", output_limit=1, timeout_seconds=5,
    ).status == "OUTPUT_LIMIT"
    assert run_output_probe(
        "success", timeout_seconds=5,
    ).status == "SUCCESS"
