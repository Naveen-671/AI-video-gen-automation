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
    """Executes schema DDL to create tables and database triggers."""
    if schema_path is None:
        schema_path = Path(__file__).parent / "schema.sql"
    
    with schema_path.open("r", encoding="utf-8") as f:
        ddl = f.read()

    conn = get_connection(db_path)
    try:
        conn.executescript(ddl)
        # Ensure default setting for global_pause
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('global_pause', 'false');"
        )
    finally:
        conn.close()
