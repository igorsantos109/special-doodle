from pydantic import BaseModel, ConfigDict


class ExecutionNotEligible(Exception):
    pass


class ExecutionObservation(BaseModel):
    model_config = ConfigDict(frozen=True)
    request: object
    session_revision: int
    reason: str = ""


def check_execution_eligibility(db, request):
    if db.in_transaction:
        raise ExecutionNotEligible("transacao externa em andamento")
    row = db.execute(
        """SELECT project_id, session_id, task_id, attempt_id, revision
        FROM attempts
        JOIN sessions USING (project_id, session_id)
        JOIN tasks USING (project_id, task_id)
        WHERE attempts.attempt_id = ?""",
        (request.attempt_id,),
    ).fetchone()
    if row is None:
        raise ExecutionNotEligible("tentativa inexistente")
    if (
        row["project_id"] != request.project_id
        or row["session_id"] != request.session_id
        or row["task_id"] != request.task_id
    ):
        raise ExecutionNotEligible("escopo divergente")
    session = db.execute(
        "SELECT state, revision FROM sessions WHERE session_id=?",
        (request.session_id,),
    ).fetchone()
    if session is None:
        raise ExecutionNotEligible("sessao inexistente")
    if session["state"] != "RUNNING":
        raise ExecutionNotEligible("sessao nao RUNNING")
    task = db.execute(
        "SELECT status FROM tasks WHERE task_id=?",
        (request.task_id,),
    ).fetchone()
    if task is None:
        raise ExecutionNotEligible("tarefa inexistente")
    if task["status"] != "RUNNING":
        raise ExecutionNotEligible("tarefa nao RUNNING")
    attempt = db.execute(
        "SELECT status FROM attempts WHERE attempt_id=?",
        (request.attempt_id,),
    ).fetchone()
    if attempt is None:
        raise ExecutionNotEligible("tentativa inexistente")
    if attempt["status"] != "RUNNING":
        raise ExecutionNotEligible("tentativa nao RUNNING")
    pending = db.execute(
        """SELECT 1 FROM control_requests
        WHERE session_id=? AND status='REQUESTED' LIMIT 1""",
        (request.session_id,),
    ).fetchone()
    if pending is not None:
        raise ExecutionNotEligible("controle pendente")
    return ExecutionObservation(
        request=request, session_revision=session["revision"]
    )
