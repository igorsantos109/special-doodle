from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from .database import connect
from .locking import database_lock
from .migrations import migrate


ModelClass = Literal["CPU", "GPU"]
ServiceStatus = Literal["unknown", "running", "stopped", "failed", "activating", "deactivating"]
HealthStatus = Literal["unknown", "healthy", "degraded", "unreachable", "unauthorized"]
OperationAction = Literal["start", "stop", "switch"]
OperationStatus = Literal["REQUESTED", "APPROVED", "IN_PROGRESS", "COMPLETED", "FAILED", "REJECTED", "BUSY"]


class ModelInfo(BaseModel):
    model_config = {"extra": "forbid", "frozen": True}

    model_id: str
    name: str
    description: str = ""
    model_class: ModelClass
    endpoint: str
    health_path: str = "/health"
    health_timeout: int = 5
    unit: str
    api_key_env: str = "DSH_LOCAL_API_KEY"
    capabilities: list[str] = Field(default_factory=list)
    exclusive_group: str | None = None
    shared: bool = True
    allowed_operations: list[str] = Field(default_factory=lambda: ["start", "stop", "health"])
    startup_timeout: int = 60
    health_interval: int = 30
    profile: str | None = None


class ModelStatusResult(BaseModel):
    model_config = {"extra": "forbid", "frozen": True}

    model_id: str
    service: ServiceStatus
    health: HealthStatus
    health_checked_at: str | None = None
    active_task: str | None = None


class ModelOperationRequest(BaseModel):
    model_config = {"extra": "forbid", "frozen": True}

    action: OperationAction
    target_model_id: str
    requester: str
    session_id: str | None = None
    task_id: str | None = None
    attempt_id: str | None = None
    execution_context: dict[str, Any] = Field(default_factory=dict)


class ModelOperationResult(BaseModel):
    model_config = {"extra": "forbid"}

    operation_id: str
    status: OperationStatus
    action: OperationAction
    target_model_id: str
    message: str = ""
    error: str = ""
    approved_at: str | None = None
    completed_at: str | None = None


_MODELS_CONFIG_PATH = Path("/home/igor/.config/pcsala-bonsai/models.json")
_API_KEY_PATH = Path("/home/igor/.config/pcsala-bonsai/api.key")
_UNIT_WHITELIST = {"bonsai2-27b.service", "bonsai2-cpu.service", "laguna.service",
                    "laguna-gpu.service", "ornith.service"}
_GPU_UNIT = "bonsai2-27b.service"
_GPU_EXCLUSIVE_GROUP = "gpu-slot-1"


def _default_models() -> list[ModelInfo]:
    return [
        ModelInfo(
            model_id="bonsai-27b-gpu",
            name="Bonsai 2 27B GPU",
            description="Bonsai 2 27B PQ2_0 em GPU (porta 8080)",
            model_class="GPU",
            endpoint="http://127.0.0.1:8080",
            unit="bonsai2-27b.service",
            exclusive_group=_GPU_EXCLUSIVE_GROUP,
            shared=False,
            allowed_operations=["start", "stop", "health"],
            startup_timeout=120,
            capabilities=["inferencia_texto", "raciocinio_avancado"],
            profile="gpu-triage-v1",
        ),
        ModelInfo(
            model_id="bonsai-9b-cpu",
            name="Bonsai 2 9B CPU",
            description="Bonsai 2 9B PQ2_0 em CPU (porta 8090)",
            model_class="CPU",
            endpoint="http://127.0.0.1:8090",
            unit="bonsai2-cpu.service",
            exclusive_group=None,
            shared=True,
            allowed_operations=["start", "stop", "health"],
            startup_timeout=60,
            capabilities=["inferencia_texto", "compressao_contexto"],
            profile="cpu-triage-v1",
        ),
        ModelInfo(
            model_id="laguna-xs-2.1-cpu",
            name="Laguna XS 2.1 CPU",
            description="Laguna XS 2.1 (poolside, 33B param, ~3B activos/token) "
                        "para programacao e depuracao, CPU (porta 8091)",
            model_class="CPU",
            endpoint="http://127.0.0.1:8091",
            unit="laguna.service",
            exclusive_group=None,
            shared=True,
            allowed_operations=["start", "stop", "health"],
            startup_timeout=120,
            capabilities=["inferencia_texto", "programacao", "geracao_codigo",
                          "depuracao", "raciocinio_tecnico"],
profile="laguna-programming-v1",
        ),
        ModelInfo(
            model_id="laguna-xs-2.1-gpu",
            name="Laguna XS 2.1 GPU",
            description="Laguna XS 2.1 APEX I-Compact em GPU via PrismML Pascal "
                        "(porta 8082, 128K contexto)",
            model_class="GPU",
            endpoint="http://127.0.0.1:8082",
            unit="laguna-gpu.service",
            exclusive_group=_GPU_EXCLUSIVE_GROUP,
            shared=False,
            allowed_operations=["start", "stop", "health"],
            startup_timeout=120,
            capabilities=["inferencia_texto", "programacao", "geracao_codigo",
                          "depuracao", "raciocinio_tecnico"],
            profile="laguna-programming-v1",
        ),
        ModelInfo(
            model_id="ornith-35b-gpu",
            name="Ornith 1.0 35B GPU",
            description="Ornith 1.0 35B MTP Q4_K_M em GPU (porta 8092, 16K contexto)",
            model_class="GPU",
            endpoint="http://127.0.0.1:8092",
            unit="ornith.service",
            exclusive_group=_GPU_EXCLUSIVE_GROUP,
            shared=False,
            allowed_operations=["start", "stop", "health"],
            startup_timeout=120,
            capabilities=["inferencia_texto", "raciocinio_avancado", "geracao_codigo"],
            profile="gpu-triage-v1",
        ),
    ]
 
 
def _load_registry() -> list[ModelInfo]:
    path = _MODELS_CONFIG_PATH
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                return [ModelInfo(**entry) for entry in raw]
        except (json.JSONDecodeError, Exception):
            pass
    return _default_models()


def _get_api_key() -> str:
    if _API_KEY_PATH.exists():
        return _API_KEY_PATH.read_text(encoding="utf-8").strip()
    return os.environ.get("DSH_LOCAL_API_KEY", "")


def _check_service_status(unit: str) -> ServiceStatus:
    try:
        out = subprocess.run(
            ["systemctl", "is-active", unit],
            capture_output=True, text=True, timeout=10,
        )
        stdout = out.stdout.strip()
        mapping: dict[str, ServiceStatus] = {
            "active": "running",
            "inactive": "stopped",
            "failed": "failed",
            "activating": "activating",
            "deactivating": "deactivating",
        }
        return mapping.get(stdout, "unknown")
    except Exception:
        return "unknown"


def _check_http_health(endpoint: str, api_key: str, path: str = "/health", timeout: int = 5) -> HealthStatus:
    try:
        import urllib.request
        url = endpoint.rstrip("/") + path
        headers = {}
        if api_key:
            headers["Authorization"] = "Bearer " + api_key
        req = urllib.request.Request(url, headers=headers, method="GET")
        resp = urllib.request.urlopen(req, timeout=timeout)
        if resp.status == 200:
            return "healthy"
        return "degraded"
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return "unauthorized"
        return "degraded"
    except (urllib.error.URLError, OSError, socket.timeout):
        return "unreachable"


def _check_tcp_health(host: str, port: int, timeout: int = 3) -> bool:
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return True
    except (OSError, socket.timeout):
        return False


class ModelRegistry:
    def __init__(self) -> None:
        self._models: dict[str, ModelInfo] = {}
        self._reload()

    def _reload(self) -> None:
        self._models = {m.model_id: m for m in _load_registry()}

    def list(self) -> list[ModelInfo]:
        self._reload()
        return list(self._models.values())

    def get(self, model_id: str) -> ModelInfo | None:
        self._reload()
        return self._models.get(model_id)

    def list_by_class(self, model_class: ModelClass) -> list[ModelInfo]:
        self._reload()
        return [m for m in self._models.values() if m.model_class == model_class]

    def get_by_unit(self, unit: str) -> ModelInfo | None:
        self._reload()
        for m in self._models.values():
            if m.unit == unit:
                return m
        return None

    def get_by_profile(self, profile: str) -> ModelInfo | None:
        self._reload()
        for m in self._models.values():
            if m.profile == profile:
                return m
        return None

    def is_known(self, model_id: str) -> bool:
        return self.get(model_id) is not None

    def validate_target(self, model_id: str) -> ModelInfo:
        m = self.get(model_id)
        if m is None:
            raise ValueError(f"Modelo desconhecido: {model_id}")
        return m


class ModelCoordinator:
    GPU_SWITCH_LOCK = "/tmp/pcsala-gpu-switch.lock"

    def __init__(self, registry: ModelRegistry, database: Path | None = None) -> None:
        self._registry = registry
        self._database = database
        self._engine_reservations: dict[str, str | None] = {}
        if database is not None:
            migrate(database)

    def _check_authorized(self, model: ModelInfo, action: str) -> None:
        if action not in model.allowed_operations:
            raise PermissionError(
                f"Operacao '{action}' nao autorizada para modelo '{model.model_id}'"
            )

    def _check_unit_whitelist(self, unit: str) -> None:
        if unit not in _UNIT_WHITELIST:
            raise PermissionError(f"Unidade nao autorizada: {unit}")

    def status(self, model_id: str) -> ModelStatusResult:
        model = self._registry.validate_target(model_id)
        service = _check_service_status(model.unit)
        host, port = self._parse_endpoint(model.endpoint)

        api_key = _get_api_key()
        health: HealthStatus = "unknown"
        checked_at: str | None = None

        if service == "running":
            if _check_tcp_health(host, port):
                health = _check_http_health(model.endpoint, api_key, model.health_path, model.health_timeout)
                checked_at = datetime.now(timezone.utc).isoformat()
            else:
                health = "unreachable"
        elif service == "stopped":
            health = "unknown"

        return ModelStatusResult(
            model_id=model_id,
            service=service,
            health=health,
            health_checked_at=checked_at,
            active_task=self._engine_reservations.get(model_id),
        )

    def health(self, model_id: str) -> ModelStatusResult:
        return self.status(model_id)

    def ensure_ready(self, model_id: str, execution_context: dict[str, Any] | None = None) -> ModelStatusResult:
        st = self.status(model_id)
        if st.service == "running" and st.health == "healthy":
            return st
        if st.service == "running" and st.health == "unreachable":
            return ModelStatusResult(
                model_id=model_id,
                service=st.service,
                health="unreachable",
                health_checked_at=st.health_checked_at,
                active_task=st.active_task,
            )
        if st.service == "stopped":
            return ModelStatusResult(
                model_id=model_id,
                service="stopped",
                health="unknown",
                health_checked_at=None,
            )
        return st

    def request_start(self, model_id: str, execution_context: dict[str, Any] | None = None) -> ModelOperationResult:
        model = self._registry.validate_target(model_id)
        self._check_authorized(model, "start")
        engine = execution_context or {}
        op_id = str(uuid4())

        if model.model_class == "GPU":
            current_gpu = self._find_active_gpu()
            if current_gpu and current_gpu != model_id:
                self._persist_operation(op_id, "start", model_id, "BUSY", engine)
                return ModelOperationResult(
                    operation_id=op_id,
                    status="BUSY",
                    action="start",
                    target_model_id=model_id,
                    message=f"GPU ocupada por '{current_gpu}'. Use 'switch' para trocar.",
                )

        st = _check_service_status(model.unit)
        if st == "running":
            self._persist_operation(op_id, "start", model_id, "COMPLETED", engine)
            return ModelOperationResult(
                operation_id=op_id,
                status="COMPLETED",
                action="start",
                target_model_id=model_id,
                message=f"Modelo '{model_id}' ja em execucao.",
                completed_at=datetime.now(timezone.utc).isoformat(),
            )

        self._persist_operation(op_id, "start", model_id, "REQUESTED", engine)
        try:
            self._check_unit_whitelist(model.unit)
            result = subprocess.run(
                ["systemctl", "start", model.unit],
                capture_output=True, text=True, timeout=model.startup_timeout + 10,
            )
            if result.returncode != 0:
                self._persist_operation(op_id, "start", model_id, "FAILED", engine,
                                        error=result.stderr.strip())
                return ModelOperationResult(
                    operation_id=op_id, status="FAILED", action="start",
                    target_model_id=model_id, error=result.stderr.strip(),
                )
            self._persist_operation(op_id, "start", model_id, "IN_PROGRESS", engine)
            self._await_service_ready(model.unit, model)
            self._persist_operation(op_id, "start", model_id, "COMPLETED", engine)
            return ModelOperationResult(
                operation_id=op_id, status="COMPLETED", action="start",
                target_model_id=model_id,
                message=f"Modelo '{model_id}' iniciado.",
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
        except subprocess.TimeoutExpired:
            self._persist_operation(op_id, "start", model_id, "FAILED", engine,
                                    error="Timeout no start via systemctl")
            return ModelOperationResult(
                operation_id=op_id, status="FAILED", action="start",
                target_model_id=model_id, error="Timeout no start",
            )
        except PermissionError:
            self._persist_operation(op_id, "start", model_id, "REJECTED", engine,
                                    error="Unidade nao autorizada")
            return ModelOperationResult(
                operation_id=op_id, status="REJECTED", action="start",
                target_model_id=model_id, error="Unidade nao autorizada",
            )
        except Exception as e:
            self._persist_operation(op_id, "start", model_id, "FAILED", engine, error=str(e))
            return ModelOperationResult(
                operation_id=op_id, status="FAILED", action="start",
                target_model_id=model_id, error=str(e),
            )

    def request_stop(self, model_id: str, execution_context: dict[str, Any] | None = None) -> ModelOperationResult:
        model = self._registry.validate_target(model_id)
        self._check_authorized(model, "stop")

        if model.shared:
            op_id = str(uuid4())
            self._persist_operation(op_id, "stop", model_id, "REJECTED", execution_context or {})
            return ModelOperationResult(
                operation_id=op_id, status="REJECTED", action="stop",
                target_model_id=model_id,
                message=f"Modelo compartilhado '{model_id}' nao pode ser parado por requisicao individual.",
            )

        engine = execution_context or {}
        op_id = str(uuid4())

        st = _check_service_status(model.unit)
        if st == "stopped":
            self._persist_operation(op_id, "stop", model_id, "COMPLETED", engine)
            return ModelOperationResult(
                operation_id=op_id, status="COMPLETED", action="stop",
                target_model_id=model_id,
                message=f"Modelo '{model_id}' ja parado.",
                completed_at=datetime.now(timezone.utc).isoformat(),
            )

        if self._engine_reservations.get(model_id):
            self._persist_operation(op_id, "stop", model_id, "BUSY", engine)
            return ModelOperationResult(
                operation_id=op_id, status="BUSY", action="stop",
                target_model_id=model_id,
                message=f"Modelo '{model_id}' com inferencia em curso. Aguarde conclusao.",
            )

        self._persist_operation(op_id, "stop", model_id, "REQUESTED", engine)
        try:
            result = subprocess.run(
                ["systemctl", "stop", model.unit],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                self._persist_operation(op_id, "stop", model_id, "FAILED", engine,
                                        error=result.stderr.strip())
                return ModelOperationResult(
                    operation_id=op_id, status="FAILED", action="stop",
                    target_model_id=model_id, error=result.stderr.strip(),
                )
            self._persist_operation(op_id, "stop", model_id, "COMPLETED", engine)
            return ModelOperationResult(
                operation_id=op_id, status="COMPLETED", action="stop",
                target_model_id=model_id,
                message=f"Modelo '{model_id}' parado.",
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as e:
            self._persist_operation(op_id, "stop", model_id, "FAILED", engine, error=str(e))
            return ModelOperationResult(
                operation_id=op_id, status="FAILED", action="stop",
                target_model_id=model_id, error=str(e),
            )

    def request_switch(self, model_id: str, execution_context: dict[str, Any] | None = None) -> ModelOperationResult:
        model = self._registry.validate_target(model_id)
        self._check_authorized(model, "start")
        engine = execution_context or {}
        op_id = str(uuid4())

        if model.model_class != "GPU":
            self._persist_operation(op_id, "switch", model_id, "REJECTED", engine)
            return ModelOperationResult(
                operation_id=op_id, status="REJECTED", action="switch",
                target_model_id=model_id,
                message=f"Switch so e aplicavel a modelos GPU. '{model_id}' e {model.model_class}.",
            )

        current_gpu = self._find_active_gpu()
        if current_gpu is None:
            return self.request_start(model_id, execution_context)

        if current_gpu == model_id:
            self._persist_operation(op_id, "switch", model_id, "COMPLETED", engine)
            return ModelOperationResult(
                operation_id=op_id, status="COMPLETED", action="switch",
                target_model_id=model_id,
                message=f"Modelo '{model_id}' ja e o GPU ativo.",
                completed_at=datetime.now(timezone.utc).isoformat(),
            )

        current_model = self._registry.get(current_gpu)
        if current_model and self._engine_reservations.get(current_gpu):
            self._persist_operation(op_id, "switch", model_id, "BUSY", engine)
            return ModelOperationResult(
                operation_id=op_id, status="BUSY", action="switch",
                target_model_id=model_id,
                message=f"GPU ocupada por '{current_gpu}' com inferencia em curso. Aguarde.",
            )

        switch_lock = Path(self.GPU_SWITCH_LOCK)
        try:
            lock_fd = os.open(str(switch_lock), os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o600)
            import fcntl
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                os.close(lock_fd)
                self._persist_operation(op_id, "switch", model_id, "BUSY", engine)
                return ModelOperationResult(
                    operation_id=op_id, status="BUSY", action="switch",
                    target_model_id=model_id,
                    message="Transicao GPU ja em curso por outro processo.",
                )
        except Exception:
            self._persist_operation(op_id, "switch", model_id, "FAILED", engine,
                                    error="Nao foi possivel obter bloqueio de transicao.")
            return ModelOperationResult(
                operation_id=op_id, status="FAILED", action="switch",
                target_model_id=model_id, error="Nao foi possivel obter bloqueio de transicao.",
            )

        self._persist_operation(op_id, "switch", model_id, "IN_PROGRESS", engine)

        try:
            stop_result = subprocess.run(
                ["systemctl", "stop", current_model.unit if current_model else _GPU_UNIT],
                capture_output=True, text=True, timeout=30,
            )
            if stop_result.returncode != 0:
                self._persist_operation(op_id, "switch", model_id, "FAILED", engine,
                                        error=f"Falha ao parar {current_gpu}: {stop_result.stderr.strip()}")
                return ModelOperationResult(
                    operation_id=op_id, status="FAILED", action="switch",
                    target_model_id=model_id,
                    error=f"Falha ao parar {current_gpu}: {stop_result.stderr.strip()}",
                )

            status_after_stop = _check_service_status(current_model.unit if current_model else _GPU_UNIT)
            if status_after_stop == "running":
                self._persist_operation(op_id, "switch", model_id, "FAILED", engine,
                                        error=f"Unidade {current_gpu} nao parou apos comando stop.")
                return ModelOperationResult(
                    operation_id=op_id, status="FAILED", action="switch",
                    target_model_id=model_id,
                    error=f"Unidade {current_gpu} nao parou.",
                )

            start_result = subprocess.run(
                ["systemctl", "start", model.unit],
                capture_output=True, text=True, timeout=model.startup_timeout + 10,
            )
            if start_result.returncode != 0:
                self._persist_operation(op_id, "switch", model_id, "FAILED", engine,
                                        error=f"Falha ao iniciar {model_id}: {start_result.stderr.strip()}")
                return ModelOperationResult(
                    operation_id=op_id, status="FAILED", action="switch",
                    target_model_id=model_id,
                    error=f"Falha ao iniciar {model_id} apos parar {current_gpu}.",
                )

            self._await_service_ready(model.unit, model)
            self._persist_operation(op_id, "switch", model_id, "COMPLETED", engine)
            return ModelOperationResult(
                operation_id=op_id, status="COMPLETED", action="switch",
                target_model_id=model_id,
                message=f"Troca GPU concluida: {current_gpu} → {model_id}.",
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as e:
            self._persist_operation(op_id, "switch", model_id, "FAILED", engine, error=str(e))
            return ModelOperationResult(
                operation_id=op_id, status="FAILED", action="switch",
                target_model_id=model_id, error=str(e),
            )
        finally:
            try:
                if 'lock_fd' in dir():
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                    os.close(lock_fd)
            except Exception:
                pass

    def reserve_engine(self, model_id: str, task_id: str) -> None:
        self._engine_reservations[model_id] = task_id

    def release_engine(self, model_id: str) -> None:
        self._engine_reservations[model_id] = None

    def reconcile_reservations(self) -> None:
        for model_id in list(self._engine_reservations.keys()):
            task = self._engine_reservations[model_id]
            if task is not None:
                st = _check_service_status(self._registry.get(model_id).unit if self._registry.get(model_id) else "")
                if st != "running":
                    self._engine_reservations[model_id] = None

    def get_operation(self, operation_id: str, database: Path | None = None) -> dict[str, Any] | None:
        db_path = database or self._database
        if db_path is None:
            return None
        db_path = Path(db_path).resolve()
        if not db_path.exists():
            return None
        with database_lock(db_path):
            db = connect(db_path)
            try:
                row = db.execute(
                    "SELECT * FROM model_operations WHERE operation_id=?",
                    (operation_id,),
                ).fetchone()
                return dict(row) if row else None
            finally:
                db.close()

    def _find_active_gpu(self) -> str | None:
        for m in self._registry.list_by_class("GPU"):
            st = _check_service_status(m.unit)
            if st == "running":
                return m.model_id
        return None

    def _parse_endpoint(self, endpoint: str) -> tuple[str, int]:
        from urllib.parse import urlparse
        parsed = urlparse(endpoint)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 8080
        return host, port

    def _await_service_ready(self, unit: str, model: ModelInfo) -> None:
        deadline = time.monotonic() + model.startup_timeout
        while time.monotonic() < deadline:
            st = _check_service_status(unit)
            if st == "running":
                host, port = self._parse_endpoint(model.endpoint)
                if _check_tcp_health(host, port, timeout=2):
                    api_key = _get_api_key()
                    if api_key:
                        h = _check_http_health(model.endpoint, api_key, model.health_path, 3)
                        if h == "healthy":
                            return
                        if h == "unauthorized":
                            return
                    else:
                        return
            time.sleep(2)
        raise TimeoutError(f"Modelo '{model.model_id}' nao ficou pronto em {model.startup_timeout}s")

    def _persist_operation(self, op_id: str, action: str, target: str,
                           status: str, engine: dict[str, Any] | None = None,
                           error: str = "") -> None:
        db_path = self._database
        if db_path is None:
            return
        db_path = Path(db_path).resolve()
        try:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            migrate(db_path)
            with database_lock(db_path):
                db = connect(db_path)
                try:
                    db.execute(
                        """INSERT OR IGNORE INTO model_operations
                        (operation_id, action, target_model_id,
                         requester, session_id, task_id, attempt_id,
                         status, error)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (op_id, action, target,
                         (engine or {}).get("requester", "system"),
                         (engine or {}).get("session_id"),
                         (engine or {}).get("task_id"),
                         (engine or {}).get("attempt_id"),
                         status, error),
                    )
                    db.commit()
                except Exception:
                    db.rollback()
                finally:
                    db.close()
        except Exception:
            pass

    def _update_operation_status(self, op_id: str, status: str, error: str = "") -> None:
        db_path = self._database
        if db_path is None:
            return
        db_path = Path(db_path).resolve()
        if not db_path.exists():
            return
        try:
            migrate(db_path)
            with database_lock(db_path):
                db = connect(db_path)
                try:
                    db.execute(
                        "UPDATE model_operations SET status=?, error=? WHERE operation_id=?",
                        (status, error, op_id),
                    )
                    db.commit()
                except Exception:
                    db.rollback()
                finally:
                    db.close()
        except Exception:
            pass