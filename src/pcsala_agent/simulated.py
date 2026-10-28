import argparse
import json
import sys
from datetime import UTC
from pathlib import Path

from .checkpoints import CheckpointStore, RecoveryRequired
from .database import connect
from .locking import ExecutorBusy, database_lock
from .migrations import migrate


def _now():
    from datetime import datetime
    return datetime.now(UTC).isoformat(timespec="seconds")


def _open_db(root):
    migrate(root / "state.sqlite")
    return connect(root / "state.sqlite")


def _scope(project, session, task, attempt="sim"):
    return {"project_id": project, "session_id": session, "task_id": task,
            "attempt_id": attempt}


def execute(root, command, project="p", session="s", task="t", attempt="sim",
            prompt="", profile="gpu-triage-v1"):
    root = Path(root)
    db = _open_db(root)
    try:
        store = CheckpointStore(db, root / "artifacts")

        if command == "iniciar":
            existing = db.execute(
                """SELECT checkpoint_id FROM checkpoints
                WHERE project_id=? AND session_id=? AND task_id=?
                AND status='COMMITTED' LIMIT 1""",
                (project, session, task),
            ).fetchone()
            if existing is not None:
                raise RuntimeError("sessao ja possui checkpoint confirmado")
            cid = store.prepare(project, session, task)
            data = {
                "scope": _scope(project, session, task),
                "step": "simulacao_iniciada",
                "checkpoint_id": cid,
            }
            store.add_artifact(cid, json.dumps(data).encode("utf-8"))
            store.commit(cid)
            return {"status": "CHECKPOINT_SALVO", "checkpoint_id": cid}

        if command == "retomar":
            latest = store.latest(project, session, task)
            if latest is None:
                raise RuntimeError("escopo sem checkpoint para retomar")
            recover = store.recover(project, session)
            if recover["checkpoints"] > 0:
                raise RecoveryRequired("checkpoint incompleto")
            pending = db.execute(
                """SELECT 1 FROM checkpoints
                WHERE project_id=? AND session_id=? AND task_id=?
                AND status='NEEDS_RECOVERY' LIMIT 1""",
                (project, session, task),
            ).fetchone()
            if pending is not None:
                raise RecoveryRequired("checkpoint em recuperacao")
            data = json.loads(
                (root / "artifacts" / f"{latest['checkpoint_id']}.bin").read_bytes()
            )
            if data.get("step") == "simulacao_concluida":
                return {
                    "status": "SIMULACAO_CONCLUIDA",
                    "checkpoint_id": latest["checkpoint_id"],
                    "nova_execucao": False,
                }
            cid = store.prepare(project, session, task)
            ndata = {
                "scope": _scope(project, session, task),
                "step": "simulacao_concluida",
                "checkpoint_id": cid,
                "previous_checkpoint": latest["checkpoint_id"],
            }
            store.add_artifact(cid, json.dumps(ndata).encode("utf-8"))
            store.commit(cid)
            return {
                "status": "SIMULACAO_CONCLUIDA",
                "checkpoint_id": cid,
                "nova_execucao": True,
            }
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(
        prog="pcsala-agent-simulated", description="Worker LangGraph simulado",
    )
    parser.add_argument("command", choices=["iniciar", "retomar"])
    parser.add_argument("--root", required=True)
    parser.add_argument("--project", default="p")
    parser.add_argument("--session", default="s")
    parser.add_argument("--task", default="t")
    args = parser.parse_args()
    env = Path(args.root)
    env.mkdir(parents=True, exist_ok=True)
    try:
        with database_lock(env / "state.sqlite"):
            result = execute(env, args.command, args.project, args.session, args.task)
    except ExecutorBusy:
        print("executor ocupado", file=sys.stderr)
        sys.exit(3)
    except (RuntimeError, RecoveryRequired) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
    print(json.dumps(result))
    sys.exit(0)


if __name__ == "__main__":
    main()
