import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import PurePosixPath
from typing import Literal

from .execution_contract import ExecutionRequest, resolve_profile

ROOT = PurePosixPath("/var/lib/pcsala-executor/jobs")

@dataclass(frozen=True)
class StorageMount:
    source: str
    target: Literal["/workspace", "/tmp"]
    bytes_max: int
    inodes_max: int
    filesystem: Literal["tmpfs"] = "tmpfs"
    options: tuple[str, ...] = ("nosuid", "nodev", "noexec", "mode=0700")

@dataclass(frozen=True)
class ExecutionPlan:
    unit: str
    workspace: str
    argv: tuple[str, ...]
    client_environment: tuple[tuple[str, str], ...]
    output_bytes_max: int
    workspace_bytes_max: int
    shell: Literal[False] = False
    enforcement_pending: tuple[str, ...] = ()
    storage_strategy: Literal[
        "legacy-persistent-bind", "private-tmpfs",
    ] = "legacy-persistent-bind"
    storage_mounts: tuple[StorageMount, ...] = ()
    sandbox_argv: tuple[str, ...] = ()
    resource_properties: tuple[str, ...] = ()
    privileged_preparation_required: bool = False
    mount_namespace: Literal["unspecified", "private"] = "unspecified"
    payload_user: str = "pcsala-executor"
    executable: bool = True

    def require_executable(self) -> None:
        if not self.executable:
            raise RuntimeError("Plano nao marcado como executavel")
        if not self.argv and not self.sandbox_argv:
            raise RuntimeError("Nenhum comando de execucao definido no plano")

def _build_base_plan(request: ExecutionRequest) -> ExecutionPlan:
    """Constroi dados; nao acessa arquivos nem executa processos."""
    checked = ExecutionRequest.model_validate(request)
    profile = resolve_profile(checked)
    canonical = json.dumps(
        checked.model_dump(), sort_keys=True, separators=(",", ":")
    )
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    unit = "pcsala-exec-" + digest + ".service"
    workspace = str(
        ROOT / checked.project_id / checked.session_id
        / checked.task_id / checked.attempt_id / "workspace"
    )
    properties = (
        "User=pcsala-executor",
        "Group=pcsala-executor",
        f"MemoryMax={profile.memory_bytes}",
        f"MemorySwapMax={profile.swap_bytes}",
        f"TasksMax={profile.tasks_max}",
        f"CPUQuota={profile.cpu_percent}%",
        f"RuntimeMaxSec={profile.runtime_seconds}s",
        "TimeoutStopSec=2s",
        "KillMode=control-group",
        "OOMPolicy=kill",
        "NoNewPrivileges=yes",
        "WorkingDirectory=/",
    )
    argv = (
        "/usr/bin/systemd-run",
        "--unit=" + unit,
        "--service-type=exec", "--wait", "--pipe",
        *("--property=" + item for item in properties),
        "/usr/bin/bwrap",
        "--unshare-user", "--unshare-net", "--unshare-pid",
        "--unshare-ipc", "--unshare-uts",
        "--die-with-parent", "--new-session", "--clearenv",
        "--setenv", "PATH", "/usr/bin",
        "--setenv", "HOME", "/tmp",
        "--setenv", "LANG", "C",
        "--ro-bind", "/usr", "/usr",
        "--ro-bind", "/lib", "/lib",
        "--ro-bind", "/lib64", "/lib64",
        "--proc", "/proc", "--dev", "/dev",
        "--tmpfs", "/tmp",
        "--dir", "/etc", "--dir", "/home", "--dir", "/run",
        "--bind", workspace, "/workspace",
        "--hostname", "pcsala-sandbox",
        "--chdir", "/workspace",
        "--", *profile.argv,
    )
    return ExecutionPlan(
        unit=unit,
        workspace=workspace,
        argv=argv,
        client_environment=(
            ("PATH", "/usr/bin:/usr/sbin"),
            ("LANG", "C"), ("LC_ALL", "C"),
        ),
        output_bytes_max=profile.output_bytes_max,
        workspace_bytes_max=profile.workspace_bytes_max,
    )


def build_execution_plan(request: ExecutionRequest) -> ExecutionPlan:
    """Planejamento puro; nao prepara montagens nem habilita execucao."""
    checked = ExecutionRequest.model_validate(request)
    profile = resolve_profile(checked)
    base = _build_base_plan(checked)
    if checked.profile == "diagnostic-v1":
        return base

    limits = profile.storage
    if limits is None:
        raise ValueError("Perfil sem limites de armazenamento")

    tmp_source = str(PurePosixPath(base.workspace).parent / "tmp")
    mounts = (
        StorageMount(
            source=base.workspace,
            target="/workspace",
            bytes_max=limits.workspace_bytes,
            inodes_max=limits.workspace_inodes,
        ),
        StorageMount(
            source=tmp_source,
            target="/tmp",
            bytes_max=limits.tmp_bytes,
            inodes_max=limits.tmp_inodes,
        ),
    )

    sandbox = list(base.argv[base.argv.index("/usr/bin/bwrap"):])
    position = sandbox.index("--tmpfs")
    if sandbox[position:position + 2] != ["--tmpfs", "/tmp"]:
        raise ValueError("Estrutura inesperada do sandbox")
    sandbox[position:position + 2] = ["--bind", tmp_source, "/tmp"]

    properties = tuple(
        item.removeprefix("--property=")
        for item in base.argv
        if item.startswith("--property=")
    )

    return replace(
        base,
        argv=(),
        storage_strategy="private-tmpfs",
        storage_mounts=mounts,
        sandbox_argv=tuple(sandbox),
        resource_properties=properties,
        privileged_preparation_required=True,
        mount_namespace="private",
    )