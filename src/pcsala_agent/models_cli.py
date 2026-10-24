import argparse
import json
import sys
from pathlib import Path

from .model_manager import (
    ModelCoordinator,
    ModelOperationResult,
    ModelRegistry,
    ModelStatusResult,
)


def main():
    parser = argparse.ArgumentParser(description="Gestao de modelos")
    parser.add_argument("--root", type=Path, default=Path("/var/lib/pcsala-worker"),
                        help="Raiz do worker para persistencia")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="Listar modelos cadastrados")

    st = sub.add_parser("status", help="Estado de um modelo")
    st.add_argument("model_id", help="Identificador do modelo")

    hl = sub.add_parser("health", help="Saude de um modelo")
    hl.add_argument("model_id", help="Identificador do modelo")

    start = sub.add_parser("start", help="Iniciar modelo")
    start.add_argument("model_id", help="Identificador do modelo")

    stop = sub.add_parser("stop", help="Parar modelo")
    stop.add_argument("model_id", help="Identificador do modelo")

    switch = sub.add_parser("switch", help="Trocar modelo GPU")
    switch.add_argument("model_id", help="Identificador do modelo destino")

    op = sub.add_parser("operation", help="Consultar operacao")
    op.add_argument("operation_id", help="Identificador da operacao")

    args = parser.parse_args()

    database = args.root / "state.sqlite"
    registry = ModelRegistry()
    coordinator = ModelCoordinator(registry, database=database)

    if args.command == "list":
        models = registry.list()
        data = [
            {
                "model_id": m.model_id,
                "name": m.name,
                "class": m.model_class,
                "profile": m.profile,
                "unit": m.unit,
                "shared": m.shared,
                "capabilities": m.capabilities,
                "exclusive_group": m.exclusive_group,
            }
            for m in models
        ]
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    if args.command == "status":
        try:
            result = coordinator.status(args.model_id)
            print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))
        except ValueError as e:
            print(str(e), file=sys.stderr)
            return 1
        return 0

    if args.command == "health":
        try:
            result = coordinator.health(args.model_id)
            print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))
        except ValueError as e:
            print(str(e), file=sys.stderr)
            return 1
        return 0

    if args.command == "start":
        try:
            result = coordinator.request_start(args.model_id)
            _print_operation(result)
            return 0 if result.status in ("COMPLETED",) else 1
        except (ValueError, PermissionError) as e:
            print(str(e), file=sys.stderr)
            return 1

    if args.command == "stop":
        try:
            result = coordinator.request_stop(args.model_id)
            _print_operation(result)
            return 0 if result.status in ("COMPLETED",) else 1
        except (ValueError, PermissionError) as e:
            print(str(e), file=sys.stderr)
            return 1

    if args.command == "switch":
        try:
            result = coordinator.request_switch(args.model_id)
            _print_operation(result)
            return 0 if result.status in ("COMPLETED",) else 1
        except (ValueError, PermissionError) as e:
            print(str(e), file=sys.stderr)
            return 1

    if args.command == "operation":
        op_data = coordinator.get_operation(args.operation_id, database=database)
        if op_data is None:
            print(f"Operacao {args.operation_id} nao encontrada", file=sys.stderr)
            return 1
        print(json.dumps(op_data, ensure_ascii=False, indent=2, default=str))
        return 0

    return 0


def _print_operation(result: ModelOperationResult):
    print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())