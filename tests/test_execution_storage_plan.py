import dataclasses

import pytest
from pydantic import ValidationError

from pcsala_agent.execution_contract import (
    ExecutionProfile,
    ExecutionRequest,
    StorageLimits,
    resolve_profile,
)
from pcsala_agent.execution_plan import build_execution_plan


def request(profile="diagnostic-v2", **changes):
    data = dict(
        project_id="p1", session_id="s1", task_id="t1",
        attempt_id="a1", profile=profile,
    )
    data.update(changes)
    return ExecutionRequest(**data)


def test_v2_roundtrip():
    req = request()
    assert ExecutionRequest.model_validate_json(req.model_dump_json()) == req


def test_legacy_profile_remains_legacy():
    profile = resolve_profile(request("diagnostic-v1"))
    assert profile.storage is None
    assert profile.argv[-1] == "print('PCSALA_DIAGNOSTIC_V1')"
    plan = build_execution_plan(request("diagnostic-v1"))
    assert plan.storage_strategy == "legacy-persistent-bind"
    assert plan.storage_mounts == ()
    assert plan.argv[0] == "/usr/bin/systemd-run"
    assert plan.executable is True
    plan.require_executable()


def test_v2_fixed_profile():
    profile = resolve_profile(request())
    assert profile.name == "diagnostic-v2"
    assert profile.argv[-1] == "print('PCSALA_DIAGNOSTIC_V2')"
    assert profile.storage == StorageLimits()
    assert profile.workspace_bytes_max == profile.storage.workspace_bytes


def test_v2_profile_requires_storage():
    with pytest.raises(ValidationError):
        ExecutionProfile(name="diagnostic-v2")


def test_legacy_profile_rejects_v2_storage():
    with pytest.raises(ValidationError):
        ExecutionProfile(storage=StorageLimits())


def test_profile_rejects_inconsistent_workspace_limit():
    with pytest.raises(ValidationError):
        ExecutionProfile(
            name="diagnostic-v2", storage=StorageLimits(),
            workspace_bytes_max=1,
        )


@pytest.mark.parametrize("field", [
    "storage", "workspace_bytes_max", "workspace_inodes_max",
    "tmp_bytes_max", "tmp_inodes_max", "mount_namespace",
])
def test_request_cannot_choose_storage(field):
    data = request().model_dump()
    data[field] = 1
    with pytest.raises(ValidationError):
        ExecutionRequest(**data)


def test_limits_are_fixed_strict_and_frozen():
    with pytest.raises(ValidationError):
        StorageLimits(tmp_bytes=1)
    with pytest.raises(ValidationError):
        StorageLimits(workspace_inodes="4096")
    limits = StorageLimits()
    with pytest.raises(ValidationError):
        limits.tmp_inodes = 2


def test_v2_has_no_complete_execution_command():
    plan = build_execution_plan(request())
    assert plan.argv == ()
    assert plan.executable is True
    plan.require_executable()
    assert plan.sandbox_argv[0] == "/usr/bin/bwrap"
    assert "--tmpfs" not in plan.sandbox_argv
    assert "/usr/bin/systemd-run" not in plan.sandbox_argv


def test_v2_declares_preparation_without_root_command():
    plan = build_execution_plan(request())
    assert plan.privileged_preparation_required is True
    assert plan.mount_namespace == "private"
    assert plan.payload_user == "pcsala-executor"
    assert "User=pcsala-executor" in plan.resource_properties
    assert "Group=pcsala-executor" in plan.resource_properties
    assert "User=root" not in plan.resource_properties
    assert plan.storage_strategy == "private-tmpfs"


def test_v2_exact_mount_limits():
    plan = build_execution_plan(request())
    workspace, temporary = plan.storage_mounts
    assert (workspace.source, workspace.target) == (
        plan.workspace, "/workspace",
    )
    assert workspace.bytes_max == 16777216
    assert workspace.inodes_max == 4096
    assert temporary.source == (
        "/var/lib/pcsala-executor/jobs/p1/s1/t1/a1/tmp"
    )
    assert temporary.target == "/tmp"
    assert temporary.bytes_max == 4194304
    assert temporary.inodes_max == 1024
    for mount in plan.storage_mounts:
        assert mount.filesystem == "tmpfs"
        assert mount.options == ("nosuid", "nodev", "noexec", "mode=0700")
        with pytest.raises(dataclasses.FrozenInstanceError):
            mount.source = "/"


def test_v2_binds_only_declared_writable_sources():
    plan = build_execution_plan(request())
    argv = plan.sandbox_argv
    binds = [
        argv[i:i + 3] for i, token in enumerate(argv)
        if token == "--bind"
    ]
    assert len(binds) == 2
    assert set(binds) == {
        ("--bind", mount.source, mount.target)
        for mount in plan.storage_mounts
    }
    assert argv[argv.index("--") + 1:] == resolve_profile(request()).argv


def test_v2_declares_execution_plan_complete():
    plan = build_execution_plan(request())
    assert plan.executable is True
    plan.require_executable()
    assert plan.sandbox_argv[0] == "/usr/bin/bwrap"


def test_versions_do_not_reuse_unit_identity():
    legacy = build_execution_plan(request("diagnostic-v1"))
    current = build_execution_plan(request())
    assert legacy.unit != current.unit
    assert current == build_execution_plan(request())


def test_v2_planning_has_no_process_or_filesystem_effects(monkeypatch):
    import builtins
    import os
    import subprocess
    from pathlib import Path

    req = request()

    def forbidden(*args, **kwargs):
        raise AssertionError("Efeito colateral durante planejamento")

    with monkeypatch.context() as patch:
        for name in ("run", "Popen", "call", "check_call", "check_output"):
            patch.setattr(subprocess, name, forbidden)
        for name in ("open", "exists", "resolve", "mkdir", "stat"):
            patch.setattr(Path, name, forbidden)
        patch.setattr(builtins, "open", forbidden)
        patch.setattr(os, "system", forbidden)
        plan = build_execution_plan(req)
    assert plan.argv == ()
