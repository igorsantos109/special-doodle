import json
import secrets
from datetime import UTC, datetime

from .execution_eligibility import (
    check_execution_eligibility,
)


class ExecutionAlreadyAccepted(Exception):
    pass


def _now():
    return datetime.now(UTC).isoformat(timespec="seconds")


def accept_execution(db, request):
    observation = check_execution_eligibility(db, request)
    request_json = request.model_dump_json()
    revision = observation.session_revision
    execution_id = secrets.token_hex(8)
    existente = db.execute(
        "SELECT 1 FROM execution_acceptances WHERE attempt_id=?",
        (request.attempt_id,),
    ).fetchone()
    if existente is not None:
        raise ExecutionAlreadyAccepted("execucao ja aceita")
    with db:
        db.execute(
            """INSERT INTO execution_acceptances
            (execution_id, attempt_id, request_json, session_revision)
            VALUES (?, ?, ?, ?)""",
            (execution_id, request.attempt_id, request_json, revision),
        )
        db.execute(
            """INSERT INTO audit_events
            (event_id, session_id, event_type, details_json)
            VALUES (?, ?, 'EXECUTION_ACCEPTED', ?)""",
            (
                secrets.token_hex(8),
                request.session_id,
                json.dumps({
                    "execution_id": execution_id,
                    "attempt_id": request.attempt_id,
                    "session_revision": revision,
                }),
            ),
        )
    return AcceptedExecution(
        execution_id=execution_id,
        attempt_id=request.attempt_id,
        session_revision=revision,
    )


class AcceptedExecution:
    def __init__(self, execution_id, attempt_id, session_revision):
        self.execution_id = execution_id
        self.attempt_id = attempt_id
        self.session_revision = session_revision
