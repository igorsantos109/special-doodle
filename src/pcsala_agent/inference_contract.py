from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        frozen=True,
        validate_default=True,
        revalidate_instances="always",
    )


class InferenceRequest(ContractModel):
    version: Literal["1"] = "1"
    project_id: str
    session_id: str
    task_id: str
    attempt_id: str
    profile: Literal["cpu-triage-v1", "gpu-triage-v1", "laguna-programming-v1"]
    system_prompt: str = ""
    user_prompt: str = ""

    @field_validator("project_id", "session_id", "task_id", "attempt_id")
    @classmethod
    def identifier(cls, value):
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value) is None:
            raise ValueError("Identificador ASCII invalido; tamanho de 1 a 64")
        return value


InferenceStatus = Literal[
    "SUCCESS",
    "UNAVAILABLE",
    "TIMEOUT",
    "INVALID_RESPONSE",
]


class InferenceResponse(ContractModel):
    version: Literal["1"] = "1"
    request: InferenceRequest
    status: InferenceStatus
    text: str = ""
    model: str = ""
    output_bytes: int = Field(ge=0, le=16777216)


class InferenceConfig:
    endpoint: str
    model: str
    timeout_seconds: int
    max_response_bytes: int
    api_key_env: str

    def __init__(
        self,
        *,
        endpoint: str = "http://127.0.0.1:8080",
        model: str = "",
        timeout_seconds: int = 60,
        max_response_bytes: int = 65536,
        api_key_env: str = "",
    ):
        self.endpoint = endpoint
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes
        self.api_key_env = api_key_env