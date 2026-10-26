BEGIN IMMEDIATE;
CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE checkpoints (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    checkpoint_id TEXT NOT NULL UNIQUE,
    project_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('PREPARING', 'COMMITTED', 'NEEDS_RECOVERY')
    ),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    committed_at TEXT
);
CREATE INDEX checkpoints_scope
ON checkpoints(project_id, session_id, task_id, status, seq);
CREATE TABLE artifacts (
    artifact_id TEXT PRIMARY KEY,
    checkpoint_id TEXT NOT NULL REFERENCES checkpoints(checkpoint_id),
    relative_path TEXT NOT NULL UNIQUE,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0)
);
CREATE TABLE operations (
    operation_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    operation_type TEXT NOT NULL,
    target TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN (
            'NOT_STARTED', 'STARTED', 'COMPLETED', 'FAILED', 'INDETERMINATE'
        )
    ),
    result_reference TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT
);
INSERT INTO schema_migrations(version) VALUES (1);
COMMIT;
