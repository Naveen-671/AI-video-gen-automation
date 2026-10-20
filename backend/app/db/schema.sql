-- AI Shorts & Reels Factory: SQLite Core DDL & Triggers

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS channels (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    platform TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ideas (
    id TEXT PRIMARY KEY,
    channel_id TEXT,
    topic TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'IDEA',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(channel_id) REFERENCES channels(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS master_scripts (
    id TEXT PRIMARY KEY,
    idea_id TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(idea_id) REFERENCES ideas(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS localized_variants (
    id TEXT PRIMARY KEY,
    master_script_id TEXT,
    language TEXT NOT NULL,
    content TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(master_script_id) REFERENCES master_scripts(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS renders (
    id TEXT PRIMARY KEY,
    localized_variant_id TEXT,
    render_checksum TEXT NOT NULL UNIQUE,
    recipe_json TEXT NOT NULL,
    file_path TEXT,
    qa_status TEXT DEFAULT 'PENDING',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(localized_variant_id) REFERENCES localized_variants(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    render_id TEXT NOT NULL,
    render_checksum TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    status TEXT NOT NULL, -- 'APPROVED' or 'REJECTED'
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    superseded_at TIMESTAMP,
    FOREIGN KEY(render_id) REFERENCES renders(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS publish_attempts (
    id TEXT PRIMARY KEY,
    approval_id TEXT NOT NULL,
    render_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    target_channel_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    idempotency_key TEXT NOT NULL UNIQUE,
    external_id TEXT,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(approval_id) REFERENCES approvals(id) ON DELETE CASCADE,
    FOREIGN KEY(render_id) REFERENCES renders(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    stage TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'QUEUED',
    lease_token TEXT,
    lease_expires_at TIMESTAMP,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    entity_id TEXT,
    details_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- CRITICAL PRODUCTION GUARDRAIL TRIGGER
-- Prohibits inserting any publish_attempt without an active, non-superseded approval matching the exact render checksum
CREATE TRIGGER IF NOT EXISTS enforce_valid_approval_before_publish
BEFORE INSERT ON publish_attempts
FOR EACH ROW
BEGIN
    SELECT CASE
        WHEN NOT EXISTS (
            SELECT 1 FROM approvals a
            JOIN renders r ON a.render_id = r.id
            WHERE a.id = NEW.approval_id
              AND a.render_id = NEW.render_id
              AND a.render_checksum = r.render_checksum
              AND a.status = 'APPROVED'
              AND a.superseded_at IS NULL
        )
        THEN RAISE(ABORT, 'Publish attempt rejected: Valid non-superseded approval matching render checksum required.')
    END;
END;
