import os

from pydantic import BaseModel, ConfigDict, field_validator


class ProfileConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    profile: str
    endpoint: str
    model: str
    timeout_seconds: int = 60
    max_response_bytes: int = 65536
    api_key_env: str = "DSH_LOCAL_API_KEY"
    endpoint_env: str = ""
    model_env: str = ""

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, v):
        if not (v.startswith("http://127.0.0.1") or v.startswith("http://localhost")):
            raise ValueError("endpoint must be local")
        return v

    def resolved_endpoint(self) -> str:
        """Retorna endpoint da env var se definida, senão o default."""
        if self.endpoint_env:
            return os.environ.get(self.endpoint_env, self.endpoint)
        return self.endpoint

    def resolved_model(self) -> str:
        """Retorna modelo da env var se definida, senão o default."""
        if self.model_env:
            return os.environ.get(self.model_env, self.model)
        return self.model


PROFILES = {
    "cpu-triage-v1": ProfileConfig(
        profile="cpu-triage-v1",
        endpoint="http://127.0.0.1:8090",
        model="/home/igor/models/ternary-bonsai-2-9b-cpu/"
        "Ternary-Bonsai-2-9B-PQ2_0.gguf",
        timeout_seconds=60,
        max_response_bytes=65536,
        endpoint_env="PCSALA_ENDPOINT_CPU_TRIAGE_V1",
        model_env="PCSALA_MODEL_CPU_TRIAGE_V1",
    ),
    "gpu-triage-v1": ProfileConfig(
        profile="gpu-triage-v1",
        endpoint="http://127.0.0.1:8080",
        model="/home/igor/models/bonsai-2-27b/"
        "Ternary-Bonsai-2-27B-PQ2_0.gguf",
        timeout_seconds=60,
        max_response_bytes=65536,
        endpoint_env="PCSALA_ENDPOINT_GPU_TRIAGE_V1",
        model_env="PCSALA_MODEL_GPU_TRIAGE_V1",
    ),
    "laguna-programming-v1": ProfileConfig(
        profile="laguna-programming-v1",
        endpoint="http://127.0.0.1:8091",
        model="/home/igor/models/laguna-xs-2-1/"
        "Laguna-XS-2.1-APEX-I-Compact.gguf",
        timeout_seconds=300,
        max_response_bytes=131072,
        endpoint_env="PCSALA_ENDPOINT_LAGUNA_PROGRAMMING_V1",
        model_env="PCSALA_MODEL_LAGUNA_PROGRAMMING_V1",
    ),
    "nemotron-ternary-v1": ProfileConfig(
        profile="nemotron-ternary-v1",
        endpoint="http://127.0.0.1:8083",
        model="/home/igor/models/ternary-nemotron-3.5-30b-a3b/"
        "Ternary-Nemotron-3.5-Lightning-30B-A3B-GGUF.gguf",
        timeout_seconds=300,
        max_response_bytes=65536,
        endpoint_env="PCSALA_ENDPOINT_NEMOTRON_TERNARY_V1",
        model_env="PCSALA_MODEL_NEMOTRON_TERNARY_V1",
    ),
}


def get_profile(name):
    if name not in PROFILES:
        raise ValueError(f"Perfil desconhecido: {name}")
    return PROFILES[name]
