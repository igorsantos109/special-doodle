import hashlib
import json
import os
import sys
import urllib.request as urlrequest
from datetime import UTC, datetime

from .checkpoints import CheckpointStore
from .context_budget import count_tokens
from .database import connect
from .inference_adapter import InferenceAdapter
from .inference_contract import InferenceConfig, InferenceRequest

GRAPH_ENDPOINT = "http://127.0.0.1:8080"

# Slot save/restore (KV de documentos longos) esta DESATIVADO por default.
# So deve ser ativado (PCSALA_SLOT_SAVE_RESTORE=1) apos validar num slot
# descartavel se o MROPE aceita o restauro. Caso nao aceite, registrar no
# guia e manter desativado (ver GUIA_MESTRE).
SLOT_SAVE_RESTORE_ENABLED = os.environ.get("PCSALA_SLOT_SAVE_RESTORE", "0") == "1"


def _now():
    return datetime.now(UTC).isoformat(timespec="seconds")


def _thread_id(scope):
    return hashlib.sha256(json.dumps(scope, ensure_ascii=False).encode("utf-8")).hexdigest()


def _scope(project, session, task, attempt):
    return (project, session, task, attempt)


def _slot_action(endpoint, slot_id, action, _urlopen=None):
    """POST /slots/<id>?action=save|restore (KV de documentos longos).

    Somente efetivo quando SLOT_SAVE_RESTORE_ENABLED. Retorna None quando
    desativado ou quando o servidor nao esta disponivel.
    """
    if not SLOT_SAVE_RESTORE_ENABLED:
        return None
    if _urlopen is None:
        _urlopen = urlrequest.urlopen
    import urllib.error
    url = f"{endpoint.rstrip('/')}/slots/{slot_id}?action={action}"
    try:
        req = _urlopen(url)
        req.read()
        return True
    except (urllib.error.URLError, OSError):
        return False



def _has_indeterminate(db, project, session, task, attempt):
    row = db.execute(
        """SELECT 1 FROM operations
        WHERE project_id=? AND session_id=? AND task_id=?
        AND status='INDETERMINATE' LIMIT 1""",
        (project, session, task),
    ).fetchone()
    return row is not None


def _find_completed_inference(db, store, project, session, task):
    rows = db.execute(
        """SELECT checkpoint_id, created_at FROM checkpoints
        WHERE project_id=? AND session_id=? AND task_id=?
        AND status='COMMITTED' ORDER BY seq DESC""",
        (project, session, task),
    ).fetchall()
    for row in rows:
        artifacts = db.execute(
            "SELECT relative_path FROM artifacts WHERE checkpoint_id=?",
            (row["checkpoint_id"],),
        ).fetchall()
        for art in artifacts:
            try:
                data = json.loads((store.root / art["relative_path"]).read_bytes())
            except Exception:
                continue
            if data.get("step") == "concluir" and data.get("inference_response"):
                return data
    return None

def execute(env, command, project, session, task, attempt, prompt,
            _urlopen=None, profile="gpu-triage-v1", _skip_health_check=False,
            _document_slot=None):
    if _urlopen is None:
        _urlopen = urlrequest.urlopen
    db_path = env / "state.sqlite"
    db = connect(db_path)
    try:
        sess = db.execute(
            "SELECT state, revision FROM sessions WHERE session_id=?",
            (session,),
        ).fetchone()
        if sess is None or sess["state"] != "RUNNING":
            return {
                "status": "EM_ANDAMENTO",
                "inference_status": "PENDING",
                "inference_response": "",
                "error": "",
                "step": "sessao_nao_running",
            }

        if _has_indeterminate(db, project, session, task, attempt):
            raise RuntimeError("reconciliacao pendente")

        scope = _scope(project, session, task, attempt)
        thread_id = _thread_id(scope)
        store = CheckpointStore(db, env / "artifacts")

        if not prompt or not prompt.strip():
            cid = _commit_step(store, db, project, session, task, attempt, thread_id,
                               profile, "validar_entrada", prompt, "", "vazio")
            _record_operation(db, project, session, task, "INFERENCE", prompt,
                              "FAILED", None)
            db.execute(
                "UPDATE attempts SET status='FAILED', completed_at=? WHERE attempt_id=?",
                (_now(), attempt),
            )
            db.commit()
            return {
                "status": "CONCLUIDO",
                "inference_status": "SKIPPED",
                "inference_response": "",
                "error": "prompt vazio",
                "step": "falha",
                "checkpoint_id": cid,
            }

        existing = _find_completed_inference(db, store, project, session, task)
        if existing:
            if command == "iniciar":
                raise RuntimeError("execucao ja concluida; use retomar")
            target_ref = existing.get("checkpoint_id") or existing.get("artifact")
            _record_operation(db, project, session, task, "INFERENCE", prompt,
                              "COMPLETED", target_ref)
            return {
                "status": "CONCLUIDO",
                "inference_status": "SUCCESS",
                "inference_response": existing["inference_response"],
                "inference_model": existing.get("model", ""),
                "error": "",
                "step": "retomado",
                "checkpoint_id": existing["checkpoint_id"],
            }

        _commit_step(store, db, project, session, task, attempt, thread_id,
                     profile, "validar_entrada", prompt, "", "ok")

        profile_cfg = _profile_config(profile)
        adapter = InferenceAdapter(profile_cfg)
        req = InferenceRequest(
            project_id=project, session_id=session, task_id=task,
            attempt_id=attempt, profile=profile, user_prompt=prompt,
        )
        _record_operation(db, project, session, task, "INFERENCE", prompt, "STARTED", None)

        if _document_slot:
            _slot_action(GRAPH_ENDPOINT, _document_slot, "save",
                         _urlopen=_urlopen)

        try:
            count_tokens(prompt, _urlopen=_urlopen)
        except Exception:
            pass
        resp = adapter.query(req, _urlopen=_urlopen)

        if resp.status != "SUCCESS":
            if _document_slot:
                _slot_action(GRAPH_ENDPOINT, _document_slot, "restore",
                             _urlopen=_urlopen)
            _record_operation(db, project, session, task, "INFERENCE", prompt,
                              "FAILED", None)
            db.execute(
                "UPDATE attempts SET status='FAILED', completed_at=? WHERE attempt_id=?",
                (_now(), attempt),
            )
            db.commit()
            return {
                "status": "CONCLUIDO",
                "inference_status": resp.status,
                "inference_response": "",
                "error": "inferencia falhou",
                "step": "inferencia",
            }

        if not resp.text.strip():
            _commit_step(store, db, project, session, task, attempt, thread_id,
                         profile, "inferiu", prompt, resp.text, "ok")
            _record_operation(db, project, session, task, "INFERENCE", prompt,
                              "COMPLETED", None)
            db.execute(
                "UPDATE attempts SET status='FAILED', completed_at=? WHERE attempt_id=?",
                (_now(), attempt),
            )
            db.commit()
            return {
                "status": "CONCLUIDO",
                "step": "falha",
                "error": "resposta vazia",
                "inference_status": "INVALID_RESPONSE",
                "inference_response": "",
            }

        _commit_step(store, db, project, session, task, attempt, thread_id,
                     profile, "inferiu", prompt, resp.text, "ok")
        _commit_step(store, db, project, session, task, attempt, thread_id,
                     profile, "validar_resposta", resp.text, resp.text, "ok")
        artifact = _commit_step(store, db, project, session, task, attempt,
                                thread_id, profile, "concluir", resp.text, resp.text, "ok")
        _record_operation(db, project, session, task, "INFERENCE", prompt,
                          "COMPLETED", artifact)
        db.execute(
            "UPDATE attempts SET status='SUCCEEDED', completed_at=? WHERE attempt_id=?",
            (_now(), attempt),
        )
        if _document_slot:
            _slot_action(GRAPH_ENDPOINT, _document_slot, "restore",
                         _urlopen=_urlopen)
        db.commit()
        return {
            "status": "CONCLUIDO",
            "inference_status": "SUCCESS",
            "inference_response": resp.text,
            "inference_model": resp.model,
            "inference_id": _thread_id(scope),
            "error": "",
            "step": "concluido",
            "checkpoint_id": artifact,
        }
    finally:
        db.close()


def _tokenize_resp(_urlopen, *args, **kwargs):
    request = args[0] if args else kwargs.get("req")
    body = json.dumps({"tokens": [1, 2, 3]}).encode("utf-8")

    class _R:
        status = 200
        def read(self, *a):
            return body
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass
    return _R()


def _profile_config(profile):
    from .inference_profiles import get_profile
    return InferenceConfig(
        endpoint=get_profile(profile).endpoint,
        model=get_profile(profile).model,
        timeout_seconds=get_profile(profile).timeout_seconds,
        max_response_bytes=get_profile(profile).max_response_bytes,
        api_key_env=get_profile(profile).api_key_env,
    )


def _record_operation(db, project, session, task, operation_type, target, status, result_reference):
    operation_id = hashlib.sha256(
        f"{project}/{session}/{task}/{operation_type}".encode()
    ).hexdigest()
    input_hash = hashlib.sha256(str(target).encode("utf-8")).hexdigest()
    completed_at = _now() if status in ("COMPLETED", "FAILED") else None
    with db:
        db.execute(
            """INSERT INTO operations
            (operation_id, project_id, session_id, task_id, operation_type,
            target, input_hash, status, result_reference, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(operation_id) DO UPDATE SET
            status=excluded.status,
            result_reference=excluded.result_reference,
            completed_at=excluded.completed_at,
            target=excluded.target""",
            (operation_id, project, session, task, operation_type, target,
             input_hash, status, result_reference, completed_at),
        )


def _commit_step(store, db, project, session, task, attempt, thread_id, profile,
                 step, prompt, response, result_tag):
    cid = store.prepare(project, session, task)
    data = {
        "scope": {"project_id": project, "session_id": session,
                  "task_id": task, "attempt_id": attempt},
        "step": step,
        "thread_id": thread_id,
        "profile": profile,
        "prompt": prompt,
        "inference_response": response,
        "model": _profile_config(profile).model,
        "result": result_tag,
        "checkpoint_id": cid,
    }
    path = store.add_artifact(cid, json.dumps(data).encode("utf-8"))
    store.commit(cid)
    return cid


def main():
    import argparse
    parser = argparse.ArgumentParser(
        prog="pcsala-agent-worker", description="Bonsai worker LangGraph (triagem)",
    )
    parser.add_argument("command", choices=["iniciar", "retomar"])
    parser.add_argument("--root", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--attempt", required=True)
    parser.add_argument("--prompt", default="")
    parser.add_argument("--profile", default="gpu-triage-v1")
    args = parser.parse_args()
    env = Path(args.root)
    result = execute(
        env, args.command, args.project, args.session, args.task,
        args.attempt, args.prompt, profile=args.profile,
    )
    print(json.dumps(result))
    sys.exit(0)


if __name__ == "__main__":
    main()
