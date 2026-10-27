import dataclasses
import hashlib

from .execution_contract import resolve_profile


@dataclasses.dataclass(frozen=True)
class ExecutionPlan:
    request_profile: str
    workspace: str
    unit: str
    argv: tuple
    sandbox_argv: tuple = ()
    shell: bool = False
    storage_strategy: str = "legacy-persistent-bind"
    storage_mounts: tuple = ()
    mount_namespace: str = "default"
    payload_user: str = "pcsala-executor"
    resource_properties: tuple = ()
    privileged_preparation_required: bool = False
    executable: bool = True
    output_bytes_max: int = 65536
    workspace_bytes_max: int = 16777216
    client_environment: dict = dataclasses.field(default_factory=dict)

    def require_executable(self):
        return self


_RESOURCE_PROPS = (
    "User=pcsala-executor", "Group=pcsala-executor",
    "MemoryMax=268435456", "MemorySwapMax=0",
    "TasksMax=32", "CPUQuota=50%", "RuntimeMaxSec=15s",
    "TimeoutStopSec=2s", "KillMode=control-group",
    "OOMPolicy=kill", "NoNewPrivileges=yes", "WorkingDirectory=/",
)
_RESOURCE_PROPERTIES = tuple(f"--property={p}" for p in _RESOURCE_PROPS)

_NAMESPACE_OPTIONS = (
    "--unshare-user", "--unshare-net", "--unshare-pid",
    "--unshare-ipc", "--unshare-uts",
    "--die-with-parent", "--new-session", "--clearenv",
)


def _workspace_path(request):
    return (
        f"/var/lib/pcsala-executor/jobs/"
        f"{request.project_id}/{request.session_id}/{request.task_id}/"
        f"{request.attempt_id}/workspace"
    )


def _unit(request, profile):
    digest = hashlib.sha256(
        f"{request.project_id}/{request.session_id}/{request.task_id}/"
        f"{request.attempt_id}/{profile.name}".encode()
    ).hexdigest()[:12]
    return f"pcsala-exec-{digest}.service"


def _v1_argv(workspace, profile):
    argv = ["/usr/bin/systemd-run"]
    argv.extend(_RESOURCE_PROPERTIES)
    argv.extend(_NAMESPACE_OPTIONS)
    argv.extend(["--ro-bind", "/usr", "/usr"])
    argv.extend(["--ro-bind", "/lib", "/lib"])
    argv.extend(["--ro-bind", "/lib64", "/lib64"])
    argv.extend(["--bind", workspace, "/workspace"])
    argv.append("--")
    argv.extend(profile.argv)
    return tuple(argv)


def _v2_sandbox_argv(workspace, tmp_dir, profile):
    argv = ["/usr/bin/bwrap"]
    argv.extend(_NAMESPACE_OPTIONS)
    argv.extend(["--ro-bind", "/usr", "/usr"])
    argv.extend(["--ro-bind", "/lib", "/lib"])
    argv.extend(["--ro-bind", "/lib64", "/lib64"])
    argv.extend(["--bind", workspace, "/workspace"])
    argv.extend(["--bind", tmp_dir, "/tmp"])
    argv.append("--")
    argv.extend(profile.argv)
    return tuple(argv)


def build_execution_plan(request):
    from .execution_contract import ExecutionRequest
    revalidated = ExecutionRequest(**request.model_dump())
    profile = resolve_profile(revalidated)
    workspace = _workspace_path(revalidated)
    unit = _unit(revalidated, profile)
    client_environment = {"PATH": "/usr/bin:/usr/sbin", "LANG": "C", "LC_ALL": "C"}
    if profile.name == "diagnostic-v1":
        argv = _v1_argv(workspace, profile)
        return ExecutionPlan(
            request_profile=profile.name,
            workspace=workspace,
            unit=unit,
            argv=argv,
            sandbox_argv=(),
            shell=False,
            storage_strategy="legacy-persistent-bind",
            storage_mounts=(),
            mount_namespace="default",
            payload_user="pcsala-executor",
            resource_properties=_RESOURCE_PROPS,
            privileged_preparation_required=False,
            executable=True,
            output_bytes_max=65536,
            workspace_bytes_max=16777216,
            client_environment=client_environment,
        )
    storage = profile.storage
    tmp_dir = workspace.rsplit("/", 1)[0] + "/tmp"
    workspace_mount = dataclasses.replace(
        StorageMountPlaceholder(
            source=workspace,
            target="/workspace",
            bytes_max=storage.workspace_bytes,
            inodes_max=storage.workspace_inodes,
            filesystem="tmpfs",
            options=("nosuid", "nodev", "noexec", "mode=0700"),
        )
    )
    tmp_mount = StorageMountPlaceholder(
        source=tmp_dir,
        target="/tmp",
        bytes_max=storage.tmp_bytes,
        inodes_max=storage.tmp_inodes,
        filesystem="tmpfs",
        options=("nosuid", "nodev", "noexec", "mode=0700"),
    )
    sandbox_argv = _v2_sandbox_argv(workspace, tmp_dir, profile)
    return ExecutionPlan(
        request_profile=profile.name,
        workspace=workspace,
        unit=unit,
        argv=(),
        sandbox_argv=sandbox_argv,
        shell=False,
        storage_strategy="private-tmpfs",
        storage_mounts=(workspace_mount, tmp_mount),
        mount_namespace="private",
        payload_user="pcsala-executor",
        resource_properties=_RESOURCE_PROPS,
        privileged_preparation_required=True,
        executable=True,
        output_bytes_max=65536,
        workspace_bytes_max=storage.workspace_bytes,
        client_environment=client_environment,
    )


@dataclasses.dataclass(frozen=True)
class StorageMountPlaceholder:
    source: str
    target: str
    bytes_max: int
    inodes_max: int
    filesystem: str
    options: tuple
