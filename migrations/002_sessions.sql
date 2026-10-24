BEGIN IMMEDIATE;

CREATE TABLE projects (
    project_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    authorized_root TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    state TEXT NOT NULL DEFAULT 'STOPPED' CHECK (
        state IN (
            'STOPPED', 'STARTING', 'READY', 'RUNNING',
            'PAUSE_REQUESTED', 'PAUSED', 'DRAINING', 'CHECKPOINTING',
            'ERROR', 'RECOVERY_REQUIRED'
        )
    ),
    api_mode TEXT NOT NULL DEFAULT 'OFFLINE' CHECK (
        api_mode IN ('OFFLINE', 'APPROVAL_REQUIRED', 'AUTONOMOUS_WITH_CAP')
    ),
    revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project_id, session_id)
);

CREATE TABLE tasks (
    task_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    title TEXT NOT NULL,
    acceptance_criteria TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        status IN ('PENDING', 'RUNNING', 'BLOCKED', 'REVIEW', 'VALIDATED')
    ),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project_id, task_id)
);

CREATE TABLE attempts (
    attempt_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PREPARED' CHECK (
        status IN (
            'PREPARED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'INDETERMINATE'
        )
    ),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    FOREIGN KEY(project_id, session_id)
        REFERENCES sessions(project_id, session_id),
    FOREIGN KEY(project_id, task_id)
        REFERENCES tasks(project_id, task_id)
);

CREATE TABLE control_requests (
    request_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    action TEXT NOT NULL CHECK(action IN ('PAUSE', 'DRAIN', 'RESUME')),
    status TEXT NOT NULL DEFAULT 'REQUESTED' CHECK (
        status IN ('REQUESTED', 'APPLIED', 'REJECTED')
    ),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT
);

CREATE TABLE audit_events (
    event_id TEXT PRIMARY KEY,
    session_id TEXT REFERENCES sessions(session_id),
    event_type TEXT NOT NULL,
    details_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX attempts_scope
ON attempts(project_id, session_id, task_id);

CREATE INDEX control_requests_pending
ON control_requests(session_id, status, created_at);

INSERT INTO schema_migrations(version) VALUES (2);
COMMIT;
