"""Tests for Publisher adapter verifying fail-closed behavior on unapproved renders and reconciliation."""

import pytest
import uuid
from pathlib import Path
from backend.app.db.connection import init_db
from backend.app.db.repository import (
    create_render,
    create_approval,
    supersede_approval_for_render
)
from backend.app.publishers.mock_publisher import MockPublisher, UnapprovedRenderPublishError

@pytest.fixture
def test_db(tmp_path: Path):
    db_file = tmp_path / "test_pub.db"
    init_db(db_file)
    return db_file

def test_publisher_refuses_unapproved_render(test_db: Path):
    """Publisher must fail-closed if no approval row exists."""
    render_id = str(uuid.uuid4())
    create_render(render_id, checksum="sha256_unapproved", recipe_json="{}", db_path=test_db)
    
    publisher = MockPublisher(db_path=test_db)
    with pytest.raises(UnapprovedRenderPublishError):
        publisher.publish_render(
            approval_id="nonexistent_approval",
            render_id=render_id,
            platform="youtube"
        )

def test_publisher_refuses_superseded_render(test_db: Path):
    """Publisher must refuse to publish if an approval was superseded by an edit."""
    render_id = str(uuid.uuid4())
    checksum = "sha256_edited_render"
    create_render(render_id, checksum=checksum, recipe_json="{}", db_path=test_db)

    app_id = str(uuid.uuid4())
    create_approval(app_id, render_id=render_id, checksum=checksum, status="APPROVED", db_path=test_db)

    # Supersede approval
    supersede_approval_for_render(render_id, db_path=test_db)

    publisher = MockPublisher(db_path=test_db)
    with pytest.raises(UnapprovedRenderPublishError):
        publisher.publish_render(
            approval_id=app_id,
            render_id=render_id,
            platform="youtube"
        )

def test_publisher_succeeds_for_valid_approval(test_db: Path):
    """Publisher successfully uploads and records external ID when approval is valid."""
    render_id = str(uuid.uuid4())
    checksum = "sha256_valid_render"
    create_render(render_id, checksum=checksum, recipe_json="{}", db_path=test_db)

    app_id = str(uuid.uuid4())
    create_approval(app_id, render_id=render_id, checksum=checksum, status="APPROVED", db_path=test_db)

    publisher = MockPublisher(db_path=test_db)
    result = publisher.publish_render(
        approval_id=app_id,
        render_id=render_id,
        platform="youtube",
        target_channel_id="channel_test_42"
    )

    assert result["status"] == "SUCCESS"
    assert "mock_youtube_vid_" in result["external_id"]
    assert result["disclosure_altered_content"] is True

def test_uncertain_upload_reconciliation(test_db: Path):
    """Simulated network timeout/drop can be reconciled without re-transmitting media."""
    render_id = str(uuid.uuid4())
    checksum = "sha256_reconcile"
    create_render(render_id, checksum=checksum, recipe_json="{}", db_path=test_db)

    app_id = str(uuid.uuid4())
    create_approval(app_id, render_id=render_id, checksum=checksum, status="APPROVED", db_path=test_db)

    publisher = MockPublisher(db_path=test_db)
    initial_pub = publisher.publish_render(approval_id=app_id, render_id=render_id)
    attempt_id = initial_pub["attempt_id"]

    # Reconcile attempt
    reconciliation = publisher.reconcile_uncertain_upload(attempt_id, expected_title_or_checksum=checksum)
    assert reconciliation["reconciled"] is True
    assert reconciliation["status"] == "SUCCESS"
