"""Regressão isolada do percurso da fila (versão de teste).

Regras desta suíte, verificadas em cada teste:
  * raiz de dados descartável sob o directório temporário do teste;
  * banco, artefactos e locks próprios (nunca /var/lib/pcsala-worker);
  * servidor HTTP falso numa porta livre 127.0.0.1;
  * todos os executores em subprocesso (CLI real e worker real);
  * encerra apenas processos iniciados por esta suíte (SIGTERM dirigido).

Nenhum teste escreve em produção, reinicia serviços ou usa GPU.

Adaptada desta versão da 1.1 (substituições mínimas, documentadas):
  * `PCSALA_ENDPOINT_*` é obrigatório para o worker usar o servidor falso —
    a 1.1 lê estas variáveis com default intacto;
  * o health check da 1.1 é por URL (`GET /health`), não via systemd, por
    isso não há chamadas a `systemctl` a registar e a secção f) só verifica
    que a produção não é perturbada;
  * indisponibilidade do servidor traduz `inference_status="UNAVAILABLE"`
    (1.1) em vez de vazio (produção) — o invariante testado é não concluir
    com resposta falsa.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import sqlite3
import subprocess
import time
from pathlib import Path

DEV = Path(__file__).resolve().parents[1]
PY = str(DEV / ".venv" / "bin" / "python")
SRC = str(DEV / "src")
PCSALA = str(DEV / "pcsala")

PROD_ROOT = "/var/lib/pcsala-worker"
PROD_HOME = "/home/igor/pc-sala-agent"
RESPOSTA = "RESPOSTA-CONECIDA-123"
UNIDADE_TESTE = "pcsala-worker-test.service"
UNIT_ARGS = ["--profile", "gpu-triage-v1", "--queue-mode"]  # exactos da unit real
TIMEOUT_TAREFA = 45

SERVIDOR_FALSO = r'''
import json, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORTA = int(sys.argv[1])
ESTADO = {"health": 0, "completions": 0, "autorizacao": 0}
BLOCOS = threading.Lock()


class H(BaseHTTPRequestHandler):
    def _responder(self, codigo, obj):
        dados = json.dumps(obj).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def do_GET(self):
        if self.path == "/health":
            with BLOCOS:
                ESTADO["health"] += 1
            self._responder(200, {"status": "ok"})
        elif self.path == "/stats":
            with BLOCOS:
                self._responder(200, dict(ESTADO))
        else:
            self._responder(404, {"erro": "nao encontrado"})

    def do_POST(self):
        tamanho = int(self.headers.get("Content-Length", 0))
        corpo = self.rfile.read(tamanho)
        del corpo
        if self.headers.get("authorization"):
            with BLOCOS:
                ESTADO["autorizacao"] += 1
        if self.path == "/v1/chat/completions":
            with BLOCOS:
                ESTADO["completions"] += 1
            self._responder(200, {
                "model": "modelo-falso",
                "choices": [{
                    "message": {"role": "assistant", "content": %r},
                    "finish_reason": "stop",
                }],
            })
        else:
            self._responder(404, {"erro": "nao encontrado"})

    def log_message(self, *args):
        pass


ThreadingHTTPServer(("127.0.0.1", PORTA), H).serve_forever()
''' % RESPOSTA

SYSTEMCTL_FALSO = '''#!/bin/sh
printf '%s\\n' "$*" >> "$PCSALA_FAKE_SYSTEMCTL_LOG"
case "$1" in
  is-active) printf '%s\\n' 'active' ;;
esac
exit 0
'''


class Ambiente:
    """Ambiente isolado: raiz descartável, porta livre, systemd falso."""

    def __init__(self, tmp_path: Path):
        self.dir = tmp_path
        self.root = tmp_path / "root"
        self.root.mkdir(exist_ok=True)
        self.porta = self._porta_livre()
        self.endpoint = f"http://127.0.0.1:{self.porta}"
        self.bin = tmp_path / "bin"
        self.bin.mkdir(exist_ok=True)
        self.log_systemctl = tmp_path / "systemctl.log"
        self.log_systemctl.touch()
        self.models = tmp_path / "models.json"
        self.chave = tmp_path / "api.key"
        self.chave.write_text("", encoding="utf-8")
        self.chave.chmod(0o600)
        self._escrever_models()
        self._escrever_systemctl_falso()
        self.servidor = None
        self.workers: list[subprocess.Popen] = []

    @staticmethod
    def _porta_livre() -> int:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def _escrever_models(self):
        self.models.write_text(json.dumps([{
            "model_id": "modelo-teste-gpu",
            "name": "Modelo de teste isolado",
            "model_class": "GPU",
            "endpoint": self.endpoint,
            "unit": UNIDADE_TESTE,
            "profile": "gpu-triage-v1",
            "allowed_operations": ["start", "stop", "health"],
            "startup_timeout": 1,
            "health_timeout": 2,
            "shared": False,
            "capabilities": ["teste"],
        }], ensure_ascii=False, indent=2), encoding="utf-8")
        self.models.chmod(0o600)

    def _escrever_systemctl_falso(self):
        alvo = self.bin / "systemctl"
        alvo.write_text(SYSTEMCTL_FALSO, encoding="utf-8")
        alvo.chmod(0o755)

    def env(self) -> dict:
        env = dict(os.environ)
        env.pop("DSH_LOCAL_API_KEY", None)   # nunca transportar segredo de produção
        env["PYTHONPATH"] = SRC
        env["PATH"] = f"{self.bin}:{env['PATH']}"
        env["PCSALA_FAKE_SYSTEMCTL_LOG"] = str(self.log_systemctl)
        env["PCSALA_ENDPOINT_GPU_TRIAGE_V1"] = self.endpoint
        env["PCSALA_ENDPOINT_CPU_TRIAGE_V1"] = self.endpoint
        env["PCSALA_ENDPOINT_LAGUNA_PROGRAMMING_V1"] = self.endpoint
        env["PCSALA_MODELS_CONFIG"] = str(self.models)
        env["PCSALA_API_KEY_FILE"] = str(self.chave)
        env["PCSALA_ROOT"] = str(self.root)
        env["PCSALA_BACKUP_DIR"] = str(self.dir / "backup")
        return env

    def confirmar_destinos(self):
        assert str(self.root).startswith(str(self.dir)), self.root
        assert self.root != PROD_ROOT and PROD_ROOT not in str(self.root)
        assert PROD_ROOT not in str(self.models)
        assert self.endpoint == env_endpoint(self.env())
        assert shutil.which("systemctl", path=self.env()["PATH"]).startswith(
            str(self.bin)
        ), "systemctl falso não está no início de PATH"

    def arrancar_servidor(self):
        script = self.dir / "servidor_falso.py"
        script.write_text(SERVIDOR_FALSO, encoding="utf-8")
        self.servidor = subprocess.Popen(
            [PY, str(script), str(self.porta)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
        )
        limite = time.time() + 15
        while time.time() < limite:
            if self._porta_aberta():
                return
            if self.servidor.poll() is not None:
                erro = self.servidor.stderr.read()
                raise AssertionError(f"servidor falso morreu: {erro}")
            time.sleep(0.1)
        raise AssertionError("servidor falso não abriu a porta")

    def _porta_aberta(self) -> bool:
        with socket.socket() as s:
            s.settimeout(0.5)
            return s.connect_ex(("127.0.0.1", self.porta)) == 0

    def parar_servidor(self):
        if self.servidor is None:
            return
        if self.servidor.poll() is None:
            self.servidor.send_signal(signal.SIGTERM)
            try:
                self.servidor.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.servidor.kill()
                self.servidor.wait(timeout=5)
        self.servidor = None

    def stats(self) -> dict:
        if not self._porta_aberta():
            return {"health": 0, "completions": 0, "autorizacao": 0}
        import urllib.request
        with urllib.request.urlopen(
            f"{self.endpoint}/stats", timeout=5
        ) as resposta:
            return json.loads(resposta.read())

    def cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [PY, PCSALA, "--root", str(self.root), *args],
            capture_output=True, text=True, env=self.env(), cwd=str(DEV),
            timeout=60,
        )

    def submeter(self, prompt: str) -> int:
        proc = self.cli("enqueue", "--prompt", prompt, "--profile",
                        "gpu-triage-v1")
        assert proc.returncode == 0, (proc.stdout, proc.stderr)
        return int(json.loads(proc.stdout)["id"])

    def estado(self, tid: int) -> dict:
        proc = self.cli("status", str(tid))
        assert proc.returncode == 0, (proc.stdout, proc.stderr)
        return json.loads(proc.stdout)

    def arrancar_worker(self) -> subprocess.Popen:
        comando = [PY, "-m", "pcsala_agent.graph_runner",
                   "--root", str(self.root), *UNIT_ARGS]
        proc = subprocess.Popen(
            comando, env=self.env(), cwd=str(DEV),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.workers.append(proc)
        return proc

    def aguardar(self, tid: int, estados: set[str],
                 timeout: float = TIMEOUT_TAREFA) -> dict:
        limite = time.time() + timeout
        ultimo = {}
        while time.time() < limite:
            ultimo = self._estado_bd(tid)
            if ultimo.get("status") in estados:
                return ultimo
            time.sleep(0.25)
        raise AssertionError(
            f"tarefa {tid} não chegou a {estados}: {ultimo}")

    def _estado_bd(self, tid: int) -> dict:
        caminho = self.root / "state.sqlite"
        if not caminho.exists():
            return {"status": "INEXISTENTE"}
        con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            linha = con.execute(
                "SELECT id, status, error, inference_response,"
                " inference_status FROM task_queue WHERE id=?",
                (tid,),
            ).fetchone()
            return dict(linha) if linha else {}
        finally:
            con.close()

    def _reservar_na_mao(self, tid: int) -> dict | None:
        from pcsala_agent.task_queue import reserve
        return reserve(self.root / "state.sqlite")

    def _forcar_status(self, tid: int, status: str, reserved_at=None):
        con = sqlite3.connect(str(self.root / "state.sqlite"))
        try:
            con.execute(
                "UPDATE task_queue SET status=?, reserved_at=? WHERE id=?",
                (status, reserved_at, tid),
            )
            con.commit()
        finally:
            con.close()

    def encerrar_workers(self):
        for proc in self.workers:
            if proc.poll() is None:
                proc.send_signal(signal.SIGTERM)
        for proc in self.workers:
            if proc.poll() is None:
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=10)
        return [(p.returncode, p.stderr.read()) for p in self.workers]

    def chamadas_systemctl(self) -> list[str]:
        return [
            linha.strip()
            for linha in self.log_systemctl.read_text().splitlines()
            if linha.strip()
        ]


def env_endpoint(env: dict) -> str:
    return env["PCSALA_ENDPOINT_GPU_TRIAGE_V1"]


def pid_worker_producao() -> str:
    proc = subprocess.run(
        ["systemctl", "show", "pcsala-worker.service", "-p", "MainPID",
         "--value"],
        capture_output=True, text=True, timeout=15,
    )
    return proc.stdout.strip()


def _base(tmp_path) -> Ambiente:
    amb = Ambiente(tmp_path)
    amb.confirmar_destinos()
    return amb



# --------------------------------------------------------------------------- a)


def test_percurso_completo_em_subprocesso(tmp_path):
    amb = _base(tmp_path)
    amb.arrancar_servidor()
    try:
        tid = amb.submeter(f"percurso base {time.time()}")
        assert amb._estado_bd(tid)["status"] == "QUEUED"

        worker = amb.arrancar_worker()
        estado = amb.aguardar(tid, {"COMPLETED", "FAILED"})

        assert estado["status"] == "COMPLETED", estado
        assert RESPOSTA in (estado["inference_response"] or ""), estado
        assert estado["inference_status"] == "SUCCESS", estado

        consulta = amb.estado(tid)
        assert consulta["status"] == "COMPLETED"
        assert RESPOSTA in consulta["inference_response"]

        stats = amb.stats()
        assert stats["completions"] == 1, stats
        assert stats["autorizacao"] == 0, "cabeçalho de autorização enviado"

        encerrados = amb.encerrar_workers()
        assert any("QueuePollCycle" in (err or "")
                   for _codigo, err in encerrados), encerrados
        assert worker.returncode is not None
    finally:
        amb.parar_servidor()
        amb.encerrar_workers()


# --------------------------------------------------------------------------- b)


def test_servidor_indisponivel_sem_conclusao_falsa(tmp_path):
    amb = _base(tmp_path)          # servidor NÃO arrancado
    try:
        tid = amb.submeter("sem servidor de inferencia")
        worker = amb.arrancar_worker()
        estado = amb.aguardar(tid, {"COMPLETED", "FAILED"})

        assert estado["status"] == "FAILED", estado
        assert estado["inference_response"] in ("", None), estado
        assert estado["inference_status"] == "UNAVAILABLE", estado
        assert estado["error"], "erro deveria ficar registado"
        assert amb.stats()["completions"] == 0
        amb.encerrar_workers()
    finally:
        amb.parar_servidor()
        amb.encerrar_workers()


# --------------------------------------------------------------------------- c)


def test_recuperacao_sem_reexecucao_indevida(tmp_path):
    amb = _base(tmp_path)
    amb.arrancar_servidor()
    try:
        # tarefa confirmada pelo grafo
        tid1 = amb.submeter("resultado ja confirmado")
        amb.arrancar_worker()
        estado = amb.aguardar(tid1, {"COMPLETED"})
        assert estado["status"] == "COMPLETED"
        conferencias = amb.stats()["completions"]

        # simula interrupção depois da inferência e antes da escrita na fila
        amb._forcar_status(tid1, "RESERVED", "2026-10-27T00:00:00")
        assert amb._estado_bd(tid1)["status"] == "RESERVED"

        proc = amb.cli("reconcile")
        estado = amb.estado(tid1)
        assert estado["status"] == "COMPLETED", (proc.stdout, proc.stderr, estado)
        assert RESPOSTA in estado["inference_response"], estado
        assert amb.stats()["completions"] == conferencias, (
            "reconciliação re-executou a inferência")

        # tarefa sem artefacto confirmado: não pode ser concluída
        tid2 = amb.submeter("sem artefacto no grafo")
        reserva = amb._reservar_na_mao(tid2)
        assert reserva is not None and reserva["id"] == tid2
        proc2 = amb.cli("reconcile")
        estado2 = amb.estado(tid2)
        assert proc2.returncode == 1, (proc2.stdout, proc2.stderr)
        assert estado2["status"] == "RESERVED", estado2
        assert estado2["inference_response"] in ("", None), estado2
        assert amb.stats()["completions"] == conferencias
        amb.encerrar_workers()
    finally:
        amb.parar_servidor()
        amb.encerrar_workers()


# --------------------------------------------------------------------------- d)


def test_cancelamento_limitado_a_estados_permitidos(tmp_path):
    amb = _base(tmp_path)
    amb.arrancar_servidor()
    try:
        # QUEUED -> cancelável
        tid_queued = amb.submeter("cancelavel")
        proc = amb.cli("cancel", str(tid_queued))
        assert proc.returncode == 0, (proc.stdout, proc.stderr)
        assert amb.estado(tid_queued)["status"] == "CANCELLED"

        # RESERVED -> não cancelável
        tid_reserved = amb.submeter("em execucao")
        assert amb._reservar_na_mao(tid_reserved) is not None
        proc = amb.cli("cancel", str(tid_reserved))
        assert proc.returncode == 1, (proc.stdout, proc.stderr)
        assert amb.estado(tid_reserved)["status"] == "RESERVED"

        # COMPLETED -> não cancelável
        tid_done = amb.submeter("ja concluida")
        amb.arrancar_worker()
        estado = amb.aguardar(tid_done, {"COMPLETED", "FAILED"})
        assert estado["status"] == "COMPLETED", estado
        proc = amb.cli("cancel", str(tid_done))
        assert proc.returncode == 1, (proc.stdout, proc.stderr)
        assert amb.estado(tid_done)["status"] == "COMPLETED"
        amb.encerrar_workers()
    finally:
        amb.parar_servidor()
        amb.encerrar_workers()


# --------------------------------------------------------------------------- e)


def test_concorrencia_apenas_um_proprietario(tmp_path):
    amb = _base(tmp_path)
    amb.arrancar_servidor()
    try:
        tid = amb.submeter("tarefa disputada")
        w1 = amb.arrancar_worker()
        w2 = amb.arrancar_worker()
        estado = amb.aguardar(tid, {"COMPLETED", "FAILED"})
        assert estado["status"] == "COMPLETED", estado

        # ambos podem concluir o ciclo, mas apenas um executa a tarefa
        concluidas = 0
        for proc in (w1, w2):
            if proc.poll() is None:
                proc.send_signal(signal.SIGTERM)
        saidas = amb.encerrar_workers()
        for _codigo, err in saidas:
            concluidas += (err or "").count("[queue] tarefa")
        assert concluidas == 1, saidas
        assert amb.stats()["completions"] == 1, amb.stats()
    finally:
        amb.parar_servidor()
        amb.encerrar_workers()


# --------------------------------------------------------------------------- f)


def test_encerramento_do_trabalhador_de_teste_nao_afecta_producao(tmp_path):
    pid_antes = pid_worker_producao()
    amb = _base(tmp_path)
    amb.arrancar_servidor()
    try:
        tid = amb.submeter("ultimo ensaio")
        amb.arrancar_worker()
        amb.aguardar(tid, {"COMPLETED", "FAILED"})
        amb.encerrar_workers()

        assert all(not p.poll() for p in amb.workers), "teste deixou órfãos"
        assert pid_worker_producao() == pid_antes, "worker de produção mudou"

        chamadas = amb.chamadas_systemctl()
        for linha in chamadas:
            assert linha == f"is-active {UNIDADE_TESTE}", chamadas
        assert PROD_ROOT not in " ".join(chamadas)
        assert amb.root.exists() and amb.root != PROD_ROOT
        assert str(amb.root).startswith(str(amb.dir)), amb.root
    finally:
        amb.parar_servidor()
        amb.encerrar_workers()
        subprocess.run(["systemctl", "is-active", "pcsala-worker.service"],
                       capture_output=True, text=True, timeout=15)
