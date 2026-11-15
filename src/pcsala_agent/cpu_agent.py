"""Camada CPU agentica — validador de tool calls, fallback e compactacao.

O modelo GPU (gpu-slot-1) gera o plano e a intencao de tool call; antes de
qualquer despacho a intencao e avaliada por um modelo CPU pequeno e rapido
(Qwen3-1.7B em 8103). Se esse validar e rejeitar (baixa confianca, ferramenta
inexistente, schema malformado) ou estiver em baixo, a mesma intencao e
reavaliada pelo fallback ultrarrapido (LFM2.5-1.2B em 8104). Só e considerado
aprovado o que sair de uma destas duas avaliacoes com veredito positivo.

A compactacao de contexto usa o Qwen2.5-1.5B (8105) como job em lote: o
servico e arrancado so quando ha trabalho e parado no fim (nao e residente).
Cada compactacao fica no audit trail da sessao (`audit_events`,
`CONTEXT_COMPACTED`), tal como cada avaliacao de tool call
(`TOOL_CALL_VALIDATED`).

As rotas (endpoints, unidades, limiares) sao declaradas no perfil
`cpu-agent-v1` em `inference_profiles.PROFILES`; perfis sem essas campos
deixam a camada desactivada (comportamento legado intacto).
"""

import hashlib
import json
import secrets
import subprocess
import urllib.error
import urllib.request as urlrequest
from datetime import UTC, datetime

from .context_budget import COMPRESSION_PROMPT, FACT_KEYS, _clean_compression_output
from .inference_profiles import get_profile

DEFAULT_CONFIDENCE_FLOOR = 0.6
DEFAULT_COMPACT_THRESHOLD = 16384
RECENT_TAIL_TOKENS = 2048
VALIDATOR_TIMEOUT = 30
COMPACTOR_TIMEOUT = 180
COMPACTOR_HEALTH_WAIT = 60
# Compactaçao em blocos: a cabeca e dividida por TOKENS (nunca por caracteres,
# que era o que descartava ~87 % do texto em silêncio) e todos os blocos tem de
# produzir factos reconheciveis, senao a compactaçao e recusada.
COMPACT_CHUNK_TOKENS = 3500
COMPACT_MAX_CHUNKS = 8
COMPACT_SUMMARY_TOKENS = 384
COMPACT_CHUNK_CHARS = 24000

VERDICT_APPROVED = "aprovada"
VERDICT_REJECTED = "rejeitada"
VERDICT_UNAVAILABLE = "indisponivel"


def _now():
    return datetime.now(UTC).isoformat(timespec="seconds")


def _default_urlopen(request, *args, **kwargs):
    # Repassa timeout e afins: sem isto o VALIDATOR_TIMEOUT/COMPACTOR_TIMEOUT
    # nunca chegavam ao socket e um servidor pendurado bloqueava o worker.
    return urlrequest.urlopen(request, *args, **kwargs)


def routing_for(profile_name):
    """Devolve o ProfileConfig do perfil, ou None se o perfil nao declara rotas CPU."""
    try:
        cfg = get_profile(profile_name)
    except ValueError:
        return None
    return cfg if getattr(cfg, "validator_endpoint", "") else None


def _post(endpoint, payload, timeout, _urlopen):
    if _urlopen is None:
        _urlopen = _default_urlopen
    url = endpoint.rstrip("/") + "/v1/chat/completions"
    req = urlrequest.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        resp = _urlopen(req, timeout=timeout)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return None
    try:
        body = resp.read()
    except (OSError, ValueError):
        return None
    try:
        parsed = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    choices = parsed.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    message = first.get("message")
    if message is None:
        message = first.get("delta") or {}
    if not isinstance(message, dict):
        return None
    return {
        "content": message.get("content") or "",
        "model": parsed.get("model", ""),
        "usage": parsed.get("usage") or {},
    }


_SYSTEM_RULE = (
    "Voce e o PORTAO de seguranca de um agente: decide se uma chamada de "
    "ferramenta pode ser despachada. Responda APENAS com um objecto JSON, sem "
    "prosa e sem cercas de codigo: "
    '{"accept": <true|false>, "confidence": <0 a 1>, "reason": "<frase curta>"}. '
    "Aceite apenas quando TUDO se verifica: (1) a ferramenta esta no catalogo; "
    "(2) os argumentos bateem com o schema; (3) a ACCAO E PEDIDA ou claramente "
    "implicada pela pergunta do utilizador — se a pergunta e sobre outra coisa "
    "(resumir, explicar, traduzir, escrever) e a chamada vai ler/elistar/apagar "
    "ficheiros, a resposta e accept=false; (4) nada de accao destrutiva, "
    "escrita fora do projecto, caminhos de sistema (/etc, /root, /usr, /), "
    "credenciais ou pedidos externos. Na duvida: accept=false.\n"
    'Exemplos — pergunta "lista os ficheiros em src" + listar_ficheiros{"src"} '
    '=> {"accept": true, "confidence": 0.95, "reason": "accao pedida e no schema"}; '
    'pergunta "resuma o changelog" + listar_ficheiros{"/etc"} => '
    '{"accept": false, "confidence": 0.9, "reason": "accao nao pedida e fora do projecto"}.\n'
    "Nao pense em voz alta: so o JSON.\n"
)


def _verdict_shape(text):
    """Extrai {accept, confidence, reason} da resposta, tolerando cercas de codigo."""
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        obj = json.loads(cleaned[start:end + 1])
    except ValueError:
        return None
    if not isinstance(obj, dict) or "accept" not in obj:
        return None
    aceita = obj.get("accept")
    if isinstance(aceita, str):
        # Tolerar "true"/"false" escritos, mas NUNCA tratar "false"/"0"/"no"
        # como verdade (bool("false") e True — fail-open).
        baixa = aceita.strip().lower()
        if baixa in ("true", "sim", "yes", "1"):
            aceita = True
        elif baixa in ("false", "nao", "no", "0"):
            aceita = False
        else:
            return None
    elif isinstance(aceita, (int, float)) and aceita in (0, 1):
        aceita = bool(aceita)
    elif not isinstance(aceita, bool):
        return None
    bruto = obj.get("confidence", 0.0)
    try:
        confidence = float(bruto)
    except (TypeError, ValueError):
        confidence = float("nan")
    if confidence != confidence or confidence in (float("inf"), float("-inf")):
        # confidence nao-finita vale como ausencia de confianca.
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    return {
        "accept": bool(aceita),
        "confidence": confidence,
        "reason": str(obj.get("reason", ""))[:400],
    }


def _known_tools(tools):
    nomes = []
    for t in tools or []:
        fn = (t or {}).get("function") or {}
        if fn.get("name"):
            nomes.append(fn["name"])
    return nomes


def _structural_reject(call, tools):
    """Checagem local: ferramenta inexistente ou arguments nao-JSON.

    Devolve o motivo, ou None quando a estrutura e aceitavel.
    """
    fn = (call or {}).get("function") or {}
    nome = fn.get("name")
    if not nome:
        return "tool call sem nome de funcao"
    if tools and nome not in _known_tools(tools):
        return f"ferramenta inexistente no catalogo: {nome}"
    argumentos = fn.get("arguments")
    if isinstance(argumentos, str):
        try:
            json.loads(argumentos or "{}")
        except ValueError:
            return f"arguments nao é JSON valido ({nome})"
    elif argumentos is not None and not isinstance(argumentos, dict):
        return f"arguments de tipo inesperado ({nome})"
    return None


def _ask_verdict(endpoint, model, prompt_text, tool_call, tools, timeout, _urlopen):
    corpo = {
        "pergunta_do_utilizador": (prompt_text or "")[:1200],
        "chamada_a_despachar": tool_call,
        "catalogo": [{"nome": (t or {}).get("function", {}).get("name"),
                      "descricao": (t or {}).get("function", {}).get("description"),
                      "parametros": ((t or {}).get("function", {}) or {}).get("parameters")}
                     for t in (tools or [])][:8],
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_RULE},
            {"role": "user", "content": json.dumps(corpo, ensure_ascii=False)},
        ],
        "temperature": 0,
        "max_tokens": 160,
    }
    out = _post(endpoint, payload, timeout, _urlopen)
    if out is None:
        return None
    return _verdict_shape(out["content"])


def validate_tool_call(*, profile, prompt_text, tool_call, tools=None,
                       _urlopen=None, _systemctl=None):
    """Rota GPU -> validador CPU -> fallback CPU.

    Devolve dict com `verdict` (aprovada|rejeitada|indisponivel), `stage`,
    `confidence`, `reason` e `model`. Nunca executa nada: e so o portao.
    """
    cfg = routing_for(profile) if isinstance(profile, str) else profile
    if cfg is None:
        return {"verdict": VERDICT_UNAVAILABLE, "stage": "sem-perfil",
                "confidence": 0.0, "reason": "perfil sem camada CPU", "model": ""}

    tools = list(tools if tools is not None else getattr(cfg, "tools", []) or [])
    floor = float(getattr(cfg, "confidence_floor", DEFAULT_CONFIDENCE_FLOOR))
    call = tool_call if isinstance(tool_call, dict) else (tool_call or [None])[0]
    motivo = _structural_reject(call, tools)
    if motivo:
        return {"verdict": VERDICT_REJECTED, "stage": "estrutura",
                "confidence": 0.0, "reason": motivo, "model": ""}

    etapas = [("validador", cfg.validator_endpoint, cfg.validator_model)]
    if getattr(cfg, "fallback_endpoint", ""):
        etapas.append(("fallback", cfg.fallback_endpoint, cfg.fallback_model))

    rejeicao = None
    for stage, endpoint, model in etapas:
        v = _ask_verdict(endpoint, model, prompt_text, call, tools,
                         VALIDATOR_TIMEOUT, _urlopen)
        if v is None:
            continue
        aceita = v["accept"] and v["confidence"] >= floor
        if aceita:
            return {"verdict": VERDICT_APPROVED, "stage": stage,
                    "confidence": v["confidence"], "reason": v["reason"],
                    "model": model}
        # Rejeicao do validador NAO encerra: a mesma intencao sobe ao fallback
        # (segunda opiniao barata), por politica do plano da camada CPU.
        rejeicao = {"verdict": VERDICT_REJECTED, "stage": stage,
                    "confidence": v["confidence"], "reason": v["reason"],
                    "model": model}
    if rejeicao is not None:
        return rejeicao
    return {"verdict": VERDICT_UNAVAILABLE, "stage": "validador+fallback",
            "confidence": 0.0, "reason": "nenhum validador CPU respondeu",
            "model": ""}


# ------------------------------------------------------------------ tokenize


def _token_ids(text, endpoint, _urlopen):
    if _urlopen is None:
        _urlopen = _default_urlopen
    req = urlrequest.Request(
        endpoint.rstrip("/") + "/tokenize",
        data=json.dumps({"content": text}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = _urlopen(req, timeout=30)
    return json.loads(resp.read()).get("tokens", [])


def _detokenize(tokens, endpoint, _urlopen):
    if _urlopen is None:
        _urlopen = _default_urlopen
    req = urlrequest.Request(
        endpoint.rstrip("/") + "/detokenize?prompt=true",
        data=json.dumps({"tokens": tokens}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = _urlopen(req, timeout=30)
    return json.loads(resp.read()).get("content", "")


# ------------------------------------------------------------------ compactor


def _unit_active(unit, _systemctl):
    if _systemctl is None:
        try:
            out = subprocess.run(["systemctl", "is-active", unit],
                                 capture_output=True, text=True, timeout=5,
                                 check=False)
            return out.stdout.strip() == "active"
        except (OSError, subprocess.SubprocessError, ValueError):
            return False
    return _systemctl("is-active", unit) == "active"


def _unit_action(action, unit, _systemctl):
    if _systemctl is None:
        try:
            r = subprocess.run(["systemctl", action, unit], capture_output=True,
                               text=True, timeout=120, check=False)
            return r.returncode == 0
        except (OSError, subprocess.SubprocessError, ValueError):
            return False
    return bool(_systemctl(action, unit))


def _wait_health(endpoint, budget, _urlopen):
    import time
    if _urlopen is None:
        _urlopen = _default_urlopen
    deadline = time.time() + budget
    intervalo = 2
    while time.time() < deadline:
        try:
            req = urlrequest.Request(endpoint.rstrip("/") + "/health", method="GET")
            resp = _urlopen(req, timeout=5)
            if b"ok" in resp.read():
                return True
        except (urllib.error.URLError, OSError, ValueError, AttributeError):
            pass
        # Dormir SEMPRE: um llama-server que responde 200 sem "ok" (slots
        # ocupados, modelo a carregar) transformava este laço em busy-poll.
        time.sleep(intervalo)
        intervalo = min(intervalo * 2, 10)
    return False


def _summary_prompt(chunk):
    """Prompt de resumo para UM bloco já limitado em tokens (nunca cortado à mão)."""
    chaves = ", ".join(FACT_KEYS)
    return (
        COMPRESSION_PROMPT
        + "Resuma o excerto seguinte como linhas de factos, cada linha no formato "
        + f"CHAVE: valor, usando apenas estas chaves: {chaves}. "
        + "Nao invente factos; omita chaves sem conteudo.\n\n"
        + "EXCERTO A RESUMIR:\n" + chunk
    )


def _chunks_por_tokens(tokens, chunk_tokens):
    return [tokens[i:i + chunk_tokens] for i in range(0, len(tokens), chunk_tokens)]


def compact_context(*, profile, prompt, _urlopen=None, _systemctl=None):
    """Compacta `prompt` acima do limiar; nunca descarta texto em silêncio.

    A cabeça é dividida em blocos de `COMPACT_CHUNK_TOKENS` tokens e TODOS os
    blocos vão ao compactador (map-reduce); a cauda (`compact_keep_tokens`)
    mantém-se literal. Se um bloco falhar, não produzir factos reconhecíveis,
    ou a cabeça exceder `COMPACT_MAX_CHUNKS`, a compactação é RECUSADA e o
    prompt volta intacto com o `reason` — melhor um prompt grande do que um
    prompt amputado.

    Devolve dict com `compacted`, `before`, `after`, `head_tokens`, `chunks`,
    `prompt` (novo ou original) e `reason`/`model`/`summary_sha256`.
    """
    if _urlopen is None:
        _urlopen = _default_urlopen
    cfg = routing_for(profile) if isinstance(profile, str) else profile
    if cfg is None or not getattr(cfg, "compactor_endpoint", ""):
        return {"compacted": False, "prompt": prompt, "reason": "sem compactador"}
    threshold = int(getattr(cfg, "compact_threshold_tokens", DEFAULT_COMPACT_THRESHOLD))
    keep = int(getattr(cfg, "compact_keep_tokens", RECENT_TAIL_TOKENS))
    tokenizer = cfg.validator_endpoint or "http://127.0.0.1:8090"
    try:
        tokens = _token_ids(prompt, tokenizer, _urlopen)
    except (urllib.error.URLError, OSError, ValueError):
        return {"compacted": False, "prompt": prompt, "reason": "tokenizer indisponivel"}
    if not isinstance(tokens, list) or not tokens:
        return {"compacted": False, "prompt": prompt, "reason": "tokenizer indisponivel"}
    before = len(tokens)
    if before <= threshold:
        return {"compacted": False, "prompt": prompt, "before": before,
                "reason": "dentro do limiar"}

    corte = max(0, before - keep)
    cabeca_tokens, cauda_tokens = tokens[:corte], tokens[corte:]
    if not cabeca_tokens:
        return {"compacted": False, "prompt": prompt, "before": before,
                "reason": "cabeca vazia"}
    blocos = _chunks_por_tokens(cabeca_tokens, COMPACT_CHUNK_TOKENS)
    if len(blocos) > COMPACT_MAX_CHUNKS:
        return {"compacted": False, "prompt": prompt, "before": before,
                "head_tokens": len(cabeca_tokens),
                "reason": "cabeca excede budget (%d blocos > %d)"
                          % (len(blocos), COMPACT_MAX_CHUNKS)}
    try:
        textos = [_detokenize(b, tokenizer, _urlopen) for b in blocos]
        cauda = _detokenize(cauda_tokens, tokenizer, _urlopen)
    except (urllib.error.URLError, OSError, ValueError):
        return {"compacted": False, "prompt": prompt, "before": before,
                "reason": "detokenize indisponivel"}
    cortados = [t for t in textos if len(t) > COMPACT_CHUNK_CHARS]
    if cortados or not cauda.strip():
        return {"compacted": False, "prompt": prompt, "before": before,
                "head_tokens": len(cabeca_tokens),
                "reason": "bloco excede limite de caracteres"}

    unit = getattr(cfg, "compactor_unit", "")
    started = False
    if unit and not _unit_active(unit, _systemctl):
        if not _unit_action("start", unit, _systemctl):
            return {"compacted": False, "prompt": prompt, "before": before,
                    "reason": "falha ao arrancar compactor"}
        started = True
        if not _wait_health(cfg.compactor_endpoint, COMPACTOR_HEALTH_WAIT, _urlopen):
            _unit_action("stop", unit, _systemctl)
            return {"compacted": False, "prompt": prompt, "before": before,
                    "reason": "compactor sem saude"}
    try:
        linhas = []
        for i, texto in enumerate(textos):
            out = _post(cfg.compactor_endpoint, {
                "model": cfg.compactor_model,
                "messages": [{"role": "user", "content": _summary_prompt(texto)}],
                "temperature": 0,
                "max_tokens": COMPACT_SUMMARY_TOKENS,
            }, COMPACTOR_TIMEOUT, _urlopen)
            if out is None:
                return {"compacted": False, "prompt": prompt, "before": before,
                        "head_tokens": len(cabeca_tokens), "chunks": len(textos),
                        "reason": "compactor nao respondeu no bloco %d" % (i + 1)}
            limpo = _clean_compression_output(out["content"])
            if not limpo.strip():
                # Sem factos reconheciveis = conteúdo do bloco perdido; recusa.
                return {"compacted": False, "prompt": prompt, "before": before,
                        "head_tokens": len(cabeca_tokens), "chunks": len(textos),
                        "reason": "bloco %d sem resumo reconhecivel" % (i + 1)}
            linhas.append(limpo.strip())
    finally:
        if started and unit:
            _unit_action("stop", unit, _systemctl)
    summary = "\n".join(linhas)
    novo = ("CONTEXTO ANTERIOR (resumo compactado):\n" + summary
            + "\n\nCONTEXTO RECENTE (literal):\n" + cauda)
    try:
        after = len(_token_ids(novo, tokenizer, _urlopen))
    except (urllib.error.URLError, OSError, ValueError):
        after = -1
    if after >= before:
        return {"compacted": False, "prompt": prompt, "before": before,
                "after": after, "head_tokens": len(cabeca_tokens),
                "chunks": len(textos), "reason": "resumo nao reduziu"}
    return {"compacted": True, "prompt": novo, "before": before, "after": after,
            "head_tokens": len(cabeca_tokens), "chunks": len(textos),
            "model": cfg.compactor_model,
            "summary_sha256": hashlib.sha256(summary.encode("utf-8")).hexdigest()}


def record_event(db, session_id, event_type, details):
    """Escreve um evento no audit trail da sessao (mesma tabela de PAUSED)."""
    with db:
        db.execute(
            """INSERT INTO audit_events
            (event_id, session_id, event_type, details_json)
            VALUES (?, ?, ?, ?)""",
            (secrets.token_hex(8), session_id, event_type,
             json.dumps(details, ensure_ascii=False)),
        )
    return True
