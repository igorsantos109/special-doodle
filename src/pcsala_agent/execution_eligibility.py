from dataclasses import dataclass

from .execution_contract import ExecutionRequest, resolve_profile

class ExecutionNotEligible(RuntimeError):
    pass

@dataclass(frozen=True)
class EligibilityObservation:
    request: ExecutionRequest
    session_revision: int

def check_execution_eligibility(db, request: ExecutionRequest):
    """Consulta consistente. Nao reserva tentativa nem autoriza execucao futura."""
    checked = ExecutionRequest.model_validate(request)
    resolve_profile(checked)

    if db.in_transaction:
        raise ExecutionNotEligible(
            "Usar conexao sem transacao externa em curso"
        )

    db.execute("BEGIN")
    try:
        return _check_in_transaction(db, checked)
    finally:
        db.rollback()


def _check_in_transaction(db, checked):
    """Interno: exige transacao ja aberta; nao confirma nem desfaz."""
    if not db.in_transaction:
        raise ExecutionNotEligible("Transacao obrigatoria")
    row = db.execute(
        """SELECT s.state, s.revision, t.status, a.status
        FROM projects AS p
        JOIN sessions AS s ON s.project_id=p.project_id
        JOIN tasks AS t ON t.project_id=p.project_id
        JOIN attempts AS a
          ON a.project_id=p.project_id
         AND a.session_id=s.session_id
         AND a.task_id=t.task_id
        WHERE p.project_id=? AND s.session_id=?
          AND t.task_id=? AND a.attempt_id=?""",
        (
            checked.project_id, checked.session_id,
            checked.task_id, checked.attempt_id,
        ),
    ).fetchone()

    if row is None:
        raise ExecutionNotEligible(
            "Entidades ausentes ou vinculos divergentes"
        )

    state, revision, task_status, attempt_status = tuple(row)
    if state != "RUNNING":
        raise ExecutionNotEligible("Sessao nao permite iniciar execucao")
    if task_status != "RUNNING":
        raise ExecutionNotEligible("Tarefa nao esta RUNNING")
    if attempt_status != "RUNNING":
        raise ExecutionNotEligible("Tentativa nao esta RUNNING")

    pending = db.execute(
        """SELECT COUNT(*) FROM control_requests
        WHERE session_id=? AND status='REQUESTED'""",
        (checked.session_id,),
    ).fetchone()[0]
    if pending:
        raise ExecutionNotEligible("Pedido de controle pendente")

    return EligibilityObservation(checked, revision)
