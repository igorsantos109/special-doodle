BEGIN IMMEDIATE;

CREATE TABLE model_operations (
    operation_id TEXT PRIMARY KEY,
    idempotency_key TEXT,
    requester TEXT NOT NULL DEFAULT 'system',
    session_id TEXT,
    task_id TEXT,
    attempt_id TEXT,
    action TEXT NOT NULL CHECK (action IN ('start', 'stop', 'switch', 'health')),
    target_model_id TEXT NOT NULL,
    previous_status TEXT,
    requested_status TEXT,
    confirmed_status TEXT,
    authorization_used TEXT,
    status TEXT NOT NULL DEFAULT 'REQUESTED' CHECK (
        status IN ('REQUESTED', 'APPROVED', 'IN_PROGRESS', 'COMPLETED', 'FAILED', 'REJECTED', 'BUSY')
    ),
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);

CREATE INDEX model_operations_target ON model_operations(target_model_id, status);
CREATE INDEX model_operations_requester ON model_operations(requester);

INSERT INTO schema_migrations(version) VALUES (5);
COMMIT;