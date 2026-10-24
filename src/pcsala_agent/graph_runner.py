import argparse
import hashlib
import json
import os
import signal
import socket
import sys
import time
from pathlib import Path
from typing import TypedDict

from .checkpoints import RecoveryRequired
from .database import connect
from .inference_profiles import PROFILES
from .locking import ExecutorBusy, database_lock
from .migrations import migrate
from .model_manager import ModelCoordinator, ModelRegistry
from .task_queue import reserve as queue_reserve
from .task_queue import update as queue_update


def _ensure_session(database, project, session, task):
    migrate(database)
    with database_lock(database):
        db = connect(database)
        try:
            if not db.execute(
                "SELECT 1 FROM projects WHERE project_id=?", (project,)
            ).fetchone():
                db.execute(
                    "INSERT INTO projects (project_id,name,authorized_root)"
                    " VALUES (?,?,?)",
                    (project, project, str(database.parent)),
                )
            if not db.execute(
                "SELECT 1 FROM sessions WHERE session_id=?", (session,)
            ).fetchone():
                db.execute(
                    "INSERT INTO sessions (session_id,project_id,state)"
                    " VALUES (?,?,?)",
                    (session, project, "RUNNING"),
                )
            if not db.execute(
                "SELECT 1 FROM tasks WHERE task_id=?", (task,)
            ).fetchone():
                db.execute(
                    "INSERT INTO tasks (task_id,project_id,title,"
                    " acceptance_criteria) VALUES (?,?,?,?)",
                    (task, project, task,
                     "Tarefa aceite automaticamente pelo worker"),
                )
            db.commit()
        finally:
            db.close()


class WorkerResult(TypedDict):
    status: str
    model_server: str
    inference_id: str
    inference_status: str
    inference_response: str
    error: str


_MODEL_HOST = "127.0.0.1"
_MODEL_PORT = 8090
_MODEL_TIMEOUT = 5


def _check_model_server(host=_MODEL_HOST, port=_MODEL_PORT):
    try:
        sock = socket.create_connection(
            (host, port), timeout=_MODEL_TIMEOUT
        )
        sock.close()
        return True
    except (OSError, socket.timeout):
        return False


def execute(root, command, project, session, task, attempt, prompt,
            *, _skip_health_check=False, _urlopen=None,
            profile="cpu-triage-v1"):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    _ensure_session(root / "state.sqlite", project, session, task)

    cfg = PROFILES.get(profile)
    if cfg is None:
        return WorkerResult(
            status="INVALID_PROFILE",
            model_server="",
            inference_id="",
            inference_status="",
            inference_response="",
            error=f"Perfil desconhecido: {profile}",
        )

    if not _skip_health_check:
        registry = ModelRegistry()
        coordinator = ModelCoordinator(registry, database=root / "state.sqlite")
        model = registry.get_by_profile(profile)
        if model is not None:
            ready = coordinator.ensure_ready(model.model_id)
            if ready.health != "healthy" and not (
                ready.service == "running" and ready.health == "unknown"
            ):
                if ready.service == "stopped":
                    return WorkerResult(
                        status="MODEL_NOT_READY",
                        model_server=cfg.endpoint,
                        inference_id="",
                        inference_status="",
                        inference_response="",
                        error=f"Modelo {profile} ({model.model_id}) nao esta em execucao. "
                              f"Use './pcsala models start {model.model_id}'.",
                    )
                return WorkerResult(
                    status="MODEL_NOT_READY",
                    model_server=cfg.endpoint,
                    inference_id="",
                    inference_status="",
                    inference_response="",
                    error=f"Modelo {profile} ({model.model_id}) nao disponivel: "
                          f"service={ready.service}, health={ready.health}",
                )
        else:
            from urllib.parse import urlparse
            parsed = urlparse(cfg.endpoint)
            host = parsed.hostname or _MODEL_HOST
            port = parsed.port or _MODEL_PORT
            if not _check_model_server(host, port):
                return WorkerResult(
                    status="MODEL_SERVER_DOWN",
                    model_server=f"{host}:{port}",
                    inference_id="",
                    inference_status="",
                    inference_response="",
                    error=f"Modelo {profile} nao disponivel em {host}:{port}",
                )

    from .real_graph import execute as real_execute

    result = real_execute(
        root, command, project, session, task, attempt, prompt,
        _urlopen=_urlopen, profile=profile,
    )

    return WorkerResult(
        status=result.get("status", "UNKNOWN"),
        model_server=cfg.endpoint,
        inference_id=result.get("inference_id", ""),
        inference_status=result.get("inference_status", ""),
        inference_response=result.get("inference_response", ""),
        error=result.get("error", ""),
    )


def main():
    parser = argparse.ArgumentParser(
        description="Worker operacional do LangGraph (Bonsai CPU/GPU)")
    parser.add_argument("command", choices=["iniciar", "retomar"],
                        nargs="?")
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--project", default="default")
    parser.add_argument("--session", default="main")
    parser.add_argument("--task", default="triage")
    parser.add_argument("--attempt", default=None)
    parser.add_argument("--prompt", default=None)
    parser.add_argument("--profile", default="cpu-triage-v1",
                        choices=list(PROFILES.keys()))
    parser.add_argument("--continuous", action="store_true",
                        help="Aguarda novas tarefas em ciclo (modo daemon)")
    parser.add_argument("--queue-mode", action="store_true",
                        help="Modo fila: consome de task_queue")
    args = parser.parse_args()

    if args.queue_mode:
        ciclo = QueuePollCycle(args)
        return ciclo.run()

    if not args.command:
        parser.error("o argumento command e obrigatorio sem --queue-mode")

    if not args.continuous:
        return _run_once(args)

    ciclo = PollCycle(args)
    return ciclo.run()


def _run_once(args):
    try:
        result = execute(
            args.root, args.command,
            args.project, args.session, args.task,
            args.attempt, args.prompt,
            profile=args.profile,
        )
    except ExecutorBusy as error:
        print(str(error), file=sys.stderr)
        return 3
    except RecoveryRequired as error:
        msg = str(error)
        print(msg, file=sys.stderr)
        if msg.startswith("Grafo ausente"):
            try:
                result = execute(
                    args.root, "iniciar",
                    args.project, args.session, args.task,
                    args.attempt, args.prompt,
                    profile=args.profile,
                )
            except (ExecutorBusy, RecoveryRequired) as e2:
                print(str(e2), file=sys.stderr)
                return 2
            print(json.dumps(result, ensure_ascii=False))
            return 0
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


class PollCycle:

    _POLL_SLEEP = 30

    def __init__(self, args):
        self._args = args
        self._running = True
        signal.signal(signal.SIGTERM, self._shutdown)
        signal.signal(signal.SIGINT, self._shutdown)

    def _shutdown(self, signum, _frame):
        sys.stderr.write(f"PollCycle: recebido sinal {signum}, encerrando\n")
        self._running = False

    def run(self):
        code = 0
        while self._running:
            out = _run_once(self._args)
            if out != 0:
                code = out
            self._wait()
        return code

    def _wait(self):
        for _ in range(self._POLL_SLEEP):
            if not self._running:
                break
            time.sleep(1)


_QUEUE_SLEEP_EMPTY = 10
_QUEUE_SLEEP_BUSY = 1


class QueuePollCycle:

    def __init__(self, args):
        self._root = args.root
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
            task = self._reserve(database)
            if task is None:
                self._wait_empty()
                continue
            queue_id = task["id"]
            attempt_id = task["attempt_id"]
            task_session = f"queue-{queue_id}"
            task_id = f"task-{queue_id}"
            prompt = task["prompt"]
            profile = task.get("profile") or self._profile

            _ensure_session(database, "default", task_session, task_id)

            try:
                result = execute(
                    self._root, "iniciar",
                    "default", task_session, task_id, attempt_id,
                    prompt, profile=profile,
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

    def _reserve(self, database):
        """Tenta reservar a primeira tarefa QUEUED."""
        return queue_reserve(database)

    def _wait_empty(self):
        for _ in range(_QUEUE_SLEEP_EMPTY):
            if not self._running:
                break
            time.sleep(1)

    def _wait_busy(self):
        time.sleep(_QUEUE_SLEEP_BUSY)


if __name__ == "__main__":
    raise SystemExit(main())