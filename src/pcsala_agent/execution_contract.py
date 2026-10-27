import dataclasses

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

VALID_PROFILES = ("diagnostic-v1", "diagnostic-v2")


class StorageLimits(BaseModel):
    model_config = ConfigDict(frozen=True)
    workspace_bytes: int = 16777216
    workspace_inodes: int = 4096
    tmp_bytes: int = 4194304
    tmp_inodes: int = 1024

    @model_validator(mode="before")
    @classmethod
    def reject_overrides(cls, data):
        if not isinstance(data, dict):
            return data
        for k in ("workspace_bytes", "workspace_inodes", "tmp_bytes", "tmp_inodes"):
            if k in data:
                raise ValueError(f"{k} é fixo")
        return data


class ExecutionProfile(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str = "diagnostic-v1"
    argv: tuple = ()
    storage: StorageLimits | None = None
    workspace_bytes_max: int = 16777216
    memory_bytes: int = 268435456
    swap_bytes: int = 0
    tasks_max: int = 32
    cpu_percent: int = 50
    runtime_seconds: int = 15
    network: str = "disabled"

    @model_validator(mode="after")
    def check_storage_consistency(self):
        if self.name == "diagnostic-v2":
            if self.storage is None:
                raise ValueError("diagnostic-v2 exige storage")
            if self.workspace_bytes_max != self.storage.workspace_bytes:
                raise ValueError("workspace_bytes_max incompatível")
        elif self.storage is not None:
            raise ValueError("perfil legado não aceita storage")
        return self


def resolve_profile(request):
    if request.profile == "diagnostic-v1":
        return ExecutionProfile(
            name="diagnostic-v1",
            argv=("/usr/bin/python3", "-I", "-u", "-c", "print('PCSALA_DIAGNOSTIC_V1')"),
            memory_bytes=256 * 1024 * 1024,
            swap_bytes=0,
            tasks_max=32,
            cpu_percent=50,
            runtime_seconds=15,
            network="disabled",
        )
    if request.profile == "diagnostic-v2":
        storage = StorageLimits()
        return ExecutionProfile(
            name="diagnostic-v2",
            argv=("/usr/bin/python3", "-I", "-u", "-c", "print('PCSALA_DIAGNOSTIC_V2')"),
            storage=storage,
            workspace_bytes_max=storage.workspace_bytes,
            memory_bytes=256 * 1024 * 1024,
            swap_bytes=0,
            tasks_max=32,
            cpu_percent=50,
            runtime_seconds=15,
            network="disabled",
        )
    raise ValueError(f"Perfil desconhecido: {request.profile}")


@dataclasses.dataclass(frozen=True)
class StorageMount:
    source: str
    target: str
    bytes_max: int
    inodes_max: int
    filesystem: str
    options: tuple


class ExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project_id: str
    session_id: str
    task_id: str
    attempt_id: str
    profile: str

    @field_validator("project_id", "session_id", "task_id", "attempt_id")
    @classmethod
    def validate_scope(cls, v):
        if not v or len(v) > 64:
            raise ValueError("identificador invalido")
        bad = set("../ ;\n\\á")
        if any(c in v for c in bad):
            raise ValueError("identificador invalido")
        if "/" in v or "\\" in v:
            raise ValueError("identificador invalido")
        return v

    @field_validator("profile")
    @classmethod
    def validate_profile(cls, v):
        if v not in VALID_PROFILES:
            raise ValueError("perfil desconhecido")
        return v


_VALID_RESULT_STATUSES = (
    "SUCCESS", "COMMAND_ERROR", "TIMEOUT", "OOM",
    "OUTPUT_LIMIT", "STORAGE_LIMIT", "INFRA_ERROR",
)


class ExecutionResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    request: ExecutionRequest
    status: str
    exit_code: int | None = None
    output_bytes: int = 0

    @field_validator("status")
    @classmethod
    def validate_status(cls, v):
        if v not in _VALID_RESULT_STATUSES:
            raise ValueError("status invalido")
        return v

    @model_validator(mode="after")
    def check_consistency(self):
        if self.status == "SUCCESS" and self.exit_code != 0:
            raise ValueError("SUCCESS exige exit_code 0")
        if self.status == "COMMAND_ERROR" and self.exit_code == 0:
            raise ValueError("COMMAND_ERROR nao aceita exit_code 0")
        if self.status == "COMMAND_ERROR" and self.exit_code is None:
            raise ValueError("COMMAND_ERROR exige exit_code")
        if self.status not in ("SUCCESS", "COMMAND_ERROR"):
            if self.exit_code is not None:
                raise ValueError("status de controle exige exit_code None")
        return self

    @field_validator("output_bytes", mode="before")
    @classmethod
    def validate_output(cls, v):
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError("output_bytes fora de faixa")
        if v < 0 or v > 65536:
            raise ValueError("output_bytes fora de faixa")
        return v
