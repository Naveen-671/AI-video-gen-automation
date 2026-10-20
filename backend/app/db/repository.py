"""Database repository operations for jobs, renders, approvals, and settings."""

import json
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from pathlib import Path

from backend.app.config import DB_PATH
from backend.app.db.connection import get_connection, db_transaction
from backend.app.domain.state_machines import JobState

def is_global_paused(db_path: Path = DB_PATH) -> bool:
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT value FROM settings WHERE key = 'global_pause'").fetchone()
        return (row["value"].lower() == "true") if row else False
    finally:
        conn.close()

def set_global_pause(paused: bool, db_path: Path = DB_PATH) -> bool:
    conn = get_connection(db_path)
    try:
        val = "true" if paused else "false"
        conn.execute(
            """
            INSERT INTO settings (key, value, updated_at) 
            VALUES ('global_pause', ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
            """,
            (val,)
        )
        record_audit("GLOBAL_PAUSE_TOGGLED", "system", {"paused": paused}, db_path=db_path)
        return paused
    finally:
        conn.close()

def create_job(stage: str, payload: dict, idempotency_key: str, max_attempts: int = 3, db_path: Path = DB_PATH) -> str:
    """Inserts a new job or returns existing ID if idempotency key matches."""
    job_id = str(uuid.uuid4())
    conn = get_connection(db_path)
    try:
        existing = conn.execute("SELECT id FROM jobs WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
        if existing:
            return existing["id"]
        
        conn.execute(
            """
            INSERT INTO jobs (id, stage, payload_json, idempotency_key, status, max_attempts)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (job_id, stage, json.dumps(payload), idempotency_key, JobState.QUEUED.value, max_attempts)
        )
        record_audit("JOB_CREATED", job_id, {"stage": stage, "idempotency_key": idempotency_key}, db_path=db_path)
        return job_id
    finally:
        conn.close()

def lease_next_job(worker_token: str, lease_duration_seconds: int = 60, db_path: Path = DB_PATH) -> Optional[Dict[str, Any]]:
    """Atomically leases the next available job using BEGIN IMMEDIATE."""
    if is_global_paused(db_path):
        return None

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=lease_duration_seconds)
    now_iso = now.isoformat()
    expires_iso = expires_at.isoformat()

    with db_transaction(db_path) as conn:
        # Reclaim any expired leases first
        conn.execute(
            """
            UPDATE jobs 
            SET status = 'QUEUED', lease_token = NULL, lease_expires_at = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE status = 'LEASED' AND lease_expires_at < ?
            """,
            (now_iso,)
        )

        # Select the oldest queued job
        job = conn.execute(
            """
            SELECT id, stage, payload_json, attempts, max_attempts, idempotency_key
            FROM jobs
            WHERE status = 'QUEUED'
            ORDER BY created_at ASC
            LIMIT 1
            """
        ).fetchone()

        if not job:
            return None

        job_id = job["id"]
        new_attempts = job["attempts"] + 1

        # Atomically lease
        conn.execute(
            """
            UPDATE jobs
            SET status = 'LEASED', lease_token = ?, lease_expires_at = ?, attempts = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'QUEUED'
            """,
            (worker_token, expires_iso, new_attempts, job_id)
        )

        return {
            "id": job_id,
            "stage": job["stage"],
            "payload": json.loads(job["payload_json"]),
            "attempts": new_attempts,
            "max_attempts": job["max_attempts"],
            "idempotency_key": job["idempotency_key"],
            "lease_token": worker_token,
            "lease_expires_at": expires_iso
        }

def heartbeat_job(job_id: str, worker_token: str, extension_seconds: int = 60, db_path: Path = DB_PATH) -> bool:
    """Extends the lease duration for an actively leased job."""
    new_expires_iso = (datetime.now(timezone.utc) + timedelta(seconds=extension_seconds)).isoformat()
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            """
            UPDATE jobs
            SET lease_expires_at = ?, status = 'RUNNING', updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND lease_token = ? AND status IN ('LEASED', 'RUNNING')
            """,
            (new_expires_iso, job_id, worker_token)
        )
        return cursor.rowcount > 0
    finally:
        conn.close()

def complete_job(job_id: str, worker_token: str, db_path: Path = DB_PATH) -> bool:
    """Marks a leased job as SUCCEEDED and clears the lease token."""
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            """
            UPDATE jobs
            SET status = 'SUCCEEDED', lease_token = NULL, lease_expires_at = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND lease_token = ?
            """,
            (job_id, worker_token)
        )
        if cursor.rowcount > 0:
            record_audit("JOB_SUCCEEDED", job_id, {}, db_path=db_path)
            return True
        return False
    finally:
        conn.close()

def fail_job(job_id: str, worker_token: str, error_msg: str, retryable: bool = True, db_path: Path = DB_PATH) -> bool:
    """Handles job failure: either re-queues if attempts < max_attempts or marks permanent failure."""
    conn = get_connection(db_path)
    try:
        job = conn.execute("SELECT attempts, max_attempts FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not job:
            return False

        if retryable and job["attempts"] < job["max_attempts"]:
            new_status = JobState.QUEUED.value
        else:
            new_status = JobState.FAILED_PERMANENT.value

        cursor = conn.execute(
            """
            UPDATE jobs
            SET status = ?, lease_token = NULL, lease_expires_at = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND lease_token = ?
            """,
            (new_status, job_id, worker_token)
        )
        record_audit("JOB_FAILED", job_id, {"error": error_msg, "status": new_status}, db_path=db_path)
        return cursor.rowcount > 0
    finally:
        conn.close()

def list_jobs(limit: int = 50, db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT id, stage, status, attempts, max_attempts, idempotency_key, lease_expires_at, created_at, updated_at
            FROM jobs
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,)
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()

# Renders & Approvals

def create_render(render_id: str, checksum: str, recipe_json: str, variant_id: Optional[str] = None, file_path: Optional[str] = None, db_path: Path = DB_PATH) -> str:
    conn = get_connection(db_path)
    try:
        conn.execute(
            """
            INSERT INTO renders (id, localized_variant_id, render_checksum, recipe_json, file_path, qa_status)
            VALUES (?, ?, ?, ?, ?, 'PASSED')
            """,
            (render_id, variant_id, checksum, recipe_json, file_path)
        )
        record_audit("RENDER_CREATED", render_id, {"checksum": checksum}, db_path=db_path)
        return render_id
    finally:
        conn.close()

def create_approval(approval_id: str, render_id: str, checksum: str, reviewer: str = "human_operator", status: str = "APPROVED", notes: Optional[str] = None, db_path: Path = DB_PATH) -> str:
    conn = get_connection(db_path)
    try:
        conn.execute(
            """
            INSERT INTO approvals (id, render_id, render_checksum, reviewer, status, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (approval_id, render_id, checksum, reviewer, status, notes)
        )
        record_audit("APPROVAL_RECORDED", approval_id, {"render_id": render_id, "status": status, "checksum": checksum}, db_path=db_path)
        return approval_id
    finally:
        conn.close()

def supersede_approval_for_render(render_id: str, db_path: Path = DB_PATH) -> int:
    """Invalidates existing approvals for a render when an edit occurs."""
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            """
            UPDATE approvals
            SET superseded_at = CURRENT_TIMESTAMP
            WHERE render_id = ? AND superseded_at IS NULL
            """,
            (render_id,)
        )
        count = cursor.rowcount
        if count > 0:
            record_audit("APPROVAL_SUPERSEDED", render_id, {"superseded_count": count}, db_path=db_path)
        return count
    finally:
        conn.close()

def record_audit(event_type: str, entity_id: str, details: dict, db_path: Path = DB_PATH):
    conn = get_connection(db_path)
    try:
        conn.execute(
            "INSERT INTO audit_log (event_type, entity_id, details_json) VALUES (?, ?, ?)",
            (event_type, entity_id, json.dumps(details))
        )
    finally:
        conn.close()
