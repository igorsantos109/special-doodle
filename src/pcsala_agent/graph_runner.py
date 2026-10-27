import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from .database import connect
from .inference_profiles import get_profile
from .locking import ExecutorBusy, database_lock
from .migrations import migrate
from .real_graph import execute as real_execute


def _validate_scope(db, project, session, task, attempt):
    """Valida existência do escopo; levanta RuntimeError se algo faltar."""
    if db.execute("SELECT 1 FROM projects WHERE project_id=?", (project,)).fetchone() is None:
        raise RuntimeError(f"projeto não encontrado: {project}")
    if db.execute(
        "SELECT 1 FROM sessions WHERE session_id=? AND project_id=?",
        (session, project),
    ).fetchone() is None:
        raise RuntimeError(f"sessão não encontrada: {session}")
    if db.execute(
        "SELECT 1 FROM tasks WHERE task_id=? AND project_id=?",
        (task, project),
    ).fetchone() is None:
        raise RuntimeError(f"tarefa não encontrada: {task}")
    if db.execute(
        "SELECT 1 FROM attempts WHERE attempt_id=? AND session_id=? AND task_id=?",
        (attempt, session, task),
    ).fetchone() is None:
        raise RuntimeError(f"tentativa não encontrada: {attempt}")


def _ensure_environment(env, project, session, task, attempt):
    """Produção: apenas migra e valida escopo. Não insere dados fictícios."""
    db_path = env / "state.sqlite"
    migrate(db_path)
    db = connect(db_path)
    try:
        _validate_scope(db, project, session, task, attempt)
    finally:
        db.close()


def _check_model_server(endpoint, timeout=2):
    """Chama GET <endpoint>/health; True apenas com HTTP 200."""
    url = endpoint.rstrip("/") + "/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _unavailable_result(endpoint):
    return {
        "status": "RETRY",
        "inference_status": "UNAVAILABLE",
        "inference_response": "",
        "error": "servidor de inferencia indisponivel",
        "step": "health_check",
        "endpoint": endpoint,
    }


def execute(env, command, project, session, task, attempt, prompt,
            _skip_health_check=False, _urlopen=None, profile="gpu-triage-v1"):
    _ensure_environment(env, project, session, task, attempt)
    if not _skip_health_check:
        prof = get_profile(profile)
        if not _check_model_server(prof.endpoint):
            return _unavailable_result(prof.endpoint)
    with database_lock(env / "state.sqlite"):
        return real_execute(
            env, command, project, session, task, attempt, prompt,
            _urlopen=_urlopen, profile=profile,
        )


def main():
    parser = argparse.ArgumentParser(
        prog="pcsala-agent", description="Worker LangGraph pc-sala-agent",
    )
    parser.add_argument("command", choices=["iniciar", "retomar"])
    parser.add_argument("--root", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--attempt", required=True)
    parser.add_argument("--prompt", default="")
    parser.add_argument("--profile", default="gpu-triage-v1")
    args = parser.parse_args()
    env = Path(args.root)
    try:
        result = execute(
            env, args.command, args.project, args.session, args.task,
            args.attempt, args.prompt, profile=args.profile,
        )
    except ExecutorBusy:
        print("executor ocupado", file=sys.stderr)
        sys.exit(3)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
    print(json.dumps(result))
    sys.exit(0)


if __name__ == "__main__":
    main()
