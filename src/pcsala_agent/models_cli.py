"""CLI de gestao de modelos: list, status, health, start, stop, switch, vram."""
import argparse
import json
import os
import sys
from pathlib import Path

from .database import connect
from .gpu_monitor import GpuMonitor
from .locking import _FileLock, ExecutorBusy
from .model_manager import ModelCoordinator, ModelRegistry, GPU_SWITCH_LOCK_DIR, _unit_active
from .model_vram import ModelVramStore
from .migrations import migrate

VRAM_GUARD_MIN_FREE_MB = 1536  # 1,5 GB


class ModelsCLI:
    def __init__(self, registry=None, coordinator=None, vram_store=None,
                 gpu_monitor=None, systemctl=None, lock_dir=None,
                 db_path=None):
        self.registry = registry or ModelRegistry()
        if db_path is not None:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            migrate(db_path)
        self.coordinator = coordinator or ModelCoordinator(
            self.registry, database=db_path)
        if vram_store is not None:
            self.vram_store = vram_store
        elif db_path is not None:
            self.vram_store = ModelVramStore(connect(db_path))
        else:
            self.vram_store = None
        self.gpu_monitor = gpu_monitor or GpuMonitor()
        self.systemctl = systemctl or self._run_systemctl
        self.lock_dir = Path(lock_dir) if lock_dir else GPU_SWITCH_LOCK_DIR

    # ------------------------------------------------------------------ run

    def run(self, args):
        command = args[0] if args else None
        if command == "list":
            return self._cmd_list()
        if command == "status":
            return self._cmd_status(args[1])
        if command == "health":
            return self._cmd_health(args[1])
        if command == "start":
            return self._cmd_start(args[1])
        if command == "stop":
            return self._cmd_stop(args[1])
        if command == "switch":
            return self._cmd_switch(args[1])
        if command == "vram":
            return self._cmd_vram()
        if command == "operation":
            return self._cmd_operation(args[1])
        print(f"comando desconhecido: {command}", file=sys.stderr)
        return 2

    # ---------------------------------------------------------------- list

    def _cmd_list(self):
        print("MODELO                   PORTA     CLASSE   COMPARTILHADO  EXCLUSIVO   ENDPOINT")
        for m in self.registry.list():
            print(f"{m.model_id:<24} {self._port(m.endpoint):<9} "
                  f"{m.model_class:<8} {'sim' if m.shared else 'nao':<12} "
                  f"{m.exclusive_group or '-':<11} {m.endpoint}")
        return 0

    # --------------------------------------------------------------- status

    def _cmd_status(self, model_id):
        model = self.registry.get(model_id)
        if model is None:
            print(f"Modelo desconhecido: {model_id}", file=sys.stderr)
            return 1
        status = self.coordinator.ensure_ready(model_id)
        reserved = self.coordinator.engine_reserved(model_id)
        print(f"modelo: {model_id}")
        print(f"  unidade: {model.unit}")
        print(f"  endpoint: {model.endpoint}")
        print(f"  servico: {status.service}")
        print(f"  saude: {status.health}")
        print(f"  exclusivo: {model.exclusive_group or '-'}")
        print(f"  residente: {'sim' if model.shared else 'nao'}")
        print(f"  engine_reservado: {'sim' if reserved else 'nao'}")
        return 0

    # ---------------------------------------------------------------- health

    def _cmd_health(self, model_id):
        model = self.registry.get(model_id)
        if model is None:
            print(f"Modelo desconhecido: {model_id}", file=sys.stderr)
            return 1
        status = self.coordinator.ensure_ready(model_id)
        print(f"{model_id}: servico={status.service} saude={status.health}")
        return 0 if status.service == "running" and status.health == "healthy" else 1

    # ---------------------------------------------------------------- start

    def _cmd_start(self, model_id):
        model = self.registry.get(model_id)
        if model is None:
            print(f"Modelo desconhecido: {model_id}", file=sys.stderr)
            return 1
        if not self._vram_ok():
            print("Recusando arranque: VRAM livre abaixo de 1,5 GB",
                  file=sys.stderr)
            return 3
        try:
            with self._switch_lock():
                self.coordinator.reserve_engine(model_id, requester="cli")
                op = self.coordinator.request_start(model_id)
                code = self.systemctl("start", model.unit)
        except ExecutorBusy:
            print("Bloqueio de troca de GPU ocupado", file=sys.stderr)
            return 3
        if code != 0:
            print(f"Falha ao iniciar {model.unit} (codigo {code})",
                  file=sys.stderr)
            self.coordinator.release_engine(model_id)
            return code
        print(f"{model_id}: iniciado (operacao {op.operation_id})")
        return 0

    # ---------------------------------------------------------------- stop

    def _cmd_stop(self, model_id):
        model = self.registry.get(model_id)
        if model is None:
            print(f"Modelo desconhecido: {model_id}", file=sys.stderr)
            return 1
        try:
            with self._switch_lock():
                code = self.systemctl("stop", model.unit)
                self.coordinator.release_engine(model_id)
        except ExecutorBusy:
            print("Bloqueio de troca de GPU ocupado", file=sys.stderr)
            return 3
        if code != 0:
            print(f"Falha ao parar {model.unit} (codigo {code})",
                  file=sys.stderr)
            return code
        print(f"{model_id}: parado")
        return 0

    # ---------------------------------------------------------------- switch

    def _cmd_switch(self, target_model_id):
        to_model = self.registry.get(target_model_id)
        if to_model is None:
            print(f"Modelo desconhecido: {target_model_id}", file=sys.stderr)
            return 1
        if to_model.exclusive_group is None:
            print(f"Recusando switch: {target_model_id} e residente/compartilhado; "
                  "o switch aplica-se apenas a modelos exclusivos (Laguna, Ornith)",
                  file=sys.stderr)
            return 3
        if not self._vram_ok():
            print("Recusando troca: VRAM livre abaixo de 1,5 GB", file=sys.stderr)
            return 3
        from_model_id = None
        for m in self.registry.exclusive_models():
            if m.model_id == target_model_id:
                continue
            try:
                st = self.coordinator.ensure_ready(m.model_id)
            except Exception:
                continue
            if st.service == "running":
                from_model_id = m.model_id
                break
        if from_model_id == target_model_id:
            print(f"{target_model_id} ja e o modelo ativo no slot exclusivo")
            return 0
        from_model = self.registry.get(from_model_id) if from_model_id else None
        try:
            with self._switch_lock():
                self.coordinator.reserve_engine(target_model_id, requester="cli")
                if from_model is not None and _unit_active(from_model.unit):
                    code = self.systemctl("stop", from_model.unit)
                    if code != 0:
                        print(f"Falha ao parar {from_model_id} (codigo {code})",
                              file=sys.stderr)
                        self.coordinator.release_engine(target_model_id)
                        return code
                code = self.systemctl("start", to_model.unit)
                if from_model is not None:
                    self.coordinator.release_engine(from_model_id)
        except ExecutorBusy:
            print("Bloqueio de troca de GPU ocupado", file=sys.stderr)
            return 3
        if code != 0:
            print(f"Falha ao trocar para {target_model_id} (codigo {code})",
                  file=sys.stderr)
            self.coordinator.release_engine(target_model_id)
            return code
        origem = from_model_id or "-"
        print(f"Troca concluida: {origem} -> {target_model_id}")
        return 0

    # ---------------------------------------------------------------- vram

    def _cmd_vram(self):
        gpus = self.gpu_monitor.query_vram()
        free_total = self.gpu_monitor.free_mb()
        print("VRAM por GPU (nvidia-smi):")
        if gpus:
            for g in gpus:
                print(f"  GPU {g.index} {g.name}: "
                      f"usada {g.used_mb} MB / total {g.total_mb} MB / "
                      f"livre {g.free_mb} MB")
        else:
            print("  nvidia-smi indisponivel; nao foi possivel medir VRAM")
        print()
        if free_total is not None:
            print(f"VRAM livre total: {free_total} MB")
            if free_total < VRAM_GUARD_MIN_FREE_MB:
                print("AVISO: folga abaixo de 1,5 GB; start/switch serao recusados")
        else:
            print("VRAM livre total: indisponivel")
        print()
        print("Ultima medida registrada por modelo (SQLite):")
        if self.vram_store is None:
            print("  armazenamento nao configurado")
        else:
            rows = self.vram_store.all()
            if not rows:
                print("  (nenhuma medida registrada)")
            for row in rows:
                print(f"  {row['model_id']} ctx={row['context_size']}: "
                      f"{row['vram_used_mb']} MB (medido em {row['measured_at']})")
        return 0

    # ------------------------------------------------------------- operation

    def _cmd_operation(self, operation_id):
        op = self.coordinator.get_operation(operation_id)
        if op is None:
            print(f"Operacao desconhecida: {operation_id}", file=sys.stderr)
            return 1
        for key in ("operation_id", "action", "target_model_id", "status",
                    "requested_status", "confirmed_status", "error",
                    "created_at", "updated_at"):
            value = op.get(key)
            print(f"  {key}: {value}")
        return 0

    # ------------------------------------------------------------- internals

    def _vram_ok(self):
        free = self.gpu_monitor.free_mb()
        if free is None:
            return True
        return free >= VRAM_GUARD_MIN_FREE_MB

    def _switch_lock(self):
        try:
            self.lock_dir.mkdir(parents=True, exist_ok=True)
            return _FileLock(self.lock_dir / "pcsala-gpu-switch.lock")
        except OSError:
            return _NullLock()

    @staticmethod
    def _port(endpoint):
        return endpoint.rsplit(":", 1)[-1]

    @staticmethod
    def _run_systemctl(action, unit):
        try:
            result = subprocess_run(["systemctl", action, unit])
            return result.returncode
        except OSError:
            return 127


class _NullLock:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def subprocess_run(cmd):
    import subprocess
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="pcsala models", description="Gestao de modelos pc-sala-agent")
    parser.add_argument("--root", default="/var/lib/pcsala-worker")
    parser.add_argument("--db", default=None,
                        help="Caminho do SQLite (default: <root>/state.sqlite)")
    parser.add_argument("command", choices=[
        "list", "status", "health", "start", "stop", "switch", "vram",
        "operation",
    ])
    parser.add_argument("model_id", nargs="?")
    parser.add_argument("to_model_id", nargs="?")
    args = parser.parse_args(argv)

    if args.command in ("status", "health", "start", "stop", "operation") \
            and not args.model_id:
        parser.error(f"{args.command} requer um modelo")

    db_path = args.db
    if db_path is None:
        db_path = str(Path(args.root) / "state.sqlite")
    cli = ModelsCLI(db_path=db_path)
    command = args.command
    if command == "switch":
        return cli.run([command, args.model_id])
    if command in ("status", "health", "start", "stop", "operation"):
        return cli.run([command, args.model_id])
    return cli.run([command])


if __name__ == "__main__":
    sys.exit(main())
