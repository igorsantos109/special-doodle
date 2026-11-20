"""Testes da camada CPU agentica (cpu_agent) e do portao no grafo real.

Nada toca em serviços reais: `_urlopen` e `_systemctl` sao sempre injectados
(ou monkeypatchados no default do modulo). Foco no que a revisao de
08/11/2026 apontou: veredito fail-open, `choices` malformado, timeouts que
nunca chegavam ao socket, compactacao que descartava texto em silencio,
aprovacao sem validador e validacao apenas da 1.ª tool call.
"""

import json
import os
import urllib.error
import urllib.parse

import pytest

from pcsala_agent import cpu_agent
from pcsala_agent.database import connect
from pcsala_agent.inference_profiles import AGENT_TOOL_CATALOG, get_profile
from pcsala_agent.migrations import migrate
from pcsala_agent.real_graph import execute

CFG = get_profile("cpu-agent-v1")
CATALOGO = AGENT_TOOL_CATALOG


def _response(body=b""):
    class FakeResponse:
        def __init__(self):
            self.body = body

        def read(self, n=-1):
            return self.body[:n] if n >= 0 else self.body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass
    return FakeResponse()


def _chat(texto):
    return _response(body=json.dumps({
        "choices": [{"message": {"content": texto}, "finish_reason": "stop"}],
        "model": "fake",
    }).encode())


def _veredito(aceita, confianca, motivo="ok"):
    return _chat(json.dumps({"accept": aceita, "confidence": confianca,
                             "reason": motivo}))


def _call(nome, argumentos):
    args = (json.dumps(argumentos) if isinstance(argumentos, dict)
            else argumentos)
    return {"id": "c1", "type": "function",
            "function": {"name": nome, "arguments": args}}


class _Opener:
    """Roteador fake: regista (porta, path, timeout, payload) de cada chamada.

    `respostas` mapeia porta -> resposta (ou funcao do payload).
    `erros` mapeia porta -> excepcao a levantar.
    """

    def __init__(self, respostas=None, erros=None):
        self.respostas = respostas or {}
        self.erros = erros or {}
        self.chamadas = []

    def __call__(self, request, *args, **kwargs):
        url = request.full_url
        porta = urllib.parse.urlsplit(url).port
        corpo = json.loads(request.data.decode()) if getattr(request, "data", None) else {}
        self.chamadas.append({"porta": porta,
                             "path": urllib.parse.urlsplit(url).path,
                             "timeout": kwargs.get("timeout"),
                             "payload": corpo})
        if porta in self.erros:
            raise self.erros[porta]
        resposta = self.respostas.get(porta)
        if callable(resposta):
            return resposta(corpo)
        if resposta is not None:
            return resposta
        raise urllib.error.URLError(f"sem rota fake para {porta}")


# ------------------------------------------------------------------ veredito


class TestShapeDoVeredito:
    def test_booleanos_literais(self):
        v1 = cpu_agent._verdict_shape('{"accept": true, "confidence": 0.9}')
        v2 = cpu_agent._verdict_shape('{"accept": false, "confidence": 0.9}')
        assert v1["accept"] is True and v2["accept"] is False

    def test_string_false_nao_e_aprovacao(self):
        """Era fail-open: bool("false") vale True."""
        for bruto in ('{"accept": "false", "confidence": 0.9}',
                      '{"accept": "no", "confidence": 0.9}',
                      '{"accept": "0", "confidence": 0.9}'):
            assert cpu_agent._verdict_shape(bruto)["accept"] is False

    def test_afirmativas_em_string_sao_toleradas(self):
        assert cpu_agent._verdict_shape('{"accept": "sim", "confidence": 0.8}')['accept'] is True

    def test_accept_de_tipo_impossivel_e_veredito_invalido(self):
        assert cpu_agent._verdict_shape('{"accept": [1], "confidence": 0.9}') is None
        assert cpu_agent._verdict_shape('{"confidence": 0.9}') is None

    def test_confidence_nan_vale_zero(self):
        v = cpu_agent._verdict_shape('{"accept": true, "confidence": "nan"}')
        assert v["confidence"] == 0.0

    def test_confidence_infinita_vale_zero(self):
        v = cpu_agent._verdict_shape('{"accept": true, "confidence": 1e999}')
        assert v["confidence"] == 0.0

    def test_sem_json_e_cerca_de_codigo(self):
        assert cpu_agent._verdict_shape("sem objecto aqui") is None
        v = cpu_agent._verdict_shape('```json\n{"accept": true, "confidence": 0.7}\n```')
        assert v["accept"] is True and v["confidence"] == 0.7


class TestPostRobusto:
    def test_choices_vazio_devolve_none_em_vez_de_indexerror(self):
        opener = _Opener({8103: _response(body=json.dumps({"choices": []}).encode())})
        assert cpu_agent._post("http://127.0.0.1:8103", {"m": 1}, 30, opener) is None

    def test_choices_elemento_nao_dict_devolve_none(self):
        opener = _Opener({8103: _response(body=json.dumps({"choices": ["x"]}).encode())})
        assert cpu_agent._post("http://127.0.0.1:8103", {"m": 1}, 30, opener) is None

    def test_sem_choices_devolve_none(self):
        opener = _Opener({8103: _response(body=json.dumps({"error": "x"}).encode())})
        assert cpu_agent._post("http://127.0.0.1:8103", {"m": 1}, 30, opener) is None

    def test_content_nulo_vazString(self):
        opener = _Opener({8103: _response(body=json.dumps(
            {"choices": [{"message": {"content": None}}]}).encode())})
        assert cpu_agent._post("http://127.0.0.1:8103", {"m": 1}, 30, opener)["content"] == ""


# ------------------------------------------------------------------- rota


class TestValidacaoDeToolCall:
    def test_perfil_legado_sem_rotas(self):
        r = cpu_agent.validate_tool_call(
            profile="cpu-triage-v1", prompt_text="x",
            tool_call=_call("consultar_ficheiros", {"path": "src", "operacao": "ler"}),
            tools=CATALOGO)
        assert r["verdict"] == cpu_agent.VERDICT_UNAVAILABLE

    def test_ferramenta_inexistente_rejeitada_sem_rede(self):
        opener = _Opener()
        r = cpu_agent.validate_tool_call(
            profile=CFG, prompt_text="lista src",
            tool_call=_call("apagar_tudo", {"path": "/"}),
            tools=CATALOGO, _urlopen=opener)
        assert r["verdict"] == cpu_agent.VERDICT_REJECTED and r["stage"] == "estrutura"
        assert opener.chamadas == []

    def test_arguments_nao_json_rejeitados_sem_rede(self):
        opener = _Opener()
        r = cpu_agent.validate_tool_call(
            profile=CFG, prompt_text="lista src",
            tool_call=_call("consultar_ficheiros", "{path quebrado"),
            tools=CATALOGO, _urlopen=opener)
        assert r["verdict"] == cpu_agent.VERDICT_REJECTED and opener.chamadas == []

    def test_confianca_abaixo_do_floor_rejeita_e_sobe_ao_fallback(self):
        opener = _Opener({8103: _veredito(True, 0.2), 8104: _veredito(True, 0.2)})
        r = cpu_agent.validate_tool_call(
            profile=CFG, prompt_text="x",
            tool_call=_call("consultar_ficheiros", {"path": "src", "operacao": "ler"}),
            tools=CATALOGO, _urlopen=opener)
        assert r["verdict"] == cpu_agent.VERDICT_REJECTED and r["stage"] == "fallback"
        assert [c["porta"] for c in opener.chamadas] == [8103, 8104]

    def test_aceite_acima_do_floor(self):
        opener = _Opener({8103: _veredito(True, 0.95)})
        r = cpu_agent.validate_tool_call(
            profile=CFG, prompt_text="lista os ficheiros de src",
            tool_call=_call("consultar_ficheiros", {"path": "src", "operacao": "listar"}),
            tools=CATALOGO, _urlopen=opener)
        assert r["verdict"] == cpu_agent.VERDICT_APPROVED and r["stage"] == "validador"
        assert len(opener.chamadas) == 1

    def test_rejeicao_do_validador_sobe_ao_fallback(self):
        opener = _Opener({8103: _veredito(False, 0.9, "fora do ambito"),
                          8104: _veredito(True, 0.95, "ok")})
        r = cpu_agent.validate_tool_call(
            profile=CFG, prompt_text="lista src",
            tool_call=_call("consultar_ficheiros", {"path": "src", "operacao": "ler"}),
            tools=CATALOGO, _urlopen=opener)
        assert r["verdict"] == cpu_agent.VERDICT_APPROVED and r["stage"] == "fallback"

    def test_ambos_rejeitam(self):
        opener = _Opener({8103: _veredito(False, 0.9), 8104: _veredito(False, 0.8)})
        r = cpu_agent.validate_tool_call(
            profile=CFG, prompt_text="x",
            tool_call=_call("consultar_ficheiros", {"path": "/etc", "operacao": "ler"}),
            tools=CATALOGO, _urlopen=opener)
        assert r["verdict"] == cpu_agent.VERDICT_REJECTED and r["stage"] == "fallback"

    def test_validador_em_baixo_usa_fallback(self):
        opener = _Opener({8104: _veredito(True, 0.9)},
                         erros={8103: urllib.error.URLError("recusado")})
        r = cpu_agent.validate_tool_call(
            profile=CFG, prompt_text="x",
            tool_call=_call("registrar_resultado", {"nota": "ok"}),
            tools=CATALOGO, _urlopen=opener)
        assert r["verdict"] == cpu_agent.VERDICT_APPROVED and r["stage"] == "fallback"

    def test_dois_em_baixo_indisponivel(self):
        erro = urllib.error.URLError("down")
        opener = _Opener(erros={8103: erro, 8104: erro})
        r = cpu_agent.validate_tool_call(
            profile=CFG, prompt_text="x",
            tool_call=_call("registrar_resultado", {"nota": "ok"}),
            tools=CATALOGO, _urlopen=opener)
        assert r["verdict"] == cpu_agent.VERDICT_UNAVAILABLE

    def test_veredito_ilegivel_nao_aprova(self):
        opener = _Opener({8103: _chat("acho que esta tudo bem"),
                          8104: _chat("acho que esta tudo bem")})
        r = cpu_agent.validate_tool_call(
            profile=CFG, prompt_text="x",
            tool_call=_call("consultar_ficheiros", {"path": "src", "operacao": "ler"}),
            tools=CATALOGO, _urlopen=opener)
        assert r["verdict"] == cpu_agent.VERDICT_UNAVAILABLE

    def test_timeout_chega_ao_socket(self):
        opener = _Opener({8103: _veredito(True, 0.95)})
        cpu_agent.validate_tool_call(
            profile=CFG, prompt_text="x",
            tool_call=_call("consultar_ficheiros", {"path": "src", "operacao": "ler"}),
            tools=CATALOGO, _urlopen=opener)
        assert opener.chamadas[0]["timeout"] == cpu_agent.VALIDATOR_TIMEOUT

    def test_urlopen_default_repassa_kwargs(self, monkeypatch):
        vistos = []

        def spy(request, *args, **kwargs):
            vistos.append(kwargs.get("timeout"))
            raise urllib.error.URLError("para")
        monkeypatch.setattr(cpu_agent.urlrequest, "urlopen", spy)
        with pytest.raises(urllib.error.URLError):
            cpu_agent._default_urlopen("u", timeout=13)
        assert vistos == [13]


# ------------------------------------------------------------------ compactar


def _opener_compactar(resumo="OBJECTIVO: continuar a tarefa\n", erro_compactador=None):
    """Fake de tokenizer (1 token por caracter) + compactador em 8105."""
    registo = []

    def opener(request, *args, **kwargs):
        url = request.full_url
        path = urllib.parse.urlsplit(url).path
        porta = urllib.parse.urlsplit(url).port
        corpo = json.loads(request.data.decode()) if getattr(request, "data", None) else {}
        registo.append({"porta": porta, "path": path, "timeout": kwargs.get("timeout"),
                        "chars": len(corpo.get("messages", [{}])[0].get("content", ""))
                        if corpo else 0})
        if path.endswith("/health"):
            return _response(body=b'{"status":"ok"}')
        if path.endswith("/tokenize"):
            return _response(body=json.dumps(
                {"tokens": list(range(1, len(corpo["content"]) + 1))}).encode())
        if path.endswith("/detokenize"):
            return _response(body=json.dumps(
                {"content": "".join(f"t{t}" for t in corpo["tokens"])}).encode())
        if path.endswith("/v1/chat/completions") and porta == 8105:
            if erro_compactador is not None:
                raise erro_compactador
            return _chat(resumo)
        raise urllib.error.URLError(f"sem rota fake para {url}")
    opener.registo = registo
    return opener


def _systemctl_falso(activo=False):
    accoes = []

    def systemctl(acao, unidade):
        accoes.append((acao, unidade))
        if acao == "is-active":
            return "active" if activo else "inactive"
        return True
    systemctl.acoes = accoes
    return systemctl


class TestCompactContext:
    def test_abaixo_do_limiar_nao_compacta(self):
        opener = _opener_compactar()
        r = cpu_agent.compact_context(profile=CFG, prompt="x" * 100,
                                      _urlopen=opener, _systemctl=_systemctl_falso())
        assert r["compacted"] is False and r["reason"] == "dentro do limiar"
        assert [c for c in opener.registo
                if c["path"].endswith("/v1/chat/completions")] == []

    def test_sem_urlopen_injectado_usa_default_do_modulo(self, monkeypatch):
        """A API publica aceita `_urlopen=None`: nao pode rebentar nem chamar rede."""
        def stub(request, *args, **kwargs):
            raise urllib.error.URLError("sem rede nos testes")
        monkeypatch.setattr(cpu_agent, "_default_urlopen", stub)
        r = cpu_agent.compact_context(profile=CFG, prompt="x" * 40000)
        assert r["compacted"] is False
        assert r["reason"] == "tokenizer indisponivel"

    def test_todos_os_blocos_vao_ao_compactador_sem_corte_de_chars(self):
        keep = CFG.compact_keep_tokens
        opener = _opener_compactar()
        prompt = "a" * 20000
        r = cpu_agent.compact_context(profile=CFG, prompt=prompt, _urlopen=opener,
                                      _systemctl=_systemctl_falso())
        assert r["compacted"] is True
        assert r["before"] == 20000
        assert r["head_tokens"] == 20000 - keep
        esperados = -(-r["head_tokens"] // cpu_agent.COMPACT_CHUNK_TOKENS)
        blocos = [c for c in opener.registo if c["porta"] == 8105
                  and c["path"].endswith("/v1/chat/completions")]
        assert len(blocos) == esperados == r["chunks"]
        # nenhum bloco e cortado à mao: cada envio cabe no limite de caracteres
        assert all(c["chars"] <= cpu_agent.COMPACT_CHUNK_CHARS for c in blocos)
        # a soma dos envios cobre toda a cabeca (nada fica por resumir)
        assert sum(c["chars"] for c in blocos) >= r["head_tokens"]
        assert "CONTEXTO ANTERIOR (resumo compactado)" in r["prompt"]
        assert "CONTEXTO RECENTE (literal)" in r["prompt"]

    def test_bloco_sem_factos_recusa_compactacao(self):
        opener = _opener_compactar(resumo="prosa solta sem as chaves de factos")
        r = cpu_agent.compact_context(profile=CFG, prompt="b" * 20000, _urlopen=opener,
                                      _systemctl=_systemctl_falso())
        assert r["compacted"] is False and "sem resumo reconhecivel" in r["reason"]
        assert r["prompt"].startswith("b" * 40)

    def test_compactador_em_baixo_recusa_compactacao(self):
        opener = _opener_compactar(erro_compactador=urllib.error.URLError("morto"))
        r = cpu_agent.compact_context(profile=CFG, prompt="c" * 20000, _urlopen=opener,
                                      _systemctl=_systemctl_falso())
        assert r["compacted"] is False and "nao respondeu" in r["reason"]

    def test_cabeca_fora_do_budget_e_recusada(self):
        opener = _opener_compactar()
        r = cpu_agent.compact_context(profile=CFG, prompt="d" * 200000, _urlopen=opener,
                                      _systemctl=_systemctl_falso())
        assert r["compacted"] is False
        assert "cabeca excede budget" in r["reason"]

    def test_unit_arrancada_e_parada_aroundo_do_job(self):
        systemctl = _systemctl_falso(activo=False)
        opener = _opener_compactar()
        r = cpu_agent.compact_context(profile=CFG, prompt="e" * 20000, _urlopen=opener,
                                      _systemctl=systemctl)
        assert r["compacted"] is True
        assert ("start", CFG.compactor_unit) in systemctl.acoes
        assert ("stop", CFG.compactor_unit) in systemctl.acoes

    def test_unit_ja_activa_nao_e_parada(self):
        systemctl = _systemctl_falso(activo=True)
        r = cpu_agent.compact_context(profile=CFG, prompt="f" * 20000,
                                      _urlopen=_opener_compactar(),
                                      _systemctl=systemctl)
        assert r["compacted"] is True
        assert ("start", CFG.compactor_unit) not in systemctl.acoes
        assert ("stop", CFG.compactor_unit) not in systemctl.acoes

    def test_timeout_do_compactador_chega_ao_socket(self):
        opener = _opener_compactar()
        cpu_agent.compact_context(profile=CFG, prompt="g" * 20000, _urlopen=opener,
                                  _systemctl=_systemctl_falso(activo=True))
        chamadas = [c for c in opener.registo if c["porta"] == 8105
                    and c["path"].endswith("/v1/chat/completions")]
        assert chamadas and all(
            c["timeout"] == cpu_agent.COMPACTOR_TIMEOUT for c in chamadas)

    def test_health_espera_mesmo_com_resposta_sem_ok(self, monkeypatch):
        """200 sem "ok" nao pode virar busy-poll: o laço tem de dormir."""
        dormidos = []
        relogio = {"t": 0.0}
        monkeypatch.setattr("time.time", lambda: relogio["t"])
        def dormir(s):
            dormidos.append(s)
            relogio["t"] += s
        monkeypatch.setattr("time.sleep", dormir)

        def opener(request, *args, **kwargs):
            if request.full_url.endswith("/health"):
                return _response(body=b'{"status":"loading"}')
            raise urllib.error.URLError("espera")
        ok = cpu_agent._wait_health("http://127.0.0.1:8105", 6, opener)
        assert ok is False
        assert dormidos and dormidos[0] >= 2


# -------------------------------------------------------------- portao no grafo


@pytest.fixture
def env(tmp_path):
    migrate(tmp_path / "state.sqlite")
    db = connect(tmp_path / "state.sqlite")
    with db:
        db.execute("INSERT INTO projects(project_id,name,authorized_root) "
                   "VALUES ('p','T','/tmp')")
        db.execute("INSERT INTO sessions(session_id,project_id,state,revision) "
                   "VALUES ('s','p','RUNNING',0)")
        db.execute("INSERT INTO tasks(task_id,project_id,title,acceptance_criteria,status) "
                   "VALUES ('t','p','T','ok','RUNNING')")
        db.execute("INSERT INTO attempts(attempt_id,project_id,session_id,task_id,status) "
                   "VALUES ('a','p','s','t','RUNNING')")
    db.close()
    return tmp_path


def _gpu_com_tool_calls(*chamadas):
    return _response(body=json.dumps({
        "choices": [{"message": {"content": None, "tool_calls": list(chamadas)},
                    "finish_reason": "tool_calls"}],
        "model": "gpu",
    }).encode())


def _gpu_texto(texto):
    return _chat(texto)


def _opener_grafo(gpu, validador=None, fallback=None):
    """GPU do perfil + portao CPU (8103/8104); /tokenize do gate devolve tokens."""
    registo = []

    def opener(request, *args, **kwargs):
        url = request.full_url
        porta = urllib.parse.urlsplit(url).port
        path = urllib.parse.urlsplit(url).path
        registo.append((porta, path))
        if path.endswith("/tokenize"):
            corpo = json.loads(request.data.decode())
            return _response(body=json.dumps(
                {"tokens": list(range(1, len(corpo["content"]) + 1))}).encode())
        if porta in (8103, 8104):
            r = validador if porta == 8103 else fallback
            if r is None:
                r = _veredito(True, 0.95)
            return r
        return gpu
    opener.registo = registo
    return opener


def _estado(env):
    db = connect(env / "state.sqlite")
    ops = dict(db.execute("SELECT operation_type,status FROM operations"))
    eventos = [row["event_type"] for row in db.execute(
        "SELECT event_type FROM audit_events WHERE session_id='s'")]
    attempt = db.execute("SELECT status FROM attempts WHERE attempt_id='a'").fetchone()[0]
    db.close()
    return ops, eventos, attempt


class TestPortaoNoGrafo:
    def test_aprovada_so_depois_do_veredito(self, env):
        os.environ["DSH_LOCAL_API_KEY"] = "k"
        opener = _opener_grafo(_gpu_com_tool_calls(
            _call("consultar_ficheiros", {"path": "src", "operacao": "listar"})))
        r = execute(env, "iniciar", "p", "s", "t", "a", "lista src",
                    _urlopen=opener, profile="cpu-agent-v1",
                    _skip_health_check=True, _systemctl=_systemctl_falso())
        assert r["tool_dispatch"] == "aprovado_aguarda_executor"
        assert len(r["tool_calls"]) == 1
        assert r["tool_validation"][0]["verdict"] == "aprovada"
        ops, eventos, attempt = _estado(env)
        assert "TOOL_CALL_VALIDATED" in eventos
        assert ops["INFERENCE"] == "COMPLETED"
        assert any(k.startswith("TOOL_DISPATCH") for k in ops)
        assert attempt == "SUCCEEDED"

    def test_rejeicao_fecha_inference_e_marca_falha(self, env):
        os.environ["DSH_LOCAL_API_KEY"] = "k"
        opener = _opener_grafo(
            _gpu_com_tool_calls(_call("consultar_ficheiros", {"path": "/etc", "operacao": "ler"})),
            validador=_veredito(False, 0.9, "fora do projecto"),
            fallback=_veredito(False, 0.9, "fora do projecto"))
        r = execute(env, "iniciar", "p", "s", "t", "a", "resume o changelog",
                    _urlopen=opener, profile="cpu-agent-v1",
                    _skip_health_check=True, _systemctl=_systemctl_falso())
        assert "rejeitada" in r["error"] and "tool_calls" not in r
        assert [(p, path) for p, path in opener.registo
                if p in (8103, 8104) and path.endswith("/v1/chat/completions")] == [
            (8103, "/v1/chat/completions"), (8104, "/v1/chat/completions")]
        ops, _, attempt = _estado(env)
        assert ops["INFERENCE"] == "FAILED" and attempt == "FAILED"

    def test_multiplas_calls_validadas_uma_a_uma(self, env):
        os.environ["DSH_LOCAL_API_KEY"] = "k"
        opener = _opener_grafo(_gpu_com_tool_calls(
            _call("consultar_ficheiros", {"path": "src", "operacao": "listar"}),
            _call("registrar_resultado", {"nota": "ok"})))
        r = execute(env, "iniciar", "p", "s", "t", "a", "lista e regista",
                    _urlopen=opener, profile="cpu-agent-v1",
                    _skip_health_check=True, _systemctl=_systemctl_falso())
        assert len(r["tool_validation"]) == 2 and len(r["tool_calls"]) == 2

    def test_uma_rejeicao_entre_varias_bloqueia_o_despacho(self, env):
        os.environ["DSH_LOCAL_API_KEY"] = "k"

        def veredito_por_nome(corpo):
            m = json.loads(corpo["messages"][1]["content"])
            nome = m["chamada_a_despachar"]["function"]["name"]
            return _veredito(nome == "consultar_ficheiros", 0.9, nome)

        def opener(request, *args, **kwargs):
            porta = urllib.parse.urlsplit(request.full_url).port
            path = urllib.parse.urlsplit(request.full_url).path
            if path.endswith("/tokenize"):
                corpo = json.loads(request.data.decode())
                return _response(body=json.dumps(
                    {"tokens": list(range(1, len(corpo["content"]) + 1))}).encode())
            if porta in (8103, 8104):
                return veredito_por_nome(json.loads(request.data.decode()))
            return _gpu_com_tool_calls(
                _call("consultar_ficheiros", {"path": "src", "operacao": "listar"}),
                _call("registrar_resultado", {"nota": "apagar tudo"}))

        r = execute(env, "iniciar", "p", "s", "t", "a", "lista e regista",
                    _urlopen=opener, profile="cpu-agent-v1",
                    _skip_health_check=True, _systemctl=_systemctl_falso())
        assert "rejeitada" in r["error"] and "tool_calls" not in r
        ops, _, _ = _estado(env)
        assert ops["INFERENCE"] == "FAILED"

    def test_perfil_sem_rotas_e_falha_fechada(self, env):
        """gpu-triage-v1 nao tem validador: tool calls nunca saem aprovadas."""
        os.environ["DSH_LOCAL_API_KEY"] = "k"
        opener = _opener_grafo(_gpu_com_tool_calls(
            _call("consultar_ficheiros", {"path": "src", "operacao": "listar"})))
        r = execute(env, "iniciar", "p", "s", "t", "a", "lista src",
                    _urlopen=opener, profile="gpu-triage-v1",
                    tools=[{"type": "function",
                            "function": {"name": "consultar_ficheiros"}}],
                    _skip_health_check=True)
        assert "sem rotas CPU" in r["error"]
        assert r.get("tool_dispatch") is None
        ops, _, attempt = _estado(env)
        assert ops["INFERENCE"] == "FAILED" and attempt == "FAILED"

    def test_resposta_normal_nao_ganha_carimbo_de_tool(self, env):
        os.environ["DSH_LOCAL_API_KEY"] = "k"
        opener = _opener_grafo(_gpu_texto("resposta normal"))
        r = execute(env, "iniciar", "p", "s", "t", "a", "pergunta",
                    _urlopen=opener, profile="cpu-agent-v1",
                    _skip_health_check=True, _systemctl=_systemctl_falso())
        assert r["inference_response"] == "resposta normal"
        assert "tool_dispatch" not in r and "tool_calls" not in r


class TestRegistoEPerfil:
    def test_perfil_declara_catalogo(self):
        assert CFG.tools and all("function" in t for t in CFG.tools)
        nomes = [t["function"]["name"] for t in AGENT_TOOL_CATALOG]
        assert "consultar_ficheiros" in nomes and "registrar_resultado" in nomes

    def test_rotas_do_perfil(self):
        assert CFG.validator_endpoint.endswith("8103")
        assert CFG.fallback_endpoint.endswith("8104")
        assert CFG.compactor_endpoint.endswith("8105")
        assert CFG.compactor_unit == "qwen25-15b-compact.service"
