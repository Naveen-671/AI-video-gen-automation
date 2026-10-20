"""Publisher adapter implementing strict approval verification and reconciliation logic."""

import sqlite3
import uuid
from typing import Dict, Any, Optional
from pathlib import Path

from backend.app.config import DB_PATH
from backend.app.db.connection import get_connection
from backend.app.domain.state_machines import PublishAttemptState

class UnapprovedRenderPublishError(Exception):
    """Raised when publishing is attempted on a render without valid, non-superseded approval."""
    pass

class MockPublisher:
    """Mock publisher for YouTube / test channels with fail-closed approval checks."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path

    def publish_render(
        self,
        approval_id: str,
        render_id: str,
        platform: str = "youtube",
        target_channel_id: str = "test_channel_001",
        idempotency_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Attempts to publish a render.
        The database trigger strictly enforces that (approval_id, render_id, render_checksum)
        matches a non-superseded APPROVED approval record.
        """
        attempt_id = str(uuid.uuid4())
        if idempotency_key is None:
            idempotency_key = f"pub_{render_id}_{attempt_id[:8]}"

        conn = get_connection(self.db_path)
        try:
            # Step 1: Insert into outbox table 'publish_attempts'
            # If unapproved or superseded, the SQLite trigger will raise an ABORT error here
            try:
                conn.execute(
                    """
                    INSERT INTO publish_attempts (
                        id, approval_id, render_id, platform, target_channel_id, status, idempotency_key
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        attempt_id,
                        approval_id,
                        render_id,
                        platform,
                        target_channel_id,
                        PublishAttemptState.IN_FLIGHT.value,
                        idempotency_key
                    )
                )
            except sqlite3.IntegrityError as e:
                # Trigger abort or foreign key error
                raise UnapprovedRenderPublishError(
                    f"Publishing blocked: Render {render_id} is unapproved or approval was superseded. Error: {str(e)}"
                ) from e

            # Step 2: Simulate successful upload to platform
            external_id = f"mock_{platform}_vid_{uuid.uuid4().hex[:8]}"
            conn.execute(
                """
                UPDATE publish_attempts
                SET status = ?, external_id = ?
                WHERE id = ?
                """,
                (PublishAttemptState.SUCCESS.value, external_id, attempt_id)
            )

            return {
                "attempt_id": attempt_id,
                "render_id": render_id,
                "platform": platform,
                "target_channel_id": target_channel_id,
                "external_id": external_id,
                "status": PublishAttemptState.SUCCESS.value,
                "disclosure_altered_content": True
            }
        finally:
            conn.close()

    def reconcile_uncertain_upload(self, attempt_id: str, expected_title_or_checksum: str) -> Dict[str, Any]:
        """
        Reconciles an upload left in UNCERTAIN state without re-transmitting media bytes.
        """
        conn = get_connection(self.db_path)
        try:
            row = conn.execute("SELECT * FROM publish_attempts WHERE id = ?", (attempt_id,)).fetchone()
            if not row:
                raise ValueError(f"Publish attempt {attempt_id} not found.")

            # In mock mode, verify if external entity exists; if confirmed, set SUCCESS
            confirmed_external_id = f"reconciled_{row['platform']}_{attempt_id[:8]}"
            conn.execute(
                """
                UPDATE publish_attempts
                SET status = ?, external_id = ?
                WHERE id = ?
                """,
                (PublishAttemptState.SUCCESS.value, confirmed_external_id, attempt_id)
            )

            return {
                "attempt_id": attempt_id,
                "status": PublishAttemptState.SUCCESS.value,
                "external_id": confirmed_external_id,
                "reconciled": True
            }
        finally:
            conn.close()
