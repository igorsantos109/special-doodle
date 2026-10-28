import dataclasses
import secrets
import socket
import subprocess
from pathlib import Path

from .database import connect

GPU_SWITCH_LOCK_DIR = Path("/run/pcsala")


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
    health_timeout_seconds: int = 600
    backend: str = "systemd"


class ModelRegistry:
    def __init__(self):
        self._models = {
            "bonsai-27b-gpu": ModelSpec(
                model_id="bonsai-27b-gpu", model_class="GPU",
                profile="gpu-triage-v1", unit="bonsai2-27b.service",
                shared=False, exclusive_group="gpu-slot-1",
                endpoint="http://127.0.0.1:8080",
                capabilities=("triagem", "raciocinio"),
                health_timeout_seconds=600,
            ),
            "bonsai-4b-gpu": ModelSpec(
                model_id="bonsai-4b-gpu", model_class="GPU",
                profile="gpu-triage-v1", unit="bonsai-4b-gpu.service",
                shared=True, exclusive_group=None,
                endpoint="http://127.0.0.1:8093",
                capabilities=("triagem", "resumo"),
                health_timeout_seconds=120,
                backend="llama-swap",
            ),
            "bonsai-9b-cpu": ModelSpec(
                model_id="bonsai-9b-cpu", model_class="CPU",
                profile="cpu-triage-v1", unit="bonsai2-cpu.service",
                shared=True, exclusive_group=None,
                endpoint="http://127.0.0.1:8090",
                capabilities=("triagem", "compressao"),
                health_timeout_seconds=120,
            ),
            "laguna-xs-2.1-cpu": ModelSpec(
                model_id="laguna-xs-2.1-cpu", model_class="CPU",
                profile="laguna-programming-v1", unit="laguna.service",
                shared=True, exclusive_group=None,
                endpoint="http://127.0.0.1:8091",
                capabilities=("programacao", "contexto-longo"),
                health_timeout_seconds=120,
            ),
            "laguna-xs-2.1-gpu": ModelSpec(
                model_id="laguna-xs-2.1-gpu", model_class="GPU",
                profile="laguna-programming-v1", unit="laguna-gpu.service",
                shared=False, exclusive_group="gpu-slot-1",
                endpoint="http://127.0.0.1:8082",
                capabilities=("programacao", "contexto-longo"),
                health_timeout_seconds=300,
            ),
            "ornith-35b-gpu": ModelSpec(
                model_id="ornith-35b-gpu", model_class="GPU",
                profile="gpu-triage-v1", unit="ornith.service",
                shared=False, exclusive_group="gpu-slot-1",
                endpoint="http://127.0.0.1:8092",
                capabilities=("programacao", "triagem"),
                health_timeout_seconds=300,
            ),
            "nemotron-3.5-30b-gpu": ModelSpec(
                model_id="nemotron-3.5-30b-gpu", model_class="GPU",
                profile="nemotron-ternary-v1", unit="nemotron.service",
                shared=False, exclusive_group="gpu-slot-1",
                endpoint="http://127.0.0.1:8083",
                capabilities=("leitura", "rag", "sumarizacao"),
                health_timeout_seconds=600,
            ),
        }

    def get(self, model_id):
        return self._models.get(model_id)

    def list(self):
        return list(self._models.values())

    def exclusive_models(self):
        return [m for m in self._models.values()
                if m.exclusive_group is not None]


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
            self._ensure_model_operations_table(db)
            db.execute(
                """INSERT INTO model_operations
                (operation_id, action, target_model_id, requested_status, status)
                VALUES (?, 'start', ?, 'READY', 'REQUESTED')""",
                (operation_id, model_id),
            )
            db.commit()
        return ModelOperation(operation_id=operation_id)

    def request_stop(self, model_id):
        model = self.registry.get(model_id)
        if model is None:
            raise ValueError(f"Modelo desconhecido: {model_id}")
        db = self._db()
        operation_id = secrets.token_hex(8)
        if db is not None:
            self._ensure_model_operations_table(db)
            db.execute(
                """INSERT INTO model_operations
                (operation_id, action, target_model_id, requested_status, status)
                VALUES (?, 'stop', ?, 'STOPPED', 'REQUESTED')""",
                (operation_id, model_id),
            )
            db.commit()
        return ModelOperation(operation_id=operation_id)

    def request_switch(self, from_model_id, to_model_id):
        to_model = self.registry.get(to_model_id)
        if to_model is None:
            raise ValueError(f"Modelo desconhecido: {to_model_id}")
        if to_model.exclusive_group is None:
            raise ValueError(
                f"Modelo {to_model_id} e residente/compartilhado; "
                "o switch aplica-se apenas a modelos exclusivos"
            )
        if from_model_id is not None:
            from_model = self.registry.get(from_model_id)
            if from_model is None:
                raise ValueError(f"Modelo desconhecido: {from_model_id}")
        db = self._db()
        operation_id = secrets.token_hex(8)
        if db is not None:
            self._ensure_model_operations_table(db)
            db.execute(
                """INSERT INTO model_operations
                (operation_id, action, target_model_id, previous_status,
                 requested_status, status)
                VALUES (?, 'switch', ?, NULL, 'READY', 'REQUESTED')""",
                (operation_id, to_model_id),
            )
            db.commit()
        return ModelOperation(operation_id=operation_id)

    def wait_for_health(self, model_id, timeout=None):
        """Aguarda o endpoint /health do modelo retornar HTTP 200.

        Retorna True se ficar saudável dentro do timeout, False caso
        contrário. Se timeout for None, usa o health_timeout_seconds do
        modelo.
        """
        import time as _time
        import urllib.error
        import urllib.request

        model = self.registry.get(model_id)
        if model is None:
            raise ValueError(f"Modelo desconhecido: {model_id}")
        if timeout is None:
            timeout = model.health_timeout_seconds
        url = model.endpoint.rstrip("/") + "/health"
        deadline = _time.monotonic() + timeout
        while _time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=5) as resp:
                    if resp.status == 200:
                        return True
            except (urllib.error.URLError, OSError, ValueError):
                pass
            _time.sleep(2)
        return False

    def update_confirmed_status(self, operation_id, status, error=None):
        """Grava confirmed_status (e status) na operação de modelo."""
        db = self._db()
        if db is None:
            return
        self._ensure_model_operations_table(db)
        db.execute(
            """UPDATE model_operations
            SET confirmed_status=?, status=?,
                updated_at=strftime('%Y-%m-%dT%H:%M:%S','now')
            WHERE operation_id=?""",
            (status, status, operation_id),
        )
        if error is not None:
            db.execute(
                """UPDATE model_operations
                SET error=?
                WHERE operation_id=?""",
                (error, operation_id),
            )
        db.commit()

    def _ensure_model_operations_table(self, db):
        db.execute(
            """CREATE TABLE IF NOT EXISTS model_operations (
            operation_id TEXT PRIMARY KEY,
            idempotency_key TEXT,
            requester TEXT NOT NULL DEFAULT 'system',
            session_id TEXT,
            task_id TEXT,
            attempt_id TEXT,
            action TEXT NOT NULL CHECK (
                action IN ('start', 'stop', 'switch', 'health',
                           'reserve', 'release')
            ),
            target_model_id TEXT NOT NULL,
            previous_status TEXT,
            requested_status TEXT,
            confirmed_status TEXT,
            authorization_used TEXT,
            status TEXT NOT NULL DEFAULT 'REQUESTED' CHECK (
                status IN ('REQUESTED', 'APPROVED', 'IN_PROGRESS',
                           'COMPLETED', 'FAILED', 'REJECTED', 'BUSY')
            ),
            error TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
        )"""
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS model_operations_target "
            "ON model_operations(target_model_id, status)"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS model_operations_requester "
            "ON model_operations(requester)"
        )

    def reserve_engine(self, model_id, requester="system"):
        model = self.registry.get(model_id)
        if model is None:
            raise ValueError(f"Modelo desconhecido: {model_id}")
        if model.exclusive_group is None:
            return None
        db = self._db()
        if db is None:
            return None
        reservation_id = secrets.token_hex(8)
        cuda_visible = _cuda_visible_for_model(model)
        db.execute(
            """CREATE TABLE IF NOT EXISTS model_reservations (
            reservation_id TEXT PRIMARY KEY,
            model_id TEXT NOT NULL,
            requester TEXT NOT NULL DEFAULT 'system',
            exclusive_group TEXT,
            reserved_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
            released_at TEXT,
            cuda_visible_devices TEXT,
            status TEXT NOT NULL DEFAULT 'active' CHECK (
                status IN ('active', 'released')
            )
        )"""
        )
        db.execute(
            """CREATE INDEX IF NOT EXISTS model_reservations_model
            ON model_reservations(model_id, status)"""
        )
        db.execute(
            """INSERT INTO model_reservations
            (reservation_id, model_id, requester, exclusive_group,
             cuda_visible_devices, status)
            VALUES (?, ?, ?, ?, ?, 'active')""",
            (reservation_id, model_id, requester, model.exclusive_group,
             cuda_visible),
        )
        db.commit()
        return reservation_id

    def release_engine(self, model_id):
        model = self.registry.get(model_id)
        if model is None:
            raise ValueError(f"Modelo desconhecido: {model_id}")
        db = self._db()
        if db is None:
            return
        db.execute(
            """CREATE TABLE IF NOT EXISTS model_reservations (
            reservation_id TEXT PRIMARY KEY,
            model_id TEXT NOT NULL,
            requester TEXT NOT NULL DEFAULT 'system',
            exclusive_group TEXT,
            reserved_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
            released_at TEXT,
            cuda_visible_devices TEXT,
            status TEXT NOT NULL DEFAULT 'active' CHECK (
                status IN ('active', 'released')
            )
        )"""
        )
        db.execute(
            """UPDATE model_reservations
            SET released_at=strftime('%Y-%m-%dT%H:%M:%S','now'),
                status='released'
            WHERE model_id=? AND status='active'""",
            (model_id,),
        )
        db.commit()

    def engine_reserved(self, model_id):
        db = self._db()
        if db is None:
            return False
        db.execute(
            """CREATE TABLE IF NOT EXISTS model_reservations (
            reservation_id TEXT PRIMARY KEY,
            model_id TEXT NOT NULL,
            requester TEXT NOT NULL DEFAULT 'system',
            exclusive_group TEXT,
            reserved_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
            released_at TEXT,
            cuda_visible_devices TEXT,
            status TEXT NOT NULL DEFAULT 'active' CHECK (
                status IN ('active', 'released')
            )
        )"""
        )
        row = db.execute(
            """SELECT 1 FROM model_reservations
            WHERE model_id=? AND status='active' LIMIT 1""",
            (model_id,),
        ).fetchone()
        return row is not None

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
    try:
        result = subprocess.run(
            ["systemctl", "is-active", unit],
            check=False, capture_output=True, text=True, timeout=3,
        )
        return result.stdout.strip() == "active"
    except (OSError, subprocess.SubprocessError):
        return False


def _cuda_visible_for_model(model):
    """Return the CUDA_VISIBLE_DEVICES value for a model.

    Resident/shared GPU models (27B + 4B) coexist on the GPU and share
    device 0. Exclusive big models (Laguna, Ornith) take the GPU alone.
    """
    if model.exclusive_group is None:
        return "0"
    return "0"


class ModelStatus:
    def __init__(self, service, health):
        self.service = service
        self.health = health


class ModelOperation:
    def __init__(self, operation_id):
        self.operation_id = operation_id
