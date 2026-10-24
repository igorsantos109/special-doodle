import argparse
import json
import sys
from pathlib import Path

from .task_queue import (
    cancel, enqueue, get, list_tasks, reconcile,
)
from .document_flow import (
    extract_document, build_analysis_prompt,
    DEPENDENCIES_SUGGESTED,
)


def _check_service(name):
    import subprocess
    try:
        out = subprocess.run(
            ["systemctl", "is-active", name],
            capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip() == "active"
    except Exception:
        return False


def _reconcile_cmd(database, args):
    root = args.root
    graph_root = root
    reconciled = 0
    failed = 0

    reserved = list_tasks(database, status="RESERVED")
    if not reserved:
        print("Nenhuma tarefa RESERVED para reconciliar")
        return 0

    for task in reserved:
        tid = task["id"]
        attempt_id = task["attempt_id"]
        task_session = f"queue-{tid}"
        task_id = f"task-{tid}"
        r = reconcile(database, tid, graph_root=graph_root,
                      graph_attempt_id=attempt_id)
        if r:
            reconciled += 1
            print(f"Tarefa {tid}: reconciliada do grafo")
        else:
            failed += 1
            print(f"Tarefa {tid}: sem artefato confirmado no grafo",
                  file=sys.stderr)

    print(f"\nReconciliadas: {reconciled}, Sem artefato: {failed}")
    return 0 if failed == 0 else 1


def main():
    parser = argparse.ArgumentParser(
        description="Fila de tarefas do worker LangGraph")
    parser.add_argument("--root", type=Path, required=True,
                        help="Raiz persistente do worker")

    sub = parser.add_subparsers(dest="command", required=True)

    enq = sub.add_parser("enqueue", help="Enfileirar tarefa")
    enq.add_argument("--prompt", required=True)
    enq.add_argument("--profile", default="gpu-triage-v1")
    enq.add_argument("--idempotency-key")

    lst = sub.add_parser("list", help="Listar tarefas")
    lst.add_argument("--status", choices=("QUEUED", "RESERVED",
                                          "COMPLETED", "FAILED", "CANCELLED"))

    st = sub.add_parser("status", help="Consultar estado de tarefa")
    st.add_argument("id", type=int)

    cn = sub.add_parser("cancel", help="Cancelar tarefa na fila")
    cn.add_argument("id", type=int)

    rc = sub.add_parser("reconcile", help="Reconciliar tarefas RESERVED"
                        " com artefactos do grafo")

    hl = sub.add_parser("health", help="Verificar saude dos servicos")

    doc = sub.add_parser("document", help="Submeter documento para analise")
    doc.add_argument("--path", required=True,
                     help="Caminho do documento (txt, md, py, ...)")
    doc.add_argument("--profile", default="gpu-triage-v1")
    doc.add_argument("--idempotency-key")

    deps = sub.add_parser("document-deps",
                          help="Listar dependencias sugeridas para extracao")

    args = parser.parse_args()
    database = args.root / "state.sqlite"

    if args.command == "enqueue":
        try:
            result = enqueue(
                database, args.prompt,
                profile=args.profile,
                idempotency_key=args.idempotency_key,
            )
        except ValueError as error:
            print(str(error), file=sys.stderr)
            return 1
        print(json.dumps(result, ensure_ascii=False))
        return 0

    if args.command == "list":
        tasks = list_tasks(database, status=getattr(args, "status", None))
        for t in tasks:
            d = dict(t)
            d.pop("prompt", None)
            print(json.dumps(d, ensure_ascii=False))
        return 0

    if args.command == "status":
        task = get(database, args.id)
        if task is None:
            print(f"Tarefa {args.id} nao encontrada", file=sys.stderr)
            return 1
        print(json.dumps(task, ensure_ascii=False))
        return 0

    if args.command == "cancel":
        ok = cancel(database, args.id)
        if ok:
            print(f"Tarefa {args.id} cancelada")
        else:
            print(f"Tarefa {args.id} nao pode ser cancelada "
                  "(inexistente ou ja processada)", file=sys.stderr)
            return 1
        return 0

    if args.command == "reconcile":
        return _reconcile_cmd(database, args)

    if args.command == "health":
        import socket
        ok = True
        for label, host, port in [
            ("Bonsai 27B GPU", "127.0.0.1", 8080),
            ("Bonsai 9B CPU", "127.0.0.1", 8090),
        ]:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)
            try:
                sock.connect((host, port))
                print(f"{label}: OK")
            except (OSError, socket.timeout):
                print(f"{label}: INDISPONIVEL", file=sys.stderr)
                ok = False
            finally:
                sock.close()
        if _check_service("pcsala-worker.service"):
            print("Worker: OK")
        else:
            print("Worker: INDISPONIVEL", file=sys.stderr)
            ok = False
        return 0 if ok else 1

    if args.command == "document":
        try:
            ext = extract_document(args.path)
        except Exception as error:
            print(str(error), file=sys.stderr)
            return 1

        print(f"Documento: {ext.origin}")
        print(f"Hash: {ext.hash_sha256}")
        print(f"Metodo: {ext.method}")
        print(f"Tamanho: {len(ext.text)} caracteres")
        print(f"Primeiros 200 caracteres: {ext.text[:200]!r}")

        prompt = build_analysis_prompt(ext)
        result = enqueue(
            database, prompt,
            profile=args.profile,
            idempotency_key=args.idempotency_key,
        )
        print(f"\nEnfileirado para analise: tarefa #{result['id']}")
        return 0

    if args.command == "document-deps":
        for dep in DEPENDENCIES_SUGGESTED:
            print(f"{dep['package']}: {dep['purpose']}")
            print(f"  Instalar: {dep['install_cmd']}")
            print(f"  Extensoes: {', '.join(dep['extensions'])}")
            print()
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())