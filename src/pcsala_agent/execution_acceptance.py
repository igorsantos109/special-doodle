import json
from dataclasses import dataclass
from uuid import uuid4

from .execution_contract import ExecutionRequest, resolve_profile
from .execution_eligibility import (
    ExecutionNotEligible, _check_in_transaction,
)

class ExecutionAlreadyAccepted(ExecutionNotEligible):
    pass

@dataclass(frozen=True)
class ExecutionAcceptance:
    execution_id: str
    attempt_id: str
    session_revision: int

def accept_execution(db, request: ExecutionRequest) -> ExecutionAcceptance:
    """Aceitacao persistente somente. Nao inicia processo nem permite replay."""
    checked = ExecutionRequest.model_validate(request)
    resolve_profile(checked)
    if db.in_transaction:
        raise ExecutionNotEligible("Transacao externa em curso")

    db.execute("BEGIN IMMEDIATE")
    try:
        observation = _check_in_transaction(db, checked)
        previous = db.execute(
            "SELECT execution_id FROM execution_acceptances WHERE attempt_id=?",
            (checked.attempt_id,),
        ).fetchone()
        if previous is not None:
            raise ExecutionAlreadyAccepted("Tentativa ja possui aceitacao")

        execution_id = str(uuid4())
        db.execute(
            """INSERT INTO execution_acceptances
            (execution_id,attempt_id,request_json,session_revision)
            VALUES (?,?,?,?)""",
            (
                execution_id, checked.attempt_id,
                checked.model_dump_json(), observation.session_revision,
            ),
        )
        db.execute(
            """INSERT INTO audit_events
            (event_id,session_id,event_type,details_json)
            VALUES (?,?,'EXECUTION_ACCEPTED',?)""",
            (
                str(uuid4()), checked.session_id,
                json.dumps({
                    "execution_id": execution_id,
                    "attempt_id": checked.attempt_id,
                    "session_revision": observation.session_revision,
                }),
            ),
        )
        db.commit()
        return ExecutionAcceptance(
            execution_id, checked.attempt_id, observation.session_revision
        )
    except BaseException:
        db.rollback()
        raise
