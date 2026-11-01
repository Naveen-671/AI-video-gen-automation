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

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    topic TEXT NOT NULL,
    target_audience TEXT NOT NULL DEFAULT 'General',
    language TEXT NOT NULL DEFAULT 'en',
    target_duration REAL NOT NULL DEFAULT 15.0,
    content_format TEXT NOT NULL DEFAULT 'explainer',
    narrative_archetype TEXT DEFAULT 'CURIOSITY_GAP',
    narration_mode TEXT NOT NULL DEFAULT 'silent', -- 'silent', 'manual_audio', or 'local_tts'
    narration_voice TEXT DEFAULT 'af_bella',
    narration_audio_path TEXT,
    status TEXT NOT NULL DEFAULT 'IDEA',
    current_render_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(current_render_id) REFERENCES renders(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS project_scenes (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    scene_index INTEGER NOT NULL,
    scene_title TEXT NOT NULL,
    narration_text TEXT NOT NULL,
    caption_text TEXT NOT NULL,
    duration_seconds REAL NOT NULL DEFAULT 5.0,
    visual_asset_path TEXT,
    motion_preset TEXT DEFAULT 'zoom_in', -- 'zoom_in', 'zoom_out', 'pan_left', 'pan_right', 'tilt_up', 'tilt_down', 'static'
    visual_source_type TEXT DEFAULT 'FLOW_REQUIRED', -- 'FLOW_REQUIRED', 'USER_UPLOAD', 'CURATED_STOCK', 'EXPLICIT_FALLBACK'
    asset_provenance_id TEXT,
    supporting_claim_ids TEXT DEFAULT '[]',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
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
    project_id TEXT,
    localized_variant_id TEXT,
    render_checksum TEXT NOT NULL UNIQUE,
    recipe_json TEXT NOT NULL,
    file_path TEXT,
    qa_status TEXT DEFAULT 'PENDING',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL,
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

CREATE TABLE IF NOT EXISTS fact_sources (
    id TEXT PRIMARY KEY,
    project_id TEXT,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    published_date TEXT,
    retrieved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    raw_excerpt TEXT,
    http_status INTEGER DEFAULT 200,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS fact_claims (
    id TEXT PRIMARY KEY,
    source_id TEXT,
    project_id TEXT,
    claim_text TEXT NOT NULL,
    quote_excerpt TEXT NOT NULL,
    evidence_status TEXT NOT NULL DEFAULT 'UNVERIFIED', -- 'VERIFIED', 'UNVERIFIED', 'INSUFFICIENT_EVIDENCE'
    uncertainty_rationale TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(source_id) REFERENCES fact_sources(id) ON DELETE SET NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS script_proposals (
    id TEXT PRIMARY KEY,
    project_id TEXT,
    topic TEXT NOT NULL,
    target_audience TEXT NOT NULL,
    narrative_archetype TEXT NOT NULL,
    hook_text TEXT NOT NULL,
    scenes_json TEXT NOT NULL,
    validation_json TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS asset_provenance (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    scene_index INTEGER NOT NULL,
    asset_type TEXT NOT NULL, -- 'USER_UPLOAD', 'WIKIMEDIA', 'NASA', 'PROCEDURAL', 'FALLBACK'
    source_url TEXT,
    author TEXT,
    license TEXT,
    attribution_text TEXT,
    local_path TEXT NOT NULL,
    sha256_checksum TEXT NOT NULL,
    associated_claim_id TEXT,
    source_asset_id TEXT,
    source_page_url TEXT,
    license_url TEXT,
    media_type TEXT DEFAULT 'image', -- 'image', 'video'
    original_width INTEGER,
    original_height INTEGER,
    original_duration REAL,
    file_size_bytes INTEGER,
    rights_status TEXT DEFAULT 'VERIFIED_FREE', -- 'VERIFIED_FREE', 'PUBLIC_DOMAIN', 'RESTRICTED', 'UNVERIFIED'
    crop_transform TEXT,
    selection_reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY(associated_claim_id) REFERENCES fact_claims(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS editorial_reviews (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    render_id TEXT,
    overall_status TEXT NOT NULL, -- 'PASSED', 'WARNING', 'FAILED'
    score INTEGER NOT NULL DEFAULT 100,
    hook_evaluation_json TEXT NOT NULL,
    pacing_evaluation_json TEXT NOT NULL,
    relevance_evaluation_json TEXT NOT NULL,
    audio_evaluation_json TEXT NOT NULL,
    warnings_json TEXT NOT NULL DEFAULT '[]',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY(render_id) REFERENCES renders(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    entity_id TEXT,
    details_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS oauth_states (
    state TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    used_at TIMESTAMP,
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
