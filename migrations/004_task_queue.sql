BEGIN IMMEDIATE;

CREATE TABLE task_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    idempotency_key TEXT UNIQUE,
    profile TEXT NOT NULL DEFAULT 'gpu-triage-v1',
    prompt TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'QUEUED' CHECK (
        status IN ('QUEUED', 'RESERVED', 'COMPLETED', 'FAILED', 'CANCELLED')
    ),
    attempt_id TEXT NOT NULL DEFAULT (lower(hex(randomblob(16)))),
    inference_response TEXT,
    inference_id TEXT,
    inference_model TEXT,
    inference_status TEXT,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
    reserved_at TEXT,
    completed_at TEXT
);

CREATE INDEX task_queue_status ON task_queue(status, id);

INSERT INTO schema_migrations(version) VALUES (4);
COMMIT;