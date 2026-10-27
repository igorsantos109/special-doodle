import os

from .inference_contract import InferenceConfig


def _env(name, default):
    """Override por ambiente apenas quando definido; default intacto."""
    return os.environ.get(name, default)


PROFILES = {
    "cpu-triage-v1": InferenceConfig(
        endpoint=_env("PCSALA_ENDPOINT_CPU_TRIAGE_V1", "http://127.0.0.1:8090"),
        model=_env(
            "PCSALA_MODEL_CPU_TRIAGE_V1",
            "/home/igor/models/ternary-bonsai-2-9b-cpu/"
            "Ternary-Bonsai-2-9B-PQ2_0.gguf",
        ),
        timeout_seconds=300,
        max_response_bytes=65536,
        api_key_env="DSH_LOCAL_API_KEY",
    ),
    "gpu-triage-v1": InferenceConfig(
        endpoint=_env("PCSALA_ENDPOINT_GPU_TRIAGE_V1", "http://127.0.0.1:8080"),
        model=_env(
            "PCSALA_MODEL_GPU_TRIAGE_V1",
            "/home/igor/models/bonsai-2-27b/"
            "Ternary-Bonsai-2-27B-PQ2_0.gguf",
        ),
        timeout_seconds=300,
        max_response_bytes=65536,
        api_key_env="DSH_LOCAL_API_KEY",
    ),
    "laguna-programming-v1": InferenceConfig(
        endpoint=_env(
            "PCSALA_ENDPOINT_LAGUNA_PROGRAMMING_V1", "http://127.0.0.1:8091"
        ),
        model=_env(
            "PCSALA_MODEL_LAGUNA_PROGRAMMING_V1",
            "/home/igor/models/laguna-xs-2-1/"
            "Laguna-XS-2.1-APEX-I-Compact.gguf",
        ),
        timeout_seconds=600,
        max_response_bytes=131072,
        api_key_env="DSH_LOCAL_API_KEY",
    ),
}


def get_profile(profile_name: str) -> InferenceConfig:
    if profile_name not in PROFILES:
        raise ValueError(
            f"Perfil desconhecido: {profile_name}. "
            f"Disponiveis: {list(PROFILES.keys())}"
        )
    return PROFILES[profile_name]