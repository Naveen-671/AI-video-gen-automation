"""Tests verifying that database triggers reject publishing attempts without valid approvals."""

import pytest
import sqlite3
import uuid
from pathlib import Path
from backend.app.db.connection import init_db, get_connection
from backend.app.db.repository import (
    create_render,
    create_approval,
    supersede_approval_for_render
)

@pytest.fixture
def test_db(tmp_path: Path):
    db_file = tmp_path / "test_trigger.db"
    init_db(db_file)
    return db_file

def test_db_trigger_rejects_unapproved_publish_attempt(test_db: Path):
    """Attempting direct INSERT into publish_attempts with nonexistent approval must be rejected by trigger."""
    render_id = str(uuid.uuid4())
    create_render(render_id, checksum="sha256_mock_111", recipe_json="{}", db_path=test_db)

    conn = get_connection(test_db)
    try:
        with pytest.raises(sqlite3.IntegrityError) as exc_info:
            conn.execute(
                """
                INSERT INTO publish_attempts (
                    id, approval_id, render_id, platform, target_channel_id, idempotency_key
                ) VALUES (?, ?, ?, 'youtube', 'test_channel', 'idemp_key_1')
                """,
                (str(uuid.uuid4()), "nonexistent_approval_id", render_id)
            )
        assert "Publish attempt rejected" in str(exc_info.value)
    finally:
        conn.close()

def test_db_trigger_rejects_superseded_approval(test_db: Path):
    """When an input edit supersedes an approval, the trigger must reject subsequent publish inserts."""
    render_id = str(uuid.uuid4())
    checksum = "sha256_mock_222"
    create_render(render_id, checksum=checksum, recipe_json="{}", db_path=test_db)
    
    app_id = str(uuid.uuid4())
    create_approval(app_id, render_id=render_id, checksum=checksum, status="APPROVED", db_path=test_db)

    # Invalidate / supersede approval due to edit
    supersede_approval_for_render(render_id, db_path=test_db)

    conn = get_connection(test_db)
    try:
        with pytest.raises(sqlite3.IntegrityError) as exc_info:
            conn.execute(
                """
                INSERT INTO publish_attempts (
                    id, approval_id, render_id, platform, target_channel_id, idempotency_key
                ) VALUES (?, ?, ?, 'youtube', 'test_channel', 'idemp_key_2')
                """,
                (str(uuid.uuid4()), app_id, render_id)
            )
        assert "Publish attempt rejected" in str(exc_info.value)
    finally:
        conn.close()

def test_db_trigger_rejects_checksum_mismatch(test_db: Path):
    """If the approval was recorded for a different checksum than the render has, trigger rejects it."""
    render_id = str(uuid.uuid4())
    actual_checksum = "sha256_actual_render"
    create_render(render_id, checksum=actual_checksum, recipe_json="{}", db_path=test_db)

    app_id = str(uuid.uuid4())
    # Approval recorded with mismatched checksum
    create_approval(app_id, render_id=render_id, checksum="sha256_old_hash_differing", status="APPROVED", db_path=test_db)

    conn = get_connection(test_db)
    try:
        with pytest.raises(sqlite3.IntegrityError) as exc_info:
            conn.execute(
                """
                INSERT INTO publish_attempts (
                    id, approval_id, render_id, platform, target_channel_id, idempotency_key
                ) VALUES (?, ?, ?, 'youtube', 'test_channel', 'idemp_key_3')
                """,
                (str(uuid.uuid4()), app_id, render_id)
            )
        assert "Publish attempt rejected" in str(exc_info.value)
    finally:
        conn.close()

def test_db_trigger_allows_valid_approved_render(test_db: Path):
    """When approval matches render ID, checksum, is APPROVED, and NOT superseded, INSERT succeeds."""
    render_id = str(uuid.uuid4())
    checksum = "sha256_perfect_match"
    create_render(render_id, checksum=checksum, recipe_json="{}", db_path=test_db)

    app_id = str(uuid.uuid4())
    create_approval(app_id, render_id=render_id, checksum=checksum, status="APPROVED", db_path=test_db)

    conn = get_connection(test_db)
    try:
        attempt_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO publish_attempts (
                id, approval_id, render_id, platform, target_channel_id, idempotency_key
            ) VALUES (?, ?, ?, 'youtube', 'test_channel', 'idemp_key_valid')
            """,
            (attempt_id, app_id, render_id)
        )
        row = conn.execute("SELECT id, status FROM publish_attempts WHERE id = ?", (attempt_id,)).fetchone()
        assert row is not None
        assert row["status"] == "PENDING"
    finally:
        conn.close()
