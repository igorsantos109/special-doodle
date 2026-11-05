"""CLI de gestao de modelos: list, status, health, start, stop, switch, vram,
gen-llama-swap."""
import argparse
import logging
import os
import sys
import time
from pathlib import Path

from .database import connect
from .gpu_monitor import GpuMonitor
from .locking import ExecutorBusy, switch_lock
from .migrations import migrate
from .model_manager import (
    GPU_SWITCH_LOCK_DIR,
    ModelCoordinator,
    ModelRegistry,
    _unit_inactive,
)
from .model_vram import ModelVramStore
from .models.client import LlamaSwapClient

logger = logging.getLogger("pcsala_agent.models_cli")

VRAM_GUARD_MIN_FREE_MB = 1536  # 1,5 GB
VRAM_RELEASE_WAIT_SECONDS = 30
VRAM_RELEASE_POLL_SECONDS = 1
HEALTH_POLL_SECONDS = 2


class ModelsCLI:
    def __init__(self, registry=None, coordinator=None, vram_store=None,
                 gpu_monitor=None, systemctl=None, lock_dir=None,
                 db_path=None, skip_vram_guard=False,
                 llama_swap_client=None):
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
        self.lock_dir = Path(lock_dir) if lock_dir else Path(
            os.environ.get("PCSALA_LOCK_DIR", GPU_SWITCH_LOCK_DIR))
        self.skip_vram_guard = skip_vram_guard
        self.llama_swap_client = llama_swap_client

        # Tabela de despacho de subcomandos.
        self._commands = {
            "list": self._cmd_list,
            "status": self._cmd_status,
            "health": self._cmd_health,
            "start": self._cmd_start,
            "stop": self._cmd_stop,
            "switch": self._cmd_switch,
            "vram": self._cmd_vram,
            "operation": self._cmd_operation,
            "gen-llama-swap": self._cmd_gen_llama_swap,
        }

    def close(self):
        """Fecha recursos (conexao SQLite do ModelVramStore)."""
        if self.vram_store is not None:
            self.vram_store.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    # ------------------------------------------------------------------ run

    def run(self, args):
        command = args[0] if args else None
        handler = self._commands.get(command)
        if handler is None:
            print(f"comando desconhecido: {command}", file=sys.stderr)
            return 2
        if command in ("status", "health", "start", "stop", "switch",
                       "operation"):
            if len(args) < 2:
                print(f"{command} requer um modelo", file=sys.stderr)
                return 2
            return handler(args[1])
        return handler()

    # ---------------------------------------------------------------- list

    def _cmd_list(self):
        print("MODELO                   PORTA     CLASSE   COMPARTILHADO  EXCLUSIVO   "
              "ENDPOINT")
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
        if (model.model_class == "GPU" and not self.skip_vram_guard
                and not self._vram_ok()):
            logger.warning(
                "start recusado por VRAM: modelo=%s classe=%s",
                model_id,
                model.model_class,
            )
            print("Recusando arranque: VRAM livre abaixo de 1,5 GB",
                  file=sys.stderr)
            return 3
        logger.info(
            "start: modelo=%s unidade=%s backend=%s",
            model_id,
            model.unit,
            model.backend,
        )
        op = self.coordinator.request_start(model_id)
        try:
            with switch_lock(self.lock_dir):
                if model.exclusive_group is not None:
                    for peer in self.registry.exclusive_models():
                        if (peer.model_id != model_id
                                and peer.exclusive_group == model.exclusive_group
                                and self._is_model_running(peer.model_id)):
                            logger.warning(
                                "start bloqueado: grupo exclusivo ocupado por %s",
                                peer.model_id,
                            )
                            raise ExecutorBusy(model.exclusive_group)
                self.coordinator.reserve_engine(model_id, requester="cli")
                logger.info(
                    "start: reserva obtida para %s (operacao %s)",
                    model_id,
                    op.operation_id,
                )
                if model.backend == "llama-swap":
                    # Execucao via llama-swap: pedido minimo para carregar
                    # o modelo no proxy.
                    ok, error = self.llama_swap_client.load_model(model_id)
                    if not ok:
                        logger.warning(
                            "start falhou llama-swap: modelo=%s erro=%s",
                            model_id,
                            error,
                        )
                        print(f"Falha ao carregar {model_id} via llama-swap: "
                              f"{error}", file=sys.stderr)
                        self.coordinator.update_confirmed_status(
                            op.operation_id, "FAILED", error=error,
                        )
                        self.coordinator.release_engine(model_id)
                        return 1
                    # Aguarda o proxy ficar disponivel (health do llama-swap).
                    healthy = self.llama_swap_client.health()
                    if not healthy:
                        logger.warning(
                            "start falhou: llama-swap nao respondeu /health: "
                            "modelo=%s",
                            model_id,
                        )
                        print("Falha: llama-swap nao respondeu /health "
                              "dentro do tempo esperado",
                              file=sys.stderr)
                        self.coordinator.update_confirmed_status(
                            op.operation_id, "FAILED",
                            error="timeout aguardando llama-swap /health",
                        )
                        self.coordinator.release_engine(model_id)
                        return 1
                    self.coordinator.update_confirmed_status(
                        op.operation_id, "COMPLETED",
                    )
                    logger.info(
                        "start concluido via llama-swap: modelo=%s operacao=%s",
                        model_id,
                        op.operation_id,
                    )
                    print(f"{model_id}: carregado via llama-swap "
                          f"(operacao {op.operation_id})")
                    return 0
                # Backend systemd: comportamento atual.
                code = self.systemctl("start", model.unit)
                if code != 0:
                    logger.warning(
                        "start falhou systemctl: modelo=%s unidade=%s "
                        "codigo=%s",
                        model_id,
                        model.unit,
                        code,
                    )
                    print(f"Falha ao iniciar {model.unit} (codigo {code})",
                          file=sys.stderr)
                    self.coordinator.update_confirmed_status(
                        op.operation_id, "FAILED",
                        error=f"systemctl start codigo {code}",
                    )
                    if _unit_inactive(model.unit):
                        self.coordinator.release_engine(model_id)
                    return code
                # Aguarda o endpoint /health ficar disponivel.
                healthy = self.coordinator.wait_for_health(model_id)
                if not healthy:
                    logger.warning(
                        "start falhou health: modelo=%s unidade=%s",
                        model_id,
                        model.unit,
                    )
                    print(f"Falha: {model.unit} nao respondeu /health "
                          f"dentro do tempo esperado",
                          file=sys.stderr)
                    self.coordinator.update_confirmed_status(
                        op.operation_id, "FAILED",
                        error="timeout aguardando /health",
                    )
                    if _unit_inactive(model.unit):
                        self.coordinator.release_engine(model_id)
                    return 1
                self.coordinator.update_confirmed_status(
                    op.operation_id, "COMPLETED",
                )
                logger.info(
                    "start concluido: modelo=%s operacao=%s",
                    model_id,
                    op.operation_id,
                )
        except ExecutorBusy:
            logger.warning(
                "start bloqueado: troca de GPU ocupada: modelo=%s",
                model_id,
            )
            print("Bloqueio de troca de GPU ocupado", file=sys.stderr)
            self.coordinator.update_confirmed_status(
                op.operation_id, "FAILED",
                error="bloqueio de troca ocupado",
            )
            return 3
        print(f"{model_id}: iniciado (operacao {op.operation_id})")
        return 0

    # ---------------------------------------------------------------- stop

    def _cmd_stop(self, model_id):
        model = self.registry.get(model_id)
        if model is None:
            print(f"Modelo desconhecido: {model_id}", file=sys.stderr)
            return 1
        logger.info(
            "stop: modelo=%s unidade=%s backend=%s",
            model_id,
            model.unit,
            model.backend,
        )
        try:
            with switch_lock(self.lock_dir):
                if model.backend == "llama-swap":
                    # stop = endpoint de descarga do llama-swap.
                    ok, error = self.llama_swap_client.unload_model(model_id)
                    if not ok:
                        logger.warning(
                            "stop falhou llama-swap: modelo=%s erro=%s",
                            model_id,
                            error,
                        )
                        print(f"Falha ao descarregar {model_id} via "
                              f"llama-swap: {error}", file=sys.stderr)
                        return 1
                    self.coordinator.release_engine(model_id)
                    logger.info("stop concluido via llama-swap: modelo=%s",
                                model_id)
                    print(f"{model_id}: descarregado via llama-swap")
                    return 0
                # Backend systemd: comportamento atual.
                code = self.systemctl("stop", model.unit)
                if code == 0:
                    if not _unit_inactive(model.unit):
                        logger.warning(
                            "stop: unidade ainda ativa apos systemctl stop: "
                            "modelo=%s unidade=%s",
                            model_id,
                            model.unit,
                        )
                        print(f"Falha ao parar {model.unit}: servico ainda ativo",
                              file=sys.stderr)
                        return 1
                    self.coordinator.release_engine(model_id)
                    logger.info("stop concluido: modelo=%s", model_id)
        except ExecutorBusy:
            logger.warning(
                "stop bloqueado: troca de GPU ocupada: modelo=%s",
                model_id,
            )
            print("Bloqueio de troca de GPU ocupado", file=sys.stderr)
            return 3
        if code != 0:
            logger.warning(
                "stop falhou systemctl: modelo=%s unidade=%s codigo=%s",
                model_id,
                model.unit,
                code,
            )
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
                  "o switch aplica-se apenas a modelos exclusivos "
                  "(27B, Laguna GPU, Ornith)",
                  file=sys.stderr)
            return 3
        op = self.coordinator.request_switch(None, target_model_id)
        logger.info(
            "switch: alvo=%s operacao=%s grupo=%s",
            target_model_id,
            op.operation_id,
            to_model.exclusive_group,
        )
        try:
            with switch_lock(self.lock_dir):
                peers = [m for m in self.registry.exclusive_models()
                         if m.model_id != target_model_id
                         and m.exclusive_group == to_model.exclusive_group
                         and self._is_model_running(m.model_id)]
                if len(peers) > 1:
                    logger.warning(
                        "switch falhou: grupo com multiplos modelos ativos: "
                        "alvo=%s",
                        target_model_id,
                    )
                    self.coordinator.update_confirmed_status(
                        op.operation_id, "FAILED",
                        error="grupo com multiplos modelos ativos",
                    )
                    return 3
                if self._is_model_running(target_model_id):
                    if peers:
                        logger.warning(
                            "switch falhou: conflito no grupo exclusivo: "
                            "alvo=%s",
                            target_model_id,
                        )
                        self.coordinator.update_confirmed_status(
                            op.operation_id, "FAILED",
                            error="conflito no grupo exclusivo",
                        )
                        return 3
                    self.coordinator.reserve_engine(target_model_id,
                                                    requester="cli")
                    self.coordinator.update_confirmed_status(
                        op.operation_id, "COMPLETED")
                    logger.info(
                        "switch concluido (ja ativo): alvo=%s operacao=%s",
                        target_model_id,
                        op.operation_id,
                    )
                    print(f"{target_model_id} ja e o modelo ativo no slot "
                          "exclusivo")
                    return 0
                previous = peers[0] if peers else None
                if previous is not None:
                    logger.info("switch: parando modelo anterior=%s",
                                previous.model_id)
                    code = self.systemctl("stop", previous.unit)
                    if code != 0 or not _unit_inactive(previous.unit):
                        logger.warning(
                            "switch falhou: modelo anterior nao parou: "
                            "anterior=%s codigo=%s",
                            previous.model_id,
                            code,
                        )
                        self.coordinator.update_confirmed_status(
                            op.operation_id, "FAILED",
                            error="modelo anterior nao parou",
                        )
                        return code or 1
                    self.coordinator.release_engine(previous.model_id)
                    logger.info(
                        "switch: reserva anterior liberada: anterior=%s",
                        previous.model_id,
                    )
                    self._await_vram_release()
                try:
                    self.coordinator.reserve_engine(target_model_id,
                                                    requester="cli")
                    logger.info(
                        "switch: reserva obtida para alvo=%s operacao=%s",
                        target_model_id,
                        op.operation_id,
                    )
                except ExecutorBusy:
                    logger.warning(
                        "switch falhou: reserva conflitante: alvo=%s "
                        "operacao=%s",
                        target_model_id,
                        op.operation_id,
                    )
                    self.coordinator.update_confirmed_status(
                        op.operation_id, "FAILED",
                        error="reserva conflitante; reconciliar grupo",
                    )
                    return 3
                if not self.skip_vram_guard and not self._vram_ok():
                    logger.warning(
                        "switch falhou: VRAM insuficiente: alvo=%s",
                        target_model_id,
                    )
                    self.coordinator.release_engine(target_model_id)
                    self._restore_previous(previous,
                                           op.operation_id,
                                           "VRAM insuficiente")
                    return 3
                code = self.systemctl("start", to_model.unit)
                healthy = code == 0 and self.coordinator.wait_for_health(
                    target_model_id)
                if not healthy:
                    # A start timeout does not prove the process released its GPU.
                    logger.warning(
                        "switch: alvo nao ficou saudavel: alvo=%s codigo=%s",
                        target_model_id,
                        code,
                    )
                    stopped = _unit_inactive(to_model.unit)
                    if not stopped:
                        stopped = (self.systemctl("stop", to_model.unit) == 0
                                   and _unit_inactive(to_model.unit))
                    if not stopped:
                        logger.warning(
                            "switch ROLLBACK_FAILED: alvo nao parou; "
                            "reserva mantida: alvo=%s",
                            target_model_id,
                        )
                        self.coordinator.update_confirmed_status(
                            op.operation_id, "ROLLBACK_FAILED",
                            error="novo modelo nao parou; reserva mantida; "
                                  "reconciliar",
                        )
                        return code or 1
                    self.coordinator.release_engine(target_model_id)
                    self._restore_previous(previous,
                                           op.operation_id,
                                           "novo modelo falhou")
                    return code or 1
                self.coordinator.update_confirmed_status(
                    op.operation_id, "COMPLETED")
                logger.info(
                    "switch concluido: %s -> %s operacao=%s",
                    previous.model_id if previous else "-",
                    target_model_id,
                    op.operation_id,
                )
        except ExecutorBusy:
            logger.warning(
                "switch bloqueado: troca de GPU ocupada: alvo=%s",
                target_model_id,
            )
            print("Bloqueio de troca de GPU ocupado", file=sys.stderr)
            self.coordinator.update_confirmed_status(
                op.operation_id, "FAILED",
                error="bloqueio de troca ocupado",
            )
            return 3
        origem = previous.model_id if previous is not None else "-"
        print(f"Troca concluida: {origem} -> {target_model_id}")
        return 0

    def _restore_previous(self, previous, operation_id, error):
        if previous is None:
            self.coordinator.update_confirmed_status(operation_id, "FAILED",
                                                     error=error)
            return
        try:
            self.coordinator.reserve_engine(previous.model_id,
                                            requester="rollback")
        except ExecutorBusy:
            self.coordinator.update_confirmed_status(
                operation_id, "ROLLBACK_FAILED",
                error=f"{error}; reserva anterior indisponivel",
            )
            return
        code = self.systemctl("start", previous.unit)
        healthy = code == 0 and self.coordinator.wait_for_health(
            previous.model_id)
        if not healthy and _unit_inactive(previous.unit):
            self.coordinator.release_engine(previous.model_id)
        self.coordinator.update_confirmed_status(
            operation_id,
            "ROLLED_BACK" if healthy else "ROLLBACK_FAILED",
            error=error,
        )

    def _await_vram_release(self):
        """Aguarda ate VRAM_RELEASE_WAIT_SECONDS pela liberacao da GPU."""
        deadline = time.monotonic() + VRAM_RELEASE_WAIT_SECONDS
        while time.monotonic() < deadline:
            free = self.gpu_monitor.free_mb()
            if free is not None and free >= VRAM_GUARD_MIN_FREE_MB:
                return
            time.sleep(VRAM_RELEASE_POLL_SECONDS)

    def _is_model_running(self, model_id):
        """Retorna True se o modelo esta rodando; False se nao puder
        verificar."""
        try:
            st = self.coordinator.ensure_ready(model_id)
        except OSError:
            return False
        return st.service == "running"

    # ---------------------------------------------------------------- vram

    def _cmd_vram(self):
        gpus = self.gpu_monitor.query_vram()
        gpu_index = self.gpu_monitor.gpu_index
        free_target = self.gpu_monitor.free_mb()
        print("VRAM por GPU (nvidia-smi):")
        if gpus:
            for g in gpus:
                marker = " (alvo)" if g.index == gpu_index else ""
                print(f"  GPU {g.index} {g.name}: "
                      f"usada {g.used_mb} MB / total {g.total_mb} MB / "
                      f"livre {g.free_mb} MB{marker}")
        else:
            print("  nvidia-smi indisponivel; nao foi possivel medir VRAM")
        print()
        if free_target is not None:
            print(f"VRAM livre GPU {gpu_index}: {free_target} MB")
            if free_target < VRAM_GUARD_MIN_FREE_MB:
                print("AVISO: folga abaixo de 1,5 GB; start/switch serao "
                      "recusados")
        else:
            print(f"VRAM livre GPU {gpu_index}: indisponivel")
        print()
        print("Ultima medida registrada por modelo (SQLite):")
        if self.vram_store is None:
            print("  armazenamento nao configurado")
        else:
            with self.vram_store.db:
                rows = self.vram_store.all()
            if not rows:
                print("  (nenhuma medida registrada)")
            for row in rows:
                print(f"  {row['model_id']} ctx={row['context_size']}: "
                      f"{row['vram_used_mb']} MB (medido em "
                      f"{row['measured_at']})")
        return 0

    # ------------------------------------------------------------- gen-llama-swap

    def _cmd_gen_llama_swap(self):
        """Gera deploy/llama-swap/config.yaml a partir do registro.

        Nunca edita a mao: usa os argumentos EXATOS das units do registro,
        com ${PORT} no lugar da porta fixa.
        """
        import yaml
        models = []
        for m in self.registry.list():
            if m.backend != "llama-swap":
                continue
            port = self._port(m.endpoint)
            models.append({
                "id": m.model_id,
                "name": f"{m.model_id} (piloto llama-swap)",
                "backend": "llama-swap",
                "cmd": [
                    "/home/igor/opt/prism-pascal-build/install/bin/llama-server",
                    "-m",
                    "/home/igor/models/bonsai-4b/Ternary-Bonsai-2-4B-Q4_K_M.gguf",
                    "--host", "127.0.0.1",
                    "--port", "${PORT}",
                    "-c", "64000",
                    "-t", "8",
                    "-ngl", "99",
                    "--flash-attn", "on",
                    "-n", "2048",
                    "--parallel", "1",
                    "--no-jinja",
                    "--threads-http", "4",
                    "--slot-save-path", "/var/lib/pcsala-worker/slots",
                ],
                "env": {
                    "LD_LIBRARY_PATH": "/home/igor/opt/prism-pascal-build/install/lib",
                },
                "ttl": 3600,
                "healthCheckTimeout": m.health_timeout_seconds,
                "port": port,
            })
        config = {"version": 1, "models": models}
        output = "deploy/llama-swap/config.yaml"
        try:
            with open(output, "w", encoding="utf-8") as f:
                yaml.safe_dump(config, f, sort_keys=False, allow_unicode=True)
        except ImportError:
            print("Erro: PyYAML nao instalado. Rode: pip install pyyaml",
                  file=sys.stderr)
            return 1
        except OSError as exc:
            print(f"Erro ao escrever {output}: {exc}", file=sys.stderr)
            return 1
        print(f"Gerado {output} com {len(models)} modelo(s) backend llama-swap.")
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
            # nvidia-smi indisponível: falha fechada
            return False
        return free >= VRAM_GUARD_MIN_FREE_MB

    @staticmethod
    def _port(endpoint):
        return endpoint.rsplit(":", 1)[-1]

    @staticmethod
    def _run_systemctl(action, unit):
        import subprocess
        try:
            result = subprocess.run(
                ["systemctl", action, unit],
                check=False, capture_output=True, text=True, timeout=30,
            )
            return result.returncode
        except subprocess.TimeoutExpired:
            return 124
        except OSError:
            return 127


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="pcsala models", description="Gestao de modelos pc-sala-agent")
    parser.add_argument("--root", default="/var/lib/pcsala-worker")
    parser.add_argument("--db", default=None,
                        help="Caminho do SQLite (default: <root>/state.sqlite)")
    parser.add_argument("--sem-guarda-vram", action="store_true",
                        help="Ignora a guarda de VRAM (uso por conta propria)")
    parser.add_argument("--llama-swap-url", default=None,
                        help="URL base do proxy llama-swap "
                             "(padrao: http://127.0.0.1:8093)")
    parser.add_argument("command", choices=[
        "list", "status", "health", "start", "stop", "switch", "vram",
        "operation", "gen-llama-swap",
    ])
    parser.add_argument("model_id", nargs="?")
    args = parser.parse_args(argv)

    if args.command in ("status", "health", "start", "stop", "switch",
                        "operation") and not args.model_id:
        parser.error(f"{args.command} requer um modelo")

    db_path = args.db
    if db_path is None:
        db_path = str(Path(args.root) / "state.sqlite")

    llama_swap_url = args.llama_swap_url
    if llama_swap_url is None:
        llama_swap_url = os.environ.get(
            "PCSALA_LLAMA_SWAP_URL", "http://127.0.0.1:8093")
    llama_swap_client = LlamaSwapClient(llama_swap_url)

    with ModelsCLI(
        db_path=db_path,
        skip_vram_guard=args.sem_guarda_vram,
        llama_swap_client=llama_swap_client,
    ) as cli:
        command_args = [args.command]
        if args.model_id:
            command_args.append(args.model_id)
        return cli.run(command_args)


if __name__ == "__main__":
    sys.exit(main())
