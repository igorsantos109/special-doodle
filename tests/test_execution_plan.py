import dataclasses
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from pcsala_agent.execution_contract import ExecutionRequest, resolve_profile
from pcsala_agent.execution_plan import build_execution_plan

def request(**changes):
    data = dict(
        project_id="p1", session_id="s1", task_id="t1",
        attempt_id="a1", profile="diagnostic-v1",
    )
    data.update(changes)
    return ExecutionRequest(**data)

def test_deterministic_and_derived():
    plan = build_execution_plan(request())
    assert plan == build_execution_plan(request())
    assert plan.workspace == (
        "/var/lib/pcsala-executor/jobs/p1/s1/t1/a1/workspace"
    )
    assert plan.unit.startswith("pcsala-exec-")
    assert plan.unit.endswith(".service")

@pytest.mark.parametrize("field", [
    "project_id", "session_id", "task_id", "attempt_id",
])
def test_scope_changes_plan(field):
    first = build_execution_plan(request())
    second = build_execution_plan(request(**{field: "outro"}))
    assert first.unit != second.unit
    assert first.workspace != second.workspace

def test_fixed_command_and_no_shell():
    req = request()
    plan = build_execution_plan(req)
    assert plan.shell is False
    assert plan.argv[0] == "/usr/bin/systemd-run"
    assert plan.argv[plan.argv.index("--") + 1:] == resolve_profile(req).argv
    for forbidden in ("sudo", "/usr/bin/sudo", "/bin/sh", "/usr/bin/sh"):
        assert forbidden not in plan.argv

@pytest.mark.parametrize("prop", [
    "User=pcsala-executor", "Group=pcsala-executor",
    "MemoryMax=268435456", "MemorySwapMax=0",
    "TasksMax=32", "CPUQuota=50%", "RuntimeMaxSec=15s",
    "TimeoutStopSec=2s", "KillMode=control-group",
    "OOMPolicy=kill", "NoNewPrivileges=yes", "WorkingDirectory=/",
])
def test_required_property(prop):
    assert "--property=" + prop in build_execution_plan(request()).argv

@pytest.mark.parametrize("option", [
    "--unshare-user", "--unshare-net", "--unshare-pid",
    "--unshare-ipc", "--unshare-uts",
    "--die-with-parent", "--new-session", "--clearenv",
])
def test_required_namespace_and_environment_options(option):
    assert option in build_execution_plan(request()).argv

def test_mount_allowlist_and_no_fallback():
    plan = build_execution_plan(request())
    argv = plan.argv
    mounts = [
        argv[i:i + 3] for i, item in enumerate(argv)
        if item in ("--bind", "--ro-bind", "--dev-bind")
    ]
    assert mounts == [
        ("--ro-bind", "/usr", "/usr"),
        ("--ro-bind", "/lib", "/lib"),
        ("--ro-bind", "/lib64", "/lib64"),
        ("--bind", plan.workspace, "/workspace"),
    ]
    assert "--share-net" not in argv
    assert "--unshare-user-try" not in argv

def test_environment_not_inherited(monkeypatch):
    monkeypatch.setenv("PCSALA_TEST_SECRET", "nao-transportar")
    plan = build_execution_plan(request())
    assert dict(plan.client_environment) == {
        "PATH": "/usr/bin:/usr/sbin", "LANG": "C", "LC_ALL": "C",
    }
    assert "nao-transportar" not in repr(plan)

def test_no_process_or_filesystem_calls(monkeypatch):
    req = request()
    def forbidden(*args, **kwargs):
        raise AssertionError("Efeito colateral durante planejamento")
    for name in ("run", "Popen", "call", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, name, forbidden)
    for name in ("open", "exists", "resolve", "mkdir", "stat"):
        monkeypatch.setattr(Path, name, forbidden)
    assert build_execution_plan(req).shell is False

def test_revalidates_forged_request():
    forged = ExecutionRequest.model_construct(
        project_id="../escape", session_id="s1", task_id="t1",
        attempt_id="a1", profile="diagnostic-v1", version="1",
    )
    with pytest.raises(ValidationError):
        build_execution_plan(forged)

def test_frozen_and_limits():
    plan = build_execution_plan(request())
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.workspace = "/"
    assert plan.output_bytes_max == 65536
    assert plan.workspace_bytes_max == 16777216
    assert plan.executable is True
    assert plan.argv[0] == "/usr/bin/systemd-run"

def test_require_executable_passes_for_v1():
    plan = build_execution_plan(request())
    plan.require_executable()
