"""CLI da fila de tarefas: enqueue, document, list, status, cancel, reconcile, health."""
import argparse
import sqlite3
import sys
from pathlib import Path

from .database import connect

MODEL_ENDPOINTS = {
    "bonsai-27b-gpu": ("127.0.0.1", 8080),
    "bonsai-4b-gpu": ("127.0.0.1", 8093),
    "bonsai-9b-cpu": ("127.0.0.1", 8090),
    "laguna-xs-2.1-cpu": ("127.0.0.1", 8091),
    "laguna-xs-2.1-gpu": ("127.0.0.1", 8082),
    "ornith-35b-gpu": ("127.0.0.1", 8092),
}


class QueueCLI:
    def __init__(self, root):
        self.root = Path(root)
        self.db_path = self.root / "state.sqlite"

    def run(self, args):
        command = args[0] if args else None
        if command == "enqueue":
            return self._cmd_enqueue(args[1:])
        if command == "document":
            return self._cmd_document(args[1:])
        if command == "document-deps":
            return self._cmd_document_deps()
        if command == "list":
            return self._cmd_list(args[1:])
        if command == "status":
            return self._cmd_status(args[1])
        if command == "cancel":
            return self._cmd_cancel(args[1])
        if command == "reconcile":
            return self._cmd_reconcile()
        if command == "health":
            return self._cmd_health()
        print(f"comando desconhecido: {command}", file=sys.stderr)
        return 2

    # --------------------------------------------------------------- enqueue

    def _cmd_enqueue(self, args):
        parser = argparse.ArgumentParser(prog="pcsala enqueue")
        parser.add_argument("--prompt", required=True)
        parser.add_argument("--profile", default="gpu-triage-v1")
        parser.add_argument("--idempotency-key")
        ns = parser.parse_args(args)
        return self._insert_task(ns.prompt, ns.profile, ns.idempotency_key)

    def _cmd_document(self, args):
        parser = argparse.ArgumentParser(prog="pcsala document")
        parser.add_argument("--path", required=True)
        parser.add_argument("--profile", default="gpu-triage-v1")
        parser.add_argument("--idempotency-key")
        ns = parser.parse_args(args)
        path = Path(ns.path)
        if not path.exists():
            print(f"arquivo nao encontrado: {path}", file=sys.stderr)
            return 1
        prompt = path.read_text(encoding="utf-8")
        return self._insert_task(prompt, ns.profile, ns.idempotency_key)

    def _insert_task(self, prompt, profile, idempotency_key):
        db = connect(self.db_path)
        try:
            with db:
                db.execute(
                    """INSERT INTO task_queue
                    (idempotency_key, profile, prompt, status)
                    VALUES (?, ?, ?, 'QUEUED')""",
                    (idempotency_key, profile, prompt),
                )
                row = db.execute(
                    "SELECT id, status FROM task_queue WHERE rowid=last_insert_rowid()"
                ).fetchone()
            print(f"enfileirado id={row['id']} status={row['status']}")
            return 0
        except sqlite3.IntegrityError:
            print("idempotencia chave duplicada; tarefa nao enfileirada",
                  file=sys.stderr)
            return 1
        finally:
            db.close()

    # ---------------------------------------------------------- document-deps

    def _cmd_document_deps(self):
        print("pdfminer.six")
        return 0

    # ---------------------------------------------------------------- list

    def _cmd_list(self, args):
        parser = argparse.ArgumentParser(prog="pcsala list")
        parser.add_argument("--status")
        ns = parser.parse_args(args)
        db = connect(self.db_path)
        try:
            if ns.status:
                rows = db.execute(
                    """SELECT id,status,profile,prompt,created_at
                    FROM task_queue WHERE status=? ORDER BY id""",
                    (ns.status,),
                ).fetchall()
            else:
                rows = db.execute(
                    """SELECT id,status,profile,prompt,created_at
                    FROM task_queue ORDER BY id DESC LIMIT 50"""
                ).fetchall()
        finally:
            db.close()
        if not rows:
            print("(nenhuma tarefa)")
            return 0
        for row in rows:
            prompt = (row["prompt"] or "")[:60].replace("\n", " ")
            print(f"{row['id']:>4} {row['status']:<12} {row['profile']:<16} "
                  f"{row['created_at']}  {prompt}")
        return 0

    # ---------------------------------------------------------------- status

    def _cmd_status(self, task_id):
        db = connect(self.db_path)
        try:
            row = db.execute(
                """SELECT id,status,profile,prompt,inference_response,
                inference_status,error,created_at,completed_at
                FROM task_queue WHERE id=?""",
                (int(task_id),),
            ).fetchone()
        finally:
            db.close()
        if row is None:
            print(f"tarefa nao encontrada: {task_id}", file=sys.stderr)
            return 1
        print(f"id: {row['id']}")
        print(f"status: {row['status']}")
        print(f"profile: {row['profile']}")
        print(f"prompt: {row['prompt']}")
        print(f"inference_status: {row['inference_status'] or '-'}")
        print(f"inference_response: {row['inference_response'] or '-'}")
        print(f"error: {row['error'] or '-'}")
        print(f"criado: {row['created_at']}")
        print(f"concluido: {row['completed_at'] or '-'}")
        return 0

    # ---------------------------------------------------------------- cancel

    def _cmd_cancel(self, task_id):
        db = connect(self.db_path)
        try:
            with db:
                cur = db.execute(
                    "UPDATE task_queue SET status='CANCELLED' WHERE id=?",
                    (int(task_id),),
                )
            if cur.rowcount == 0:
                print(f"tarefa nao encontrada: {task_id}", file=sys.stderr)
                return 1
            print(f"tarefa {task_id} cancelada")
            return 0
        finally:
            db.close()

    # ------------------------------------------------------------- reconcile

    def _cmd_reconcile(self):
        db = connect(self.db_path)
        try:
            with db:
                cur = db.execute(
                    """UPDATE task_queue
                    SET status='QUEUED', reserved_at=NULL
                    WHERE status='RESERVED'
                    AND reserved_at IS NOT NULL
                    AND reserved_at < strftime('%Y-%m-%dT%H:%M:%S','now','-5 minutes')"""
                )
            print(f"reconciliadas {cur.rowcount} tarefas RESERVED -> QUEUED")
            return 0
        finally:
            db.close()

    # ---------------------------------------------------------------- health

    def _cmd_health(self):
        import socket
        overall = True
        for model, (host, port) in MODEL_ENDPOINTS.items():
            ok = False
            try:
                with socket.create_connection((host, port), timeout=1):
                    ok = True
            except OSError:
                ok = False
            if not ok:
                overall = False
            print(f"  {model}: {host}:{port} -> {'online' if ok else 'offline'}")
        return 0 if overall else 1


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="pcsala queue", description="Fila de tarefas pc-sala-agent")
    parser.add_argument("--root", default="/var/lib/pcsala-worker")
    parser.add_argument("command", nargs="?", default=None)
    parser.add_argument("rest", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    cli = QueueCLI(args.root)
    rest = args.rest if args.command else []
    if args.command:
        rest = [args.command, *rest]
    return cli.run(rest)


if __name__ == "__main__":
    sys.exit(main())
