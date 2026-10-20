"""Tests for single-worker leasing, heartbeat, crash recovery, and pause controls."""

import pytest
import sqlite3
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta

from backend.app.db.connection import init_db, get_connection
from backend.app.db.repository import (
    create_job,
    lease_next_job,
    heartbeat_job,
    complete_job,
    set_global_pause
)
from backend.app.worker.runner import WorkerRunner

@pytest.fixture
def test_db(tmp_path: Path):
    db_file = tmp_path / "test_worker.db"
    init_db(db_file)
    return db_file

def test_single_job_lease_and_completion(test_db: Path):
    """Worker leases a job, executes it, and marks it SUCCEEDED."""
    job_id = create_job("MOCK_SCRIPT", {"topic": "Quantum Computing"}, "quantum_01", db_path=test_db)
    
    worker = WorkerRunner(db_path=test_db, worker_id="worker_slot_1")
    result = worker.run_one_cycle()

    assert result is not None
    assert result["job_id"] == job_id
    assert result["status"] == "COMPLETED"

    conn = get_connection(test_db)
    try:
        job = conn.execute("SELECT status, attempts, lease_token FROM jobs WHERE id = ?", (job_id,)).fetchone()
        assert job["status"] == "SUCCEEDED"
        assert job["attempts"] == 1
        assert job["lease_token"] is None
    finally:
        conn.close()

def test_expired_lease_automatic_recovery(test_db: Path):
    """When a worker leases a job and dies without completing it, expired lease is reclaimed and re-queued."""
    job_id = create_job("MOCK_AUDIO", {"text": "Testing crash recovery"}, "audio_01", db_path=test_db)

    # Simulate worker leasing the job with a lease that expired 10 seconds ago
    expired_time = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    conn = get_connection(test_db)
    try:
        conn.execute(
            """
            UPDATE jobs
            SET status = 'LEASED', lease_token = 'crashed_worker', lease_expires_at = ?, attempts = 1
            WHERE id = ?
            """,
            (expired_time, job_id)
        )
    finally:
        conn.close()

    # New worker runs a cycle
    new_worker = WorkerRunner(db_path=test_db, worker_id="healthy_worker")
    result = new_worker.run_one_cycle()

    assert result is not None
    assert result["job_id"] == job_id
    assert result["status"] == "COMPLETED"

    conn = get_connection(test_db)
    try:
        job = conn.execute("SELECT status, attempts FROM jobs WHERE id = ?", (job_id,)).fetchone()
        assert job["status"] == "SUCCEEDED"
        assert job["attempts"] == 2 # 1 prior + 1 recovered attempt
    finally:
        conn.close()

def test_global_pause_halts_worker_leasing(test_db: Path):
    """When global pause is enabled, worker refuses to lease any jobs."""
    job_id = create_job("MOCK_SCRIPT", {"topic": "AI Ethics"}, "ethics_01", db_path=test_db)
    set_global_pause(True, db_path=test_db)

    worker = WorkerRunner(db_path=test_db, worker_id="worker_slot_1")
    result = worker.run_one_cycle()

    assert result is None # Did not process job

    conn = get_connection(test_db)
    try:
        job = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
        assert job["status"] == "QUEUED" # Remained in queue
    finally:
        conn.close()

    # Unpause and verify execution
    set_global_pause(False, db_path=test_db)
    result = worker.run_one_cycle()
    assert result is not None
    assert result["job_id"] == job_id
