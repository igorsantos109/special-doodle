from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from .inference_contract import (
    InferenceConfig,
    InferenceRequest,
    InferenceResponse,
)

logger = logging.getLogger(__name__)


class InferenceEndpointError(ValueError):
    pass


class InferenceTransportError(RuntimeError):
    pass


def _build_chat_completion_body(
    request: InferenceRequest,
    config: InferenceConfig,
) -> bytes:
    messages = []
    if request.system_prompt:
        messages.append({"role": "system", "content": request.system_prompt})
    messages.append({"role": "user", "content": request.user_prompt})

    body = {
        "model": config.model,
        "messages": messages,
        "stream": False,
        "max_tokens": 16384,
    }
    return json.dumps(body, ensure_ascii=False).encode("utf-8")


def _validate_endpoint(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    host = parsed.hostname or ""
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise InferenceEndpointError(
            f"Endpoint rejeitado: {endpoint}. Somente loopback permitido."
        )
    if parsed.scheme not in ("http",):
        raise InferenceEndpointError(
            f"Esquema rejeitado: {parsed.scheme}. Somente http."
        )
    return endpoint


class InferenceAdapter:
    def __init__(
        self,
        config: InferenceConfig,
    ):
        self.config = config

    def query(
        self,
        request: InferenceRequest,
        *,
        _urlopen: Callable[..., Any] | None = None,
    ) -> InferenceResponse:
        _validate_endpoint(self.config.endpoint)
        url = self.config.endpoint.rstrip("/") + "/v1/chat/completions"
        data = _build_chat_completion_body(request, self.config)

        opener = _urlopen if _urlopen is not None else urllib.request.urlopen
        headers = {"Content-Type": "application/json"}
        if self.config.api_key_env:
            key = os.environ.get(self.config.api_key_env, "")
            if key:
                headers["Authorization"] = "Bearer " + key
        req = urllib.request.Request(
            url,
            data=data,
            headers=headers,
            method="POST",
        )

        try:
            response = opener(
                req, timeout=self.config.timeout_seconds
            )
        except urllib.error.HTTPError as exc:
            status = exc.code
            try:
                detail = exc.read(self.config.max_response_bytes)
            except Exception:
                detail = b""
            logger.warning(
                "Inferencia HTTP %s para %s", status, request.attempt_id
            )
            return InferenceResponse(
                request=request,
                status="UNAVAILABLE",
                output_bytes=len(detail),
            )
        except urllib.error.URLError as exc:
            logger.warning(
                "Inferencia indisponivel para %s: %s",
                request.attempt_id,
                exc.reason,
            )
            return InferenceResponse(
                request=request,
                status="UNAVAILABLE",
                output_bytes=0,
            )

        except TimeoutError as exc:
            logger.warning(
                "Inferencia timeout para %s", request.attempt_id
            )
            return InferenceResponse(
                request=request,
                status="TIMEOUT",
                output_bytes=0,
            )

        try:
            raw = response.read(self.config.max_response_bytes + 1)
        except Exception as exc:
            logger.error("Erro na leitura da resposta: %s", exc)
            return InferenceResponse(
                request=request, status="INVALID_RESPONSE"
            )

        if len(raw) > self.config.max_response_bytes:
            logger.warning("Resposta excede %s bytes", self.config.max_response_bytes)
            return InferenceResponse(
                request=request,
                status="INVALID_RESPONSE",
                output_bytes=self.config.max_response_bytes + 1,
            )

        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning("JSON invalido na resposta: %s", exc)
            return InferenceResponse(
                request=request,
                status="INVALID_RESPONSE",
                output_bytes=len(raw),
            )

        try:
            text = payload["choices"][0]["message"]["content"]
            model = payload.get("model", self.config.model)
        except (KeyError, IndexError, TypeError) as exc:
            logger.warning("Estrutura inesperada na resposta: %s", exc)
            return InferenceResponse(
                request=request,
                status="INVALID_RESPONSE",
                output_bytes=len(raw),
            )

        if not isinstance(text, str):
            logger.warning("Conteudo da mensagem nao e texto")
            return InferenceResponse(
                request=request,
                status="INVALID_RESPONSE",
                output_bytes=len(raw),
            )

        # Nao executar tool_calls ou comandos contidos na resposta
        if "tool_calls" in payload or any(
            choice.get("finish_reason") == "tool_calls"
            for choice in payload.get("choices", [])
        ):
            logger.warning("Resposta contem tool_calls — ignorada")
            return InferenceResponse(
                request=request,
                status="INVALID_RESPONSE",
                output_bytes=len(raw),
            )

        return InferenceResponse(
            request=request,
            status="SUCCESS",
            text=text,
            model=model,
            output_bytes=len(raw),
        )