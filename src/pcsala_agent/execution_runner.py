import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

from .execution_contract import ExecutionRequest, resolve_profile
from .execution_plan import ExecutionPlan, build_execution_plan
from .output_collector import CollectedOutput, OutputCollectionError, collect_output


class ExecutionRunnerError(RuntimeError):
    pass


def _prepare_workspace(plan: ExecutionPlan) -> None:
    workspace = Path(plan.workspace)
    tmp_dir = workspace.parent / "tmp"

    for directory in (workspace, tmp_dir):
        subprocess.run(
            ["sudo", "-n", "mkdir", "-p", str(directory)],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["sudo", "-n", "chmod", "0777", str(directory)],
            check=True, capture_output=True,
        )


def _chown_workspace(plan: ExecutionPlan) -> None:
    for path in (plan.workspace, str(Path(plan.workspace).parent / "tmp")):
        subprocess.run(
            ["sudo", "-n", "chown", "-R",
             "pcsala-executor:pcsala-executor", path],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["sudo", "-n", "chmod", "0700", path],
            check=True, capture_output=True,
        )


def _build_run_command(plan: ExecutionPlan) -> tuple[list[str], int | None]:
    if plan.argv:
        return list(plan.argv), None
    if plan.sandbox_argv and plan.resource_properties:
        unit = plan.unit
        cmd = [
            "/usr/bin/systemd-run",
            "--unit=" + unit,
            "--service-type=exec", "--wait", "--pipe",
        ]
        for prop in plan.resource_properties:
            cmd.append("--property=" + prop)
        cmd.extend(plan.sandbox_argv)
        return cmd, plan.output_bytes_max
    raise ExecutionRunnerError("Plano sem argv nem sandbox_argv")


def _run_sandboxed(cmd: list[str], output_limit: int, timeout: int) -> CollectedOutput:
    start = time.monotonic()
    process = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
        shell=False,
        start_new_session=True,
        close_fds=True,
    )

    def terminate():
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    return collect_output(
        process,
        terminate=terminate,
        output_limit=output_limit,
        timeout_seconds=timeout,
        started_at=start,
    )


def _snapshot_workspace(workspace: str) -> dict[str, str]:
    result = {}
    proc = subprocess.run(
        ["sudo", "-n", "find", workspace, "-type", "f"],
        capture_output=True, timeout=5,
    )
    if proc.returncode != 0:
        return result
    paths = proc.stdout.decode(errors="replace").strip().split("\n")
    for path_str in paths:
        path_str = path_str.strip()
        if not path_str:
            continue
        try:
            rel = Path(path_str).relative_to(workspace)
        except ValueError:
            continue
        proc2 = subprocess.run(
            ["sudo", "-n", "xxd", "-p", path_str],
            capture_output=True, timeout=5,
        )
        if proc2.returncode == 0:
            result[str(rel)] = proc2.stdout.decode(errors="replace").strip()
    return result


def _compute_diff(workspace: str, before: dict[str, str]) -> str:
    now = _snapshot_workspace(workspace)
    lines = []
    for path, hex_content in sorted(now.items()):
        if path not in before:
            lines.append(f"[CRIADO] {path}")
        elif before[path] != hex_content:
            lines.append(f"[ALTERADO] {path}")
    for path in sorted(before):
        if path not in now:
            lines.append(f"[REMOVIDO] {path}")
    return "\n".join(lines)


def snapshot_workspace(workspace: str) -> dict[str, str]:
    return _snapshot_workspace(workspace)


def compute_diff(workspace: str, before: dict[str, str]) -> str:
    return _compute_diff(workspace, before)


def prepare_workspace(plan: ExecutionPlan) -> str:
    _prepare_workspace(plan)
    return plan.workspace


def write_workspace_file(workspace: str, path: str, content: str) -> str:
    full = str(Path(workspace) / path)
    proc = subprocess.run(
        ["sudo", "-n", "tee", full],
        input=content.encode("utf-8"), capture_output=True,
    )
    if proc.returncode != 0:
        raise ExecutionRunnerError(
            f"Falha ao escrever {full}: {proc.stderr.decode(errors='replace')}"
        )
    subprocess.run(
        ["sudo", "-n", "chmod", "0700", full],
        check=True, capture_output=True,
    )
    return full


def run_sandboxed(cmd: list[str], output_limit: int, timeout: int = 15) -> CollectedOutput:
    return _run_sandboxed(cmd, output_limit, timeout)


def run_code_workspace(
    request: ExecutionRequest,
    script_file: str,
    *,
    plan: ExecutionPlan | None = None,
) -> dict:
    if plan is None:
        plan = build_execution_plan(request)
    plan.require_executable()

    _prepare_workspace(plan)
    _chown_workspace(plan)

    before = _snapshot_workspace(plan.workspace)

    unit = plan.unit
    resource_properties = plan.resource_properties or (
        f"User={plan.payload_user}",
        f"Group={plan.payload_user}",
        "MemoryMax=268435456",
        "MemorySwapMax=0",
        "TasksMax=32",
        "CPUQuota=50%",
        "RuntimeMaxSec=15s",
        "NoNewPrivileges=yes",
        "WorkingDirectory=/",
    )
    sandbox_argv = plan.sandbox_argv
    if not sandbox_argv:
        sandbox_argv = [
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
            "--bind", plan.workspace, "/workspace",
            "--hostname", "pcsala-sandbox",
            "--chdir", "/workspace",
        ]

    cmd = ["sudo", "-n", "/usr/bin/systemd-run",
           "--unit=" + unit,
           "--service-type=exec", "--wait", "--pipe"]
    for prop in resource_properties:
        cmd.append("--property=" + prop)
    cmd.extend(sandbox_argv)
    cmd.append("--")
    cmd.append("/usr/bin/python3")
    cmd.append("-I")
    cmd.append("-u")
    cmd.append(script_file)

    output_limit = plan.output_bytes_max

    try:
        collected = _run_sandboxed(cmd, output_limit, 15)
    except OutputCollectionError as error:
        raise ExecutionRunnerError(str(error)) from error

    diff = _compute_diff(plan.workspace, before)

    return {
        "status": collected.status,
        "exit_code": collected.returncode,
        "stdout": collected.stdout.decode("utf-8", errors="replace"),
        "stderr": collected.stderr.decode("utf-8", errors="replace"),
        "output_bytes": collected.retained_bytes,
        "elapsed_seconds": collected.elapsed_seconds,
        "workspace_diff": diff,
        "execution_unit": unit,
        "workspace": plan.workspace,
    }


def run_execution_plan(
    request: ExecutionRequest,
    *,
    plan: ExecutionPlan | None = None,
) -> dict:
    if plan is None:
        plan = build_execution_plan(request)
    plan.require_executable()

    _prepare_workspace(plan)

    before = _snapshot_workspace(plan.workspace)

    cmd, output_limit_override = _build_run_command(plan)
    output_limit = output_limit_override or plan.output_bytes_max
    timeout = 15

    try:
        collected = _run_sandboxed(["sudo", "-n"] + cmd, output_limit, timeout)
    except OutputCollectionError as error:
        raise ExecutionRunnerError(
            f"Falha de infraestrutura na execucao: {error}"
        ) from error

    diff = _compute_diff(plan.workspace, before)

    return {
        "status": collected.status,
        "exit_code": collected.returncode,
        "stdout": collected.stdout.decode("utf-8", errors="replace"),
        "stderr": collected.stderr.decode("utf-8", errors="replace"),
        "output_bytes": collected.retained_bytes,
        "elapsed_seconds": collected.elapsed_seconds,
        "workspace_diff": diff,
        "execution_unit": plan.unit,
        "workspace": plan.workspace,
    }