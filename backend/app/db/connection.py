"""SQLite connection manager supporting WAL mode and atomic BEGIN IMMEDIATE transactions."""

import sqlite3
from pathlib import Path
from contextlib import contextmanager
from typing import Generator
from backend.app.config import DB_PATH, DATA_DIR

def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Creates an SQLite connection configured with WAL mode and foreign keys enabled."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(db_path),
        timeout=10.0,
        isolation_level=None # Autocommit mode, explicit transaction control via BEGIN
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    return conn

@contextmanager
def db_transaction(db_path: Path = DB_PATH) -> Generator[sqlite3.Connection, None, None]:
    """Context manager for atomic BEGIN IMMEDIATE transactions (vital for single-worker leasing)."""
    conn = get_connection(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE;")
        yield conn
        conn.execute("COMMIT;")
    except Exception:
        conn.execute("ROLLBACK;")
        raise
    finally:
        conn.close()

def init_db(db_path: Path = DB_PATH, schema_path: Path = None):
    """Executes schema DDL to create tables and database triggers, with migration handling."""
    if schema_path is None:
        schema_path = Path(__file__).parent / "schema.sql"
    
    with schema_path.open("r", encoding="utf-8") as f:
        ddl = f.read()

    conn = get_connection(db_path)
    try:
        conn.executescript(ddl)
        
        # Check if project_id column exists on renders (migration check)
        columns = [col["name"] for col in conn.execute("PRAGMA table_info(renders);").fetchall()]
        if "project_id" not in columns:
            try:
                conn.execute("ALTER TABLE renders ADD COLUMN project_id TEXT;")
            except sqlite3.OperationalError:
                pass

        # Check if narration_voice column exists on projects (migration check)
        proj_cols = [col["name"] for col in conn.execute("PRAGMA table_info(projects);").fetchall()]
        if "narration_voice" not in proj_cols:
            try:
                conn.execute("ALTER TABLE projects ADD COLUMN narration_voice TEXT DEFAULT 'af_bella';")
            except sqlite3.OperationalError:
                pass
        if "narrative_archetype" not in proj_cols:
            try:
                conn.execute("ALTER TABLE projects ADD COLUMN narrative_archetype TEXT DEFAULT 'CURIOSITY_GAP';")
            except sqlite3.OperationalError:
                pass

        # Check if supporting_claim_ids column exists on project_scenes (migration check)
        scene_cols = [col["name"] for col in conn.execute("PRAGMA table_info(project_scenes);").fetchall()]
        if "supporting_claim_ids" not in scene_cols:
            try:
                conn.execute("ALTER TABLE project_scenes ADD COLUMN supporting_claim_ids TEXT DEFAULT '[]';")
            except sqlite3.OperationalError:
                pass
        if "motion_preset" not in scene_cols:
            try:
                conn.execute("ALTER TABLE project_scenes ADD COLUMN motion_preset TEXT DEFAULT 'zoom_in';")
            except sqlite3.OperationalError:
                pass
        if "asset_provenance_id" not in scene_cols:
            try:
                conn.execute("ALTER TABLE project_scenes ADD COLUMN asset_provenance_id TEXT;")
            except sqlite3.OperationalError:
                pass
        if "visual_source_type" not in scene_cols:
            try:
                conn.execute("ALTER TABLE project_scenes ADD COLUMN visual_source_type TEXT DEFAULT 'FLOW_REQUIRED';")
            except sqlite3.OperationalError:
                pass

        # Check if extended columns exist on asset_provenance (migration check)
        asset_cols = [col["name"] for col in conn.execute("PRAGMA table_info(asset_provenance);").fetchall()]
        extended_cols = {
            "source_asset_id": "TEXT",
            "source_page_url": "TEXT",
            "license_url": "TEXT",
            "media_type": "TEXT DEFAULT 'image'",
            "original_width": "INTEGER",
            "original_height": "INTEGER",
            "original_duration": "REAL",
            "file_size_bytes": "INTEGER",
            "rights_status": "TEXT DEFAULT 'VERIFIED_FREE'",
            "crop_transform": "TEXT",
            "selection_reason": "TEXT",
        }
        for col_name, col_def in extended_cols.items():
            if col_name not in asset_cols:
                try:
                    conn.execute(f"ALTER TABLE asset_provenance ADD COLUMN {col_name} {col_def};")
                except sqlite3.OperationalError:
                    pass

        # Ensure oauth_states table exists
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS oauth_states (
                state TEXT PRIMARY KEY,
                platform TEXT NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                used_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        # Ensure default setting for global_pause
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('global_pause', 'false');"
        )
    finally:
        conn.close()
