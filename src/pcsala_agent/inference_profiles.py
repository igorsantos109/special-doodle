from pydantic import BaseModel, ConfigDict, field_validator


class ProfileConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    profile: str
    endpoint: str
    model: str
    timeout_seconds: int = 60
    max_response_bytes: int = 65536
    api_key_env: str = "DSH_LOCAL_API_KEY"

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, v):
        if not (v.startswith("http://127.0.0.1") or v.startswith("http://localhost")):
            raise ValueError("endpoint must be local")
        return v


PROFILES = {
    "cpu-triage-v1": ProfileConfig(
        profile="cpu-triage-v1",
        endpoint="http://127.0.0.1:8090",
        model="/home/igor/models/ternary-bonsai-2-9b-cpu/"
        "Ternary-Bonsai-2-9B-PQ2_0.gguf",
        timeout_seconds=60,
        max_response_bytes=65536,
    ),
    "gpu-triage-v1": ProfileConfig(
        profile="gpu-triage-v1",
        endpoint="http://127.0.0.1:8080",
        model="/home/igor/models/bonsai-2-27b/"
        "Ternary-Bonsai-2-27B-PQ2_0.gguf",
        timeout_seconds=60,
        max_response_bytes=65536,
    ),
    "laguna-programming-v1": ProfileConfig(
        profile="laguna-programming-v1",
        endpoint="http://127.0.0.1:8091",
        model="/home/igor/models/laguna-xs-2-1/"
        "Laguna-XS-2.1-APEX-I-Compact.gguf",
        timeout_seconds=300,
        max_response_bytes=131072,
    ),
}


def get_profile(name):
    if name not in PROFILES:
        raise ValueError(f"Perfil desconhecido: {name}")
    return PROFILES[name]
