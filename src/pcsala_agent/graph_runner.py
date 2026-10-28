import argparse
import json
import signal
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from .checkpoints import RecoveryRequired
from .database import connect
from .inference_profiles import get_profile
from .locking import ExecutorBusy, database_lock
from .migrations import migrate
from .real_graph import execute as real_execute
from .task_queue import reserve as queue_reserve
from .task_queue import update as queue_update


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


def _ensure_scope(database, project, session, task, attempt):
    """Cria projecto/sessao/tarefa/tentativa para uma tarefa da fila.

    A 1.1 valida o escopo em vez de o criar, por isso o worker de fila
    garante primeiro as linhas exigidas por `_validate_scope` e pela
    sessao em estado RUNNING que o grafo exige.
    """
    migrate(database)
    with database_lock(database):
        db = connect(database)
        try:
            with db:
                db.execute(
                    """INSERT OR IGNORE INTO projects
                    (project_id,name,authorized_root) VALUES (?,?,?)""",
                    (project, project, str(Path(database).parent)),
                )
                db.execute(
                    """INSERT OR IGNORE INTO sessions
                    (session_id,project_id,state,revision,api_mode)
                    VALUES (?,?,'RUNNING',0,'OFFLINE')
                    ON CONFLICT(session_id) DO UPDATE SET state='RUNNING'""",
                    (session, project),
                )
                db.execute(
                    """INSERT OR IGNORE INTO tasks
                    (task_id,project_id,title,acceptance_criteria,status)
                    VALUES (?,?,?,?,'RUNNING')""",
                    (task, project, task,
                     "Tarefa aceite automaticamente pelo worker"),
                )
                db.execute(
                    """INSERT OR IGNORE INTO attempts
                    (attempt_id,project_id,session_id,task_id,status)
                    VALUES (?,?,?,?,'RUNNING')""",
                    (attempt, project, session, task),
                )
        finally:
            db.close()


_QUEUE_SLEEP_EMPTY = 10


class QueuePollCycle:
    """Ciclo de polling da fila persistente (modo --queue-mode)."""

    def __init__(self, args):
        self._root = Path(args.root)
        self._profile = args.profile
        self._running = True
        signal.signal(signal.SIGTERM, self._shutdown)
        signal.signal(signal.SIGINT, self._shutdown)

    def _shutdown(self, signum, _frame):
        sys.stderr.write(
            f"QueuePollCycle: recebido sinal {signum}, encerrando\n")
        self._running = False

    def run(self):
        code = 0
        database = self._root / "state.sqlite"
        while self._running:
            task = queue_reserve(database)
            if task is None:
                self._wait_empty()
                continue

            queue_id = task["id"]
            attempt_id = task["attempt_id"]
            task_session = f"queue-{queue_id}"
            task_id = f"task-{queue_id}"
            prompt = task["prompt"]
            profile = task.get("profile") or self._profile

            _ensure_scope(database, "default", task_session, task_id,
                          attempt_id)

            try:
                result = execute(
                    self._root, "iniciar", "default", task_session,
                    task_id, attempt_id, prompt, profile=profile,
                )
            except (ExecutorBusy, RecoveryRequired) as error:
                queue_update(
                    database, queue_id,
                    error=f"{type(error).__name__}: {error}",
                )
                code = 1
                continue

            queue_update(
                database, queue_id,
                inference_id=result.get("inference_id", ""),
                inference_response=result.get("inference_response", ""),
                inference_model=result.get("inference_model", ""),
                inference_status=result.get("inference_status", ""),
                error=result.get("error", ""),
            )

            sys.stderr.write(
                f"[queue] tarefa {queue_id} concluida: "
                f"{result.get('status', 'UNKNOWN')}\n")

        return code

    def _wait_empty(self):
        for _ in range(_QUEUE_SLEEP_EMPTY):
            if not self._running:
                break
            time.sleep(1)


def main():
    parser = argparse.ArgumentParser(
        prog="pcsala-agent", description="Worker LangGraph pc-sala-agent",
    )
    parser.add_argument("command", choices=["iniciar", "retomar"], nargs="?")
    parser.add_argument("--root", required=True)
    parser.add_argument("--project", default=None)
    parser.add_argument("--session", default=None)
    parser.add_argument("--task", default=None)
    parser.add_argument("--attempt", default=None)
    parser.add_argument("--prompt", default="")
    parser.add_argument("--profile", default="gpu-triage-v1")
    parser.add_argument("--queue-mode", action="store_true",
                        help="Modo fila: consome de task_queue")
    args = parser.parse_args()

    if args.queue_mode:
        sys.exit(QueuePollCycle(args).run())

    if not args.command:
        parser.error("o argumento command e obrigatorio sem --queue-mode")
    missing = [name for name in ("project", "session", "task", "attempt")
               if getattr(args, name) is None]
    if missing:
        parser.error("sem --queue-mode sao obrigatorios: "
                     + ", ".join(f"--{name}" for name in missing))

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
