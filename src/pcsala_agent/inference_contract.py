from pydantic import BaseModel, ConfigDict, field_validator


class InferenceConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    endpoint: str = "http://127.0.0.1:8090"
    model: str = ""
    timeout_seconds: int = 60
    max_response_bytes: int = 65536
    api_key_env: str = "DSH_LOCAL_API_KEY"

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, v):
        # A aplicacao da regra de endpoint local/HTTP ocorre no adaptador,
        # no momento da consulta (InferenceAdapter._validate_endpoint).
        return v


class InferenceRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    project_id: str
    session_id: str
    task_id: str
    attempt_id: str
    profile: str
    user_prompt: str
    system_prompt: str = ""
    timeout_seconds: int = 60

    @field_validator("profile")
    @classmethod
    def validate_profile(cls, v):
        from .inference_profiles import get_profile
        get_profile(v)
        return v


class InferenceResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    request: InferenceRequest
    status: str
    text: str = ""
    model: str = ""
    output_bytes: int = 0
