BEGIN IMMEDIATE;

CREATE TABLE execution_acceptances (
    execution_id TEXT PRIMARY KEY NOT NULL,
    attempt_id TEXT NOT NULL UNIQUE REFERENCES attempts(attempt_id),
    request_json TEXT NOT NULL,
    session_revision INTEGER NOT NULL CHECK(session_revision >= 0),
    status TEXT NOT NULL DEFAULT 'ACCEPTED' CHECK(status='ACCEPTED'),
    accepted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO schema_migrations(version) VALUES (3);
COMMIT;
