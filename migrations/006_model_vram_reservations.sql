BEGIN IMMEDIATE;

CREATE TABLE model_vram (
    model_id TEXT NOT NULL,
    context_size INTEGER NOT NULL,
    vram_used_mb INTEGER NOT NULL,
    measured_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
    PRIMARY KEY (model_id, context_size)
);

CREATE INDEX model_vram_model ON model_vram(model_id);

CREATE TABLE model_reservations (
    reservation_id TEXT PRIMARY KEY,
    model_id TEXT NOT NULL,
    requester TEXT NOT NULL DEFAULT 'system',
    exclusive_group TEXT,
    reserved_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
    released_at TEXT,
    cuda_visible_devices TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (
        status IN ('active', 'released')
    )
);

CREATE INDEX model_reservations_model ON model_reservations(model_id, status);

INSERT INTO schema_migrations(version) VALUES (6);
COMMIT;
