import json
import urllib.error
from urllib.parse import urlparse

from .inference_contract import InferenceResponse


class InferenceEndpointError(Exception):
    pass


class InferenceAdapter:
    def __init__(self, config=None):
        from .inference_contract import InferenceConfig
        self.config = config or InferenceConfig()

    def _validate_endpoint(self):
        endpoint = self.config.endpoint
        parsed = urlparse(endpoint)
        host = parsed.hostname or ""
        if not (host == "127.0.0.1" or host == "localhost"):
            raise InferenceEndpointError(f"endpoint não local: {endpoint}")
        if parsed.scheme != "http":
            raise InferenceEndpointError(f"schema não http: {endpoint}")

    def query(self, request, _urlopen=None):
        import urllib.request as _urlreq
        if _urlopen is None:
            _urlopen = _urlrequest
        self._validate_endpoint()
        url = self.config.endpoint.rstrip("/") + "/v1/chat/completions"
        messages = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.user_prompt})
        payload = {"model": self.config.model or request.profile, "messages": messages}
        data = json.dumps(payload).encode("utf-8")
        req = _urlreq.Request(url, data=data, headers={"Content-Type": "application/json"},
                              method="POST")
        try:
            resp = _urlopen(req)
        except urllib.error.HTTPError:
            return InferenceResponse(
                request=request, status="UNAVAILABLE", text=""
            )
        except urllib.error.URLError:
            return InferenceResponse(
                request=request, status="UNAVAILABLE", text=""
            )
        except TimeoutError:
            return InferenceResponse(
                request=request, status="TIMEOUT", text=""
            )
        body = resp.read()
        if len(body) > self.config.max_response_bytes:
            return InferenceResponse(
                request=request, status="INVALID_RESPONSE", text=""
            )
        try:
            parsed = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            return InferenceResponse(
                request=request, status="INVALID_RESPONSE", text=""
            )
        if not isinstance(parsed, dict) or "choices" not in parsed:
            return InferenceResponse(
                request=request, status="INVALID_RESPONSE", text=""
            )
        choice = parsed["choices"][0]
        message = choice.get("message", {})
        content = message.get("content")
        finish = choice.get("finish_reason")
        if not isinstance(content, str):
            return InferenceResponse(
                request=request, status="INVALID_RESPONSE", text=""
            )
        if finish == "tool_calls":
            return InferenceResponse(
                request=request, status="INVALID_RESPONSE", text=""
            )
        return InferenceResponse(
            request=request,
            status="SUCCESS",
            text=content,
            model=parsed.get("model", ""),
            output_bytes=len(body),
        )


def _urlrequest(request, *args, **kwargs):
    import urllib.request
    return urllib.request.urlopen(request)
