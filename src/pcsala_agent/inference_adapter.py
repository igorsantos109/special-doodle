import json
import logging
import urllib.error
from http.client import HTTPException
from urllib.parse import urlparse

from .inference_contract import InferenceResponse

logger = logging.getLogger("pcsala_agent.inference_adapter")


class InferenceEndpointError(Exception):
    pass


class InferenceAdapter:
    def __init__(self, config=None):
        from .inference_contract import InferenceConfig
        self.config = config or InferenceConfig()

    def _validate_endpoint(self):
        parsed = urlparse(self.config.endpoint)
        if parsed.hostname not in ("127.0.0.1", "localhost"):
            raise InferenceEndpointError(f"endpoint não local: {self.config.endpoint}")
        if parsed.scheme != "http":
            raise InferenceEndpointError(f"schema não http: {self.config.endpoint}")
        if parsed.username is not None or parsed.password is not None:
            raise InferenceEndpointError("credenciais não permitidas no endpoint")

    def query(self, request, _urlopen=None):
        import urllib.request as _urlreq

        if _urlopen is None:
            _urlopen = _urlrequest
        self._validate_endpoint()
        if self.config.timeout_seconds <= 0 or self.config.max_response_bytes <= 0:
            logger.warning(
                "requisicao invalida: timeout=%s max_response_bytes=%s",
                self.config.timeout_seconds,
                self.config.max_response_bytes,
            )
            return InferenceResponse(request=request, status="INVALID_RESPONSE")
        url = self.config.endpoint.rstrip("/") + "/v1/chat/completions"
        logger.debug(
            "inferencia iniciada: endpoint=%s timeout=%s max_response_bytes=%s",
            self.config.endpoint,
            self.config.timeout_seconds,
            self.config.max_response_bytes,
        )
        messages = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.user_prompt})
        payload = {"model": self.config.model or request.profile, "messages": messages}
        req = _urlreq.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        resp = None
        try:
            resp = _urlopen(req, timeout=self.config.timeout_seconds)
            body = resp.read(self.config.max_response_bytes + 1)
        except urllib.error.HTTPError as exc:
            exc.close()
            logger.warning("inferencia HTTPError: codigo=%s", getattr(exc, "code", None))
            return InferenceResponse(request=request, status="UNAVAILABLE")
        except urllib.error.URLError as exc:
            status = "TIMEOUT" if isinstance(exc.reason, TimeoutError) else "UNAVAILABLE"
            logger.warning("inferencia URLError: status=%s motivo=%s", status, exc.reason)
            return InferenceResponse(request=request, status=status)
        except TimeoutError:
            logger.warning("inferencia TIMEOUT: timeout do urlopen")
            return InferenceResponse(request=request, status="TIMEOUT")
        except (OSError, HTTPException):
            logger.warning("inferencia indisponivel: OSError/HTTPException")
            return InferenceResponse(request=request, status="UNAVAILABLE")
        finally:
            if resp is not None:
                close = getattr(resp, "close", None)
                if close is not None:
                    close()
        if not isinstance(body, bytes) or len(body) > self.config.max_response_bytes:
            logger.warning(
                "inferencia truncada/corpo invalido: bytes=%s limite=%s",
                len(body) if isinstance(body, (bytes, bytearray)) else type(body).__name__,
                self.config.max_response_bytes,
            )
            return InferenceResponse(request=request, status="INVALID_RESPONSE")
        try:
            parsed = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            logger.warning("inferencia corpo nao eh JSON valido")
            return InferenceResponse(request=request, status="INVALID_RESPONSE")
        if not isinstance(parsed, dict):
            logger.warning("inferencia corpo JSON nao eh um objeto")
            return InferenceResponse(request=request, status="INVALID_RESPONSE")
        choices = parsed.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            logger.warning("inferencia choices ausentes ou malformados")
            return InferenceResponse(request=request, status="INVALID_RESPONSE")
        choice = choices[0]
        message = choice.get("message")
        if not isinstance(message, dict):
            logger.warning("inferencia message nao eh um objeto")
            return InferenceResponse(request=request, status="INVALID_RESPONSE")
        content = message.get("content")
        model = parsed.get("model", "")
        finish_reason = choice.get("finish_reason")
        if (not isinstance(content, str)
                or not isinstance(model, str)
                or finish_reason not in (None, "stop")
                or message.get("tool_calls")):
            logger.warning(
                "inferencia resposta invalida: finish_reason=%s content_tipo=%s tool_calls=%s",
                finish_reason, type(content).__name__, bool(message.get("tool_calls")),
            )
            return InferenceResponse(request=request, status="INVALID_RESPONSE")
        logger.info(
            "inferencia concluida: status=SUCCESS model=%s output_bytes=%s",
            model, len(body),
        )
        return InferenceResponse(
            request=request, status="SUCCESS", text=content,
            model=model, output_bytes=len(body),
        )


def _urlrequest(request, *args, **kwargs):
    import urllib.request
    return urllib.request.urlopen(request, *args, **kwargs)
