import json

PRIMARY_CONTEXT = 64000
PRIMARY_BUDGET = 55000
PRIMARY_INPUT_BUDGET = 50000
AUX_CONTEXT = 32768
AUX_BUDGET = 28000
AUX_INPUT_BUDGET = 65536

FACT_KEYS = [
    "OBJECTIVO", "DECISOES", "AUTORIZACOES", "PROIBICOES",
    "CAMINHOS", "IDENTIFICADORES", "RESULTADOS", "ERROS", "PROXIMA ACCAO",
]

FACTS_TO_PRESERVE_TEMPLATE = (
    "OBJECTIVO: {objective}\n"
    "DECISOES: {decisions}\n"
    "AUTORIZACOES: {authorizations}\n"
    "PROIBICOES: {prohibitions}\n"
    "CAMINHOS: {paths}\n"
    "IDENTIFICADORES: {identifiers}\n"
    "RESULTADOS: {results}\n"
    "ERROS: {errors}\n"
    "PROXIMA ACCAO: {next_action}\n"
)

COMPRESSION_PROMPT = (
    "PRESERVAR as seguintes categorias de informacao:\n"
    "Objectivo, Decisoes, Proibicoes, Caminhos, Erros e Proxima accao.\n"
)

TOKENIZE_PATH = "/tokenize"


class ContextOverflow(Exception):
    pass


class CompressionError(Exception):
    pass


class TokenizerError(Exception):
    pass


class BudgetCheck:
    __slots__ = ("deficit", "over_budget", "ratio", "tokens")

    def __init__(self, over_budget, deficit, ratio, tokens):
        self.over_budget = over_budget
        self.deficit = deficit
        self.ratio = ratio
        self.tokens = tokens

    def __eq__(self, other):
        if not isinstance(other, BudgetCheck):
            return NotImplemented
        return (
            self.over_budget == other.over_budget
            and self.deficit == other.deficit
            and self.ratio == other.ratio
            and self.tokens == other.tokens
        )


def _default_urlopen(request, *args, **kwargs):
    import urllib.request
    return urllib.request.urlopen(request)


def count_tokens(text, _urlopen=_default_urlopen):
    import urllib.request as urlreq
    endpoint = "http://127.0.0.1:8090"
    req = urlreq.Request(
        endpoint + TOKENIZE_PATH,
        data=json.dumps({"content": text}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        resp = _urlopen(req)
        body = resp.read()
    except Exception as exc:
        if getattr(exc, "response", None) is None and "HTTPError" in type(exc).__name__:
            pass
        raise TokenizerError(str(exc))
    parsed = json.loads(body)
    tokens = parsed.get("tokens", [])
    if not isinstance(tokens, list):
        raise TokenizerError("tokens invalidos")
    return len(tokens)


def check_budget(text, budget, _urlopen=_default_urlopen):
    tokens = count_tokens(text, _urlopen=_urlopen)
    over = tokens > budget
    deficit = max(0, tokens - budget) if over else 0
    ratio = tokens / budget if budget > 0 else 0
    return BudgetCheck(over_budget=over, deficit=deficit, ratio=ratio, tokens=tokens)


def _clean_compression_output(raw):
    if not raw or raw.strip() == "":
        return ""
    lines = raw.strip().splitlines()
    kept = []
    fact_set = tuple(k.upper() for k in FACT_KEYS)
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        lowered = stripped.split(":", 1)[0].strip().upper()
        if any(lowered.startswith(k) for k in fact_set):
            kept.append(stripped)
        else:
            continue
    return "\n".join(kept) + ("\n" if kept else "")
