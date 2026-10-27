import argparse
import json
import socket
import sys
from pathlib import Path
from urllib.parse import urlparse

from .database import connect
from .locking import database_lock, ExecutorBusy
from .migrations import migrate
from .real_graph import execute as real_execute


def _check_model_server(host="127.0.0.1", port=8080, timeout=2):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _ensure_environment(env):
    db_path = env / "state.sqlite"
    migrate(db_path)
    db = connect(db_path)
    try:
        with db:
            db.execute(
                """INSERT OR IGNORE INTO projects(project_id,name,authorized_root)
                VALUES ('p','Simulado','/referencia')"""
            )
            db.execute(
                """INSERT OR IGNORE INTO sessions
                (session_id,project_id,state,revision,api_mode)
                VALUES ('s','p','RUNNING',0,'OFFLINE')
                ON CONFLICT(session_id) DO UPDATE SET
                state=excluded.state, revision=excluded.revision"""
            )
            db.execute(
                """INSERT OR IGNORE INTO tasks
                (task_id,project_id,title,acceptance_criteria,status)
                VALUES ('t','p','Simulado','Checkpoint confirmado','RUNNING')"""
            )
            db.execute(
                """INSERT OR IGNORE INTO attempts
                (attempt_id,project_id,session_id,task_id,status)
                VALUES ('a','p','s','t','RUNNING')"""
            )
    finally:
        db.close()


def execute(env, command, project, session, task, attempt, prompt,
            _skip_health_check=False, _urlopen=None, profile="gpu-triage-v1"):
    _ensure_environment(env)
    if not _skip_health_check and not _check_model_server():
        return {
            "status": "CONCLUIDO",
            "inference_status": "UNAVAILABLE",
            "inference_response": "",
            "error": "servidor de inferencia indisponivel",
            "step": "health_check",
        }
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
            args.attempt, args.prompt, _skip_health_check=True,
            profile=args.profile,
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
