import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

class ContractModel(BaseModel):
    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        frozen=True,
        validate_default=True,
        revalidate_instances="always",
    )

class ExecutionRequest(ContractModel):
    version: Literal["1"] = "1"
    project_id: str
    session_id: str
    task_id: str
    attempt_id: str
    profile: Literal["diagnostic-v1", "diagnostic-v2"]

    @field_validator("project_id", "session_id", "task_id", "attempt_id")
    @classmethod
    def identifier(cls, value):
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value) is None:
            raise ValueError("Identificador ASCII invalido; tamanho de 1 a 64")
        return value

class StorageLimits(ContractModel):
    strategy: Literal["private-tmpfs"] = "private-tmpfs"
    workspace_bytes: Literal[16777216] = 16777216
    workspace_inodes: Literal[4096] = 4096
    tmp_bytes: Literal[4194304] = 4194304
    tmp_inodes: Literal[1024] = 1024
    volatile: Literal[True] = True

class ExecutionProfile(ContractModel):
    name: Literal["diagnostic-v1", "diagnostic-v2"] = "diagnostic-v1"
    argv: tuple[str, ...] = (
        "/usr/bin/python3", "-I", "-u", "-c",
        "print('PCSALA_DIAGNOSTIC_V1')",
    )
    memory_bytes: int = Field(default=268435456, gt=0)
    swap_bytes: Literal[0] = 0
    tasks_max: int = Field(default=32, gt=0)
    cpu_percent: int = Field(default=50, gt=0, le=100)
    runtime_seconds: int = Field(default=15, gt=0)
    output_bytes_max: int = Field(default=65536, gt=0)
    workspace_bytes_max: int = Field(default=16777216, gt=0)
    network: Literal["disabled"] = "disabled"
    storage: StorageLimits | None = None

    @model_validator(mode="after")
    def coherent_storage(self):
        if self.name == "diagnostic-v1":
            if self.storage is not None:
                raise ValueError("Perfil legado nao recebe armazenamento v2")
        else:
            if self.storage is None:
                raise ValueError("diagnostic-v2 exige limites de armazenamento")
            if self.workspace_bytes_max != self.storage.workspace_bytes:
                raise ValueError("Limites de workspace inconsistentes")
        return self

def resolve_profile(request: ExecutionRequest) -> ExecutionProfile:
    """Selecao local fixa. Nao executa comandos nem acessa o filesystem."""
    checked = ExecutionRequest.model_validate(request)
    if checked.profile == "diagnostic-v1":
        return ExecutionProfile()
    if checked.profile == "diagnostic-v2":
        return ExecutionProfile(
            name="diagnostic-v2",
            argv=(
                "/usr/bin/python3", "-I", "-u", "-c",
                "print('PCSALA_DIAGNOSTIC_V2')",
            ),
            storage=StorageLimits(),
        )
    raise ValueError("Perfil nao cadastrado")

class ExecutionResult(ContractModel):
    request: ExecutionRequest
    status: Literal[
        "SUCCESS", "COMMAND_ERROR", "TIMEOUT", "OOM",
        "OUTPUT_LIMIT", "STORAGE_LIMIT", "INFRA_ERROR",
    ]
    exit_code: int | None = Field(default=None, ge=0, le=255)
    output_bytes: int = Field(ge=0, le=65536)

    @model_validator(mode="after")
    def coherent_exit(self):
        if self.status == "SUCCESS" and self.exit_code != 0:
            raise ValueError("Sucesso exige exit_code zero")
        if self.status == "COMMAND_ERROR" and (
            self.exit_code is None or self.exit_code == 0
        ):
            raise ValueError("Erro de comando exige codigo nao zero")
        if self.status not in ("SUCCESS", "COMMAND_ERROR"):
            if self.exit_code is not None:
                raise ValueError(
                    "Falhas de controle usam status; exit_code deve ser null"
                )
        return self
