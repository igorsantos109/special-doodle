import dataclasses
import secrets
import socket
import urllib.error
from pathlib import Path

from .database import connect

KNOWN_MODELS = (
    "bonsai-27b-gpu",
    "bonsai-9b-cpu",
    "laguna-xs-2.1-cpu",
    "laguna-xs-2.1-gpu",
    "ornith-35b-gpu",
)


@dataclasses.dataclass(frozen=True)
class ModelSpec:
    model_id: str
    model_class: str
    profile: str
    unit: str
    shared: bool
    exclusive_group: str | None
    endpoint: str
    capabilities: tuple


class ModelRegistry:
    def __init__(self):
        self._models = {
            "bonsai-27b-gpu": ModelSpec(
                model_id="bonsai-27b-gpu", model_class="GPU",
                profile="gpu-triage-v1", unit="bonsai2-27b.service",
                shared=False, exclusive_group="gpu-slot-1",
                endpoint="http://127.0.0.1:8080",
                capabilities=("triagem", "raciocinio"),
            ),
            "bonsai-9b-cpu": ModelSpec(
                model_id="bonsai-9b-cpu", model_class="CPU",
                profile="cpu-triage-v1", unit="bonsai2-cpu.service",
                shared=True, exclusive_group=None,
                endpoint="http://127.0.0.1:8090",
                capabilities=("triagem", "compressao"),
            ),
            "laguna-xs-2.1-cpu": ModelSpec(
                model_id="laguna-xs-2.1-cpu", model_class="CPU",
                profile="laguna-programming-v1", unit="laguna.service",
                shared=True, exclusive_group=None,
                endpoint="http://127.0.0.1:8091",
                capabilities=("programacao", "contexto-longo"),
            ),
            "laguna-xs-2.1-gpu": ModelSpec(
                model_id="laguna-xs-2.1-gpu", model_class="GPU",
                profile="laguna-programming-v1", unit="laguna-gpu.service",
                shared=False, exclusive_group="gpu-slot-1",
                endpoint="http://127.0.0.1:8082",
                capabilities=("programacao", "contexto-longo"),
            ),
            "ornith-35b-gpu": ModelSpec(
                model_id="ornith-35b-gpu", model_class="GPU",
                profile="gpu-triage-v1", unit="ornith.service",
                shared=False, exclusive_group="gpu-slot-1",
                endpoint="http://127.0.0.1:8092",
                capabilities=("programacao", "triagem"),
            ),
        }

    def get(self, model_id):
        return self._models.get(model_id)

    def list(self):
        return list(self._models.values())


def _check_model_server(host="127.0.0.1", port=8090):
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


class ModelCoordinator:
    def __init__(self, registry, database=None):
        self.registry = registry
        self.database = database

    def _db(self):
        if self.database is None:
            return None
        if isinstance(self.database, (str, Path)):
            return connect(self.database)
        return self.database

    def ensure_ready(self, model_id):
        model = self.registry.get(model_id)
        if model is None:
            raise ValueError(f"Modelo desconhecido: {model_id}")
        healthy = _check_model_server(
            model.endpoint.split("://")[1].split("/")[0].split(":")[0],
            int(model.endpoint.split(":")[-1]),
        )
        active = _unit_active(model.unit)
        return ModelStatus(
            service="running" if active else "stopped",
            health="healthy" if healthy else "unhealthy",
        )

    def request_start(self, model_id):
        model = self.registry.get(model_id)
        if model is None:
            raise ValueError(f"Modelo desconhecido: {model_id}")
        db = self._db()
        operation_id = secrets.token_hex(8)
        if db is not None:
            db.execute(
                """CREATE TABLE IF NOT EXISTS model_operations (
                operation_id TEXT PRIMARY KEY,
                idempotency_key TEXT,
                requester TEXT NOT NULL DEFAULT 'system',
                session_id TEXT,
                task_id TEXT,
                attempt_id TEXT,
                action TEXT NOT NULL,
                target_model_id TEXT NOT NULL,
                previous_status TEXT,
                requested_status TEXT,
                confirmed_status TEXT,
                authorization_used TEXT,
                status TEXT NOT NULL DEFAULT 'REQUESTED',
                error TEXT,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
            )"""
            )
            db.execute(
                """INSERT INTO model_operations
                (operation_id, action, target_model_id, requested_status, status)
                VALUES (?, 'start', ?, 'READY', 'REQUESTED')""",
                (operation_id, model_id),
            )
            db.commit()
        return ModelOperation(operation_id=operation_id)

    def get_operation(self, operation_id, database=None):
        db = database
        own = False
        if db is None:
            db = self._db()
        elif isinstance(db, (str, Path)):
            db = connect(db)
            own = True
        if db is None:
            return None
        try:
            row = db.execute(
                "SELECT * FROM model_operations WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
        finally:
            if own:
                db.close()
        if row is None:
            return None
        return dict(row)


def _unit_active(unit):
    import subprocess
    try:
        result = subprocess.run(
            ["systemctl", "is-active", unit],
            capture_output=True, text=True, timeout=3,
        )
        return result.stdout.strip() == "active"
    except Exception:
        return False


class ModelStatus:
    def __init__(self, service, health):
        self.service = service
        self.health = health


class ModelOperation:
    def __init__(self, operation_id):
        self.operation_id = operation_id


def _connect_cm(database):
    return connect(database)
