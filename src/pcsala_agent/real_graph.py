import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Literal, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context

from .checkpoints import CheckpointStore, RecoveryRequired, new_id
from .context_budget import (
    BudgetCheck, PRIMARY_INPUT_BUDGET,
    check_budget, compress_context, ContextOverflow, CompressionError,
)
from .database import connect
from .inference_adapter import InferenceAdapter
from .inference_contract import InferenceRequest
from .inference_profiles import get_profile, PROFILES
from .locking import ExecutorBusy, database_lock
from .migrations import migrate


Step = Literal[
    "iniciado", "validado", "verificado_orcamento", "comprimido",
    "inferiu", "validado_resposta", "concluido", "falha",
]


class TriageState(TypedDict):
    project_id: str
    session_id: str
    task_id: str
    attempt_id: str
    step: Step
    inference_prompt: str
    inference_id: str
    inference_response: str
    inference_model: str
    inference_status: str
    error: str


def _session_state(db, project, session):
    row = db.execute(
        "SELECT state FROM sessions WHERE session_id=? AND project_id=?",
        (session, project),
    ).fetchone()
    return row["state"] if row else None


def _should_stop(db, project, session):
    state = _session_state(db, project, session)
    if state is None:
        return "Sessao inexistente"
    if state in ("STOPPED", "DRAINING", "CHECKPOINTING", "ERROR",
                  "RECOVERY_REQUIRED"):
        return f"Sessao em estado {state}"
    if state == "PAUSE_REQUESTED":
        pending = db.execute(
            """SELECT COUNT(*) FROM control_requests
            WHERE session_id=? AND status='REQUESTED'""",
            (session,),
        ).fetchone()[0]
        if pending:
            return "Pausa pendente"
    return ""


def _confirmed_artifact(store, project, session, task):
    checkpoint = store.latest(project, session, task)
    if checkpoint is None:
        return None
    rows = store.db.execute(
        "SELECT relative_path FROM artifacts WHERE checkpoint_id=?",
        (checkpoint["checkpoint_id"],),
    ).fetchall()
    if len(rows) != 1:
        raise RecoveryRequired("Manifesto de artefato invalido")
    return json.loads(
        (store.root / rows[0]["relative_path"]).read_bytes()
    )


def _write_artifact(store, project, session, task, data):
    content = json.dumps(data, ensure_ascii=False).encode("utf-8")
    cid = store.prepare(project, session, task)
    store.add_artifact(cid, content)
    store.commit(cid)
    return cid


def _build_update(state, **overrides):
    result = dict(state)
    for key, value in overrides.items():
        if value is not None:
            result[key] = value
    return TriageState(**result)


def execute(root, command, project, session, task, attempt, prompt,
            *, _urlopen=None, profile="cpu-triage-v1"):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    database = root / "state.sqlite"

    migrate(database)

    scope = (project, session, task, attempt)
    thread = hashlib.sha256(
        json.dumps(scope, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    config = {
        "configurable": {"thread_id": thread},
        "max_concurrency": 1,
    }

    with database_lock(database):
        db = connect(database, check_same_thread=False)
        graph_db = None
        try:
            store = CheckpointStore(db, root / "artifacts")

            blocked = db.execute(
                """SELECT COUNT(*) FROM checkpoints
                WHERE project_id=? AND session_id=?
                AND status='NEEDS_RECOVERY'""",
                (project, session),
            ).fetchone()[0]
            uncertain = db.execute(
                """SELECT COUNT(*) FROM operations
                WHERE project_id=? AND session_id=?
                AND status IN ('STARTED','INDETERMINATE')""",
                (project, session),
            ).fetchone()[0]
            if blocked or uncertain:
                raise RecoveryRequired("Sessao exige reconciliacao")

            # ---- node: validar_entrada ----
            def run_validar_entrada(state: TriageState):
                confirmed = _confirmed_artifact(store, project, session, task)
                if confirmed is not None and confirmed.get("step") in (
                    "concluido", "falha",
                ):
                    return _build_update(state, step="falha",
                        error="Estado terminal ja registrado")
                if confirmed is not None and confirmed.get("step") in (
                    "validado", "inferiu", "validado_resposta",
                ):
                    return state

                reason = _should_stop(db, project, session)
                if reason:
                    return _build_update(state, step="falha", error=reason)

                text = state.get("inference_prompt", "").strip()
                if not text:
                    return _build_update(state, step="falha",
                        error="Prompt vazio na entrada")

                _write_artifact(store, project, session, task, {
                    "step": "validado",
                    "scope": {
                        "project_id": project,
                        "session_id": session,
                        "task_id": task,
                        "attempt_id": attempt,
                    },
                    "inference_prompt": text,
                })
                return _build_update(state, step="validado")

            # ---- node: verificar_orcamento ----
            def run_verificar_orcamento(state: TriageState):
                confirmed = _confirmed_artifact(store, project, session, task)
                if confirmed is not None and confirmed.get("step") in (
                    "concluido", "falha",
                ):
                    return _build_update(state, step="falha",
                        error="Estado terminal ja registrado")
                if confirmed is not None and confirmed.get("step") in (
                    "verificado_orcamento", "comprimido",
                    "inferiu", "validado_resposta",
                ):
                    return state

                text = state.get("inference_prompt", "").strip()
                if not text:
                    return _build_update(state, step="falha",
                        error="Prompt vazio no orcamento")

                try:
                    budget = check_budget(text, budget=PRIMARY_INPUT_BUDGET,
                                          _urlopen=_urlopen)
                except Exception as exc:
                    return _build_update(state, step="verificado_orcamento",
                        error=f"Tokenizador indisponivel, seguindo sem compressao: {exc}")

                if not budget.over_budget:
                    _write_artifact(store, project, session, task, {
                        "step": "verificado_orcamento",
                        "scope": {
                            "project_id": project,
                            "session_id": session,
                            "task_id": task,
                            "attempt_id": attempt,
                        },
                        "input_tokens": budget.input_tokens,
                        "budget": budget.available_budget,
                    })
                    return _build_update(state, step="verificado_orcamento")

                try:
                    compressed = compress_context(text, _urlopen=_urlopen)
                except (ContextOverflow, CompressionError) as exc:
                    return _build_update(state, step="falha",
                        error=f"Compressao falhou: {exc}")
                except Exception as exc:
                    return _build_update(state, step="falha",
                        error=f"Erro na compressao: {exc}")

                _write_artifact(store, project, session, task, {
                    "step": "comprimido",
                    "scope": {
                        "project_id": project,
                        "session_id": session,
                        "task_id": task,
                        "attempt_id": attempt,
                    },
                    "input_tokens": budget.input_tokens,
                    "compressed_tokens": None,
                    "budget": budget.available_budget,
                })
                return _build_update(state, step="comprimido",
                    inference_prompt=compressed)

            # ---- node: triagem ----
            def run_triagem(state: TriageState):
                confirmed = _confirmed_artifact(store, project, session, task)
                if confirmed is not None and confirmed.get("step") in (
                    "concluido", "falha",
                ):
                    return _build_update(state,
                        step=confirmed["step"],
                        inference_id=confirmed.get("inference_id", ""),
                        inference_response=confirmed.get("inference_response", ""),
                        inference_model=confirmed.get("inference_model", ""),
                        inference_status=confirmed.get("inference_status", ""),
                        error=confirmed.get("error", ""),
                    )
                if confirmed is not None and confirmed.get("step") == "inferiu":
                    return _build_update(state, step="inferiu",
                        inference_id=confirmed.get("inference_id", ""),
                        inference_response=confirmed.get("inference_response", ""),
                        inference_model=confirmed.get("inference_model", ""),
                        inference_status=confirmed.get("inference_status", ""))

                reason = _should_stop(db, project, session)
                if reason:
                    return _build_update(state, step="falha", error=reason)

                inference_id = new_id()
                current_prompt = state.get("inference_prompt") or prompt
                input_hash = hashlib.sha256(
                    current_prompt.encode("utf-8")
                ).hexdigest()
                db.execute(
                    """INSERT INTO operations
                    (operation_id, project_id, session_id, task_id,
                     operation_type, target, input_hash, status)
                    VALUES (?, ?, ?, ?, 'INFERENCE', ?, ?, 'STARTED')""",
                    (inference_id, project, session, task,
                     attempt, input_hash),
                )
                db.commit()

                cfg = get_profile(profile)
                req = InferenceRequest(
                    project_id=project,
                    session_id=session,
                    task_id=task,
                    attempt_id=attempt,
                    profile=profile,
                    user_prompt=current_prompt,
                )
                adapter = InferenceAdapter(cfg)
                resp = adapter.query(req, _urlopen=_urlopen)

                reason = _should_stop(db, project, session)
                if reason:
                    db.execute(
                        """UPDATE operations SET status='INDETERMINATE'
                        WHERE operation_id=?""",
                        (inference_id,),
                    )
                    db.commit()
                    return _build_update(state, step="falha",
                        inference_id=inference_id,
                        inference_status="INDETERMINATE",
                        error=reason)

                if resp.status == "SUCCESS":
                    db.execute(
                        """UPDATE operations SET status='COMPLETED'
                        WHERE operation_id=?""",
                        (inference_id,),
                    )
                else:
                    db.execute(
                        """UPDATE operations SET status='FAILED'
                        WHERE operation_id=?""",
                        (inference_id,),
                    )
                db.commit()

                resp_text = resp.text if resp.status == "SUCCESS" else ""
                _write_artifact(store, project, session, task, {
                    "step": "inferiu",
                    "scope": {
                        "project_id": project,
                        "session_id": session,
                        "task_id": task,
                        "attempt_id": attempt,
                    },
                    "inference_id": inference_id,
                    "inference_status": resp.status,
                    "inference_model": resp.model if resp.status == "SUCCESS" else "",
                    "inference_response": resp_text,
                })
                return _build_update(state,
                    step="inferiu", inference_id=inference_id,
                    inference_response=resp_text,
                    inference_model=resp.model if resp.status == "SUCCESS" else "",
                    inference_status=resp.status,
                    error="" if resp.status == "SUCCESS" else resp.status)

            # ---- node: validar_resposta ----
            def run_validar_resposta(state: TriageState):
                confirmed = _confirmed_artifact(store, project, session, task)
                if confirmed is not None and confirmed.get("step") in (
                    "concluido", "falha",
                ):
                    return _build_update(state, step=confirmed["step"],
                        error=confirmed.get("error", ""))
                if confirmed is not None and \
                        confirmed.get("step") == "validado_resposta":
                    return state

                reason = _should_stop(db, project, session)
                if reason:
                    return _build_update(state, step="falha", error=reason)

                inf_status = state.get("inference_status", "")
                if inf_status != "SUCCESS":
                    return _build_update(state, step="falha",
                        error=f"Inferencia falhou: {inf_status}")

                resp_text = state.get("inference_response", "")
                if not resp_text.strip():
                    return _build_update(state, step="falha",
                        error="Resposta da inferencia vazia")

                _write_artifact(store, project, session, task, {
                    "step": "validado_resposta",
                    "scope": {
                        "project_id": project,
                        "session_id": session,
                        "task_id": task,
                        "attempt_id": attempt,
                    },
                    "response_length": len(resp_text),
                })
                return _build_update(state, step="validado_resposta")

            # ---- node: persistir ----
            def run_persist(state: TriageState):
                confirmed = _confirmed_artifact(store, project, session, task)
                if confirmed is not None and \
                        confirmed.get("step") in ("concluido", "falha"):
                    return state

                reason = _should_stop(db, project, session)
                if reason:
                    return state

                state_step = state.get("step", "")
                state_error = state.get("error", "")
                if state_step == "falha" or state_error:
                    final_step = "falha"
                    error = state_error or "Falha em etapa anterior"
                else:
                    final_step = "concluido"
                    error = ""

                _write_artifact(store, project, session, task, {
                    "step": final_step,
                    "scope": {
                        "project_id": project,
                        "session_id": session,
                        "task_id": task,
                        "attempt_id": attempt,
                    },
                    "inference_id": state.get("inference_id", ""),
                    "inference_status": state.get("inference_status", ""),
                    "inference_model": state.get("inference_model", ""),
                    "inference_response": state.get("inference_response", ""),
                    "error": error,
                })
                return state

            # ---- conditional routing ----
            def route_after_validacao(state: TriageState):
                if state.get("step") == "falha":
                    return "persistir"
                return "verificar_orcamento"

            def route_after_orcamento(state: TriageState):
                if state.get("step") == "falha":
                    return "persistir"
                return "triagem"

            def route_after_triagem(state: TriageState):
                if state.get("step") == "falha":
                    return "persistir"
                return "validar_resposta"

            def route_after_validacao_resposta(state: TriageState):
                return "persistir"

            # ---- build graph ----
            graph_db = connect(root / "langgraph.sqlite",
                               check_same_thread=False)
            saver = SqliteSaver(graph_db)
            builder = StateGraph(TriageState)
            builder.add_node("validar_entrada", run_validar_entrada)
            builder.add_node("verificar_orcamento", run_verificar_orcamento)
            builder.add_node("triagem", run_triagem)
            builder.add_node("validar_resposta", run_validar_resposta)
            builder.add_node("persistir", run_persist)
            builder.add_edge(START, "validar_entrada")
            builder.add_conditional_edges(
                "validar_entrada", route_after_validacao,
                {"verificar_orcamento": "verificar_orcamento",
                 "persistir": "persistir"},
            )
            builder.add_conditional_edges(
                "verificar_orcamento", route_after_orcamento,
                {"triagem": "triagem", "persistir": "persistir"},
            )
            builder.add_conditional_edges(
                "triagem", route_after_triagem,
                {"validar_resposta": "validar_resposta",
                 "persistir": "persistir"},
            )
            builder.add_edge("validar_resposta", "persistir")
            builder.add_edge("persistir", END)
            graph = builder.compile(checkpointer=saver)

            # ---- execute ----
            with tracing_context(enabled=False):
                snapshot = graph.get_state(config)
                confirmed = _confirmed_artifact(store, project, session, task)

                if command == "iniciar":
                    if snapshot.created_at is not None:
                        raise RecoveryRequired("Execucao ja iniciada")

                    initial = TriageState(
                        project_id=project,
                        session_id=session,
                        task_id=task,
                        attempt_id=attempt,
                        step="iniciado",
                        inference_prompt=prompt,
                        inference_id="",
                        inference_response="",
                        inference_model="",
                        inference_status="",
                        error="",
                    )
                    graph.invoke(
                        initial, config,
                        interrupt_before=[], durability="sync",
                    )
                else:  # retomar
                    if snapshot.created_at is None:
                        raise RecoveryRequired(
                            "Grafo ausente; nao reconstruir as cegas"
                        )
                    if confirmed is not None and confirmed.get("step") in (
                        "concluido", "falha",
                    ):
                        pass
                    else:
                        graph.invoke(None, config, durability="sync")

                confirmed = _confirmed_artifact(store, project, session, task)
                return {
                    "status": "CONCLUIDO" if confirmed else "EM_ANDAMENTO",
                    "step": (confirmed or {}).get("step", ""),
                    "inference_status": (
                        confirmed or {}).get("inference_status", ""),
                    "inference_id": (confirmed or {}).get("inference_id", ""),
                    "inference_model": (confirmed or {}).get(
                        "inference_model", ""),
                    "inference_response": (
                        confirmed or {}).get("inference_response", ""),
                    "error": (confirmed or {}).get("error", ""),
                }
        finally:
            if graph_db is not None:
                graph_db.close()
            db.close()


def main():
    parser = argparse.ArgumentParser(
        description="Grafo de triagem Bonsai CPU")
    parser.add_argument("command", choices=["iniciar", "retomar"])
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--project", required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--attempt", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--profile", default="cpu-triage-v1",
                        choices=list(PROFILES.keys()))
    args = parser.parse_args()
    try:
        result = execute(
            args.root, args.command,
            args.project, args.session, args.task,
            args.attempt, args.prompt,
            profile=args.profile,
        )
    except ExecutorBusy as error:
        print(str(error), file=sys.stderr)
        return 3
    except RecoveryRequired as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
