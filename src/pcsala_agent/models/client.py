"""Cliente HTTP para o proxy llama-swap (camada de execução, B2/B3).

Envia o id do modelo no campo "model" da API compatível com OpenAI.
Sempre injetável em testes (servidor HTTP falso).
Desabilita proxies por padrão para evitar 502 em ambientes com proxy
de rede interceptando localhost.
"""
import json
import urllib.error
import urllib.request


def _default_urlopen(req, timeout=None):
    """urlopen sem proxy (evita 502 em ambientes com proxy de rede)."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(req, timeout=timeout)


class LlamaSwapClient:
    def __init__(self, base_url: str, timeout_seconds: int = 60,
                 _urlopen=None):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._urlopen = _urlopen or _default_urlopen

    def load_model(self, model_id: str, max_tokens: int = 1):
        """Pedido mínimo para carregar/ativar o modelo no llama-swap.

        Retorna (ok, error). ok=True quando o servidor responde com sucesso.
        """
        url = f"{self.base_url}/v1/chat/completions"
        payload = json.dumps({
            "model": model_id,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": max_tokens,
        }).encode("utf-8")
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._urlopen(req, timeout=self.timeout_seconds) as resp:
                resp.read()
                return True, None
        except urllib.error.HTTPError as exc:
            return False, f"HTTP {exc.code}"
        except urllib.error.URLError as exc:
            return False, f"URL {exc.reason}"
        except OSError as exc:
            return False, f"OS {exc}"

    def unload_model(self, model_id: str):
        """Endpoint de descarga do modelo (se exposto pelo llama-swap).

        Retorna (ok, error). Falhas de rede não são críticas para o rollback.
        """
        url = f"{self.base_url}/api/models/unload/{model_id}"
        req = urllib.request.Request(url, method="POST")
        try:
            with self._urlopen(req, timeout=self.timeout_seconds) as resp:
                resp.read()
                return True, None
        except urllib.error.HTTPError as exc:
            return False, f"HTTP {exc.code}"
        except (urllib.error.URLError, OSError) as exc:
            return False, str(exc)

    def health(self) -> bool:
        """Verifica se o proxy llama-swap está disponível."""
        url = f"{self.base_url}/v1/models"
        try:
            with self._urlopen(url, timeout=5) as resp:
                return resp.status == 200
        except (urllib.error.URLError, OSError, ValueError):
            return False
