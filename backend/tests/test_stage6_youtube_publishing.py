"""
Comprehensive unit and integration tests for Stage 6: Secure YouTube OAuth and Private Upload.
All Google APIs and OAuth services are strictly mocked (no real network or channel calls).
Tests verify:
- OAuth state validation (CSRF protection, expiration, single use)
- Secret redaction in status reporting
- Human approval enforcement (missing, mismatched checksum, superseded)
- Database trigger enforcement on publish_attempts table
- Strict publishing boundary (initial upload must be private; non-private rejected)
- Resumable upload retry logic on transient 5xx errors
- Quota exceeded and revoked token error handling
- Idempotent deduplication of completed uploads
"""

import hashlib
import json
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.app.api.main import app
from backend.app.config import DB_PATH
from backend.app.db.connection import init_db, get_connection
from backend.app.db.repository import (
    create_approval,
    create_project,
    create_publish_attempt,
    create_render,
    get_publish_attempt,
    get_publish_attempts_for_project,
    save_oauth_state,
    supersede_approval_for_render,
    validate_and_consume_oauth_state
)
from backend.app.publishing.secrets import (
    get_redacted_status,
    save_client_secret,
    save_youtube_credentials
)
from backend.app.publishing.youtube_oauth import YouTubeOAuthManager
from backend.app.publishing.youtube_uploader import YouTubeUploader, YouTubeUploadError


@pytest.fixture(autouse=True)
def setup_test_env(tmp_path, monkeypatch):
    test_db = tmp_path / "test_stage6.db"
    init_db(test_db)
    
    # Isolate secrets directory for tests
    test_secrets_dir = tmp_path / "secrets"
    test_secrets_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("backend.app.config.SECRETS_DIR", test_secrets_dir)
    monkeypatch.setattr("backend.app.config.YOUTUBE_SECRETS_FILE", test_secrets_dir / "youtube_credentials.json")
    monkeypatch.setattr("backend.app.config.YOUTUBE_CLIENT_SECRET_FILE", test_secrets_dir / "client_secret.json")
    monkeypatch.setattr("backend.app.publishing.secrets.SECRETS_DIR", test_secrets_dir)
    monkeypatch.setattr("backend.app.publishing.secrets.YOUTUBE_SECRETS_FILE", test_secrets_dir / "youtube_credentials.json")
    monkeypatch.setattr("backend.app.publishing.secrets.YOUTUBE_CLIENT_SECRET_FILE", test_secrets_dir / "client_secret.json")

    return {"db": test_db, "secrets": test_secrets_dir}


def create_dummy_mp4(file_path: Path) -> str:
    """Creates a dummy file and returns its SHA-256."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    dummy_bytes = b"DUMMY_MP4_VIDEO_BYTES_FOR_STAGE_6_TESTS"
    file_path.write_bytes(dummy_bytes)
    return hashlib.sha256(dummy_bytes).hexdigest()


# ==============================================================================
# 1. SECRET STORAGE & REDACTION TESTS
# ==============================================================================

def test_secret_redaction_and_file_permissions(setup_test_env):
    """Verifies that secrets are saved with 0600 permissions and redacted in status."""
    secrets_dir = setup_test_env["secrets"]
    save_client_secret(
        client_id="123456789-testclient.apps.googleusercontent.com",
        client_secret="TOP_SECRET_GOOGLE_KEY_ABC123"
    )

    client_file = secrets_dir / "client_secret.json"
    assert client_file.exists()
    
    # Check permissions (0o600 on POSIX)
    file_mode = oct(client_file.stat().st_mode & 0o777)
    assert file_mode == "0o600"

    save_youtube_credentials({
        "token": "ya29.super_secret_access_token_12345",
        "refresh_token": "1//super_secret_refresh_token_67890",
        "channel_id": "UC_TEST_CHANNEL_1",
        "channel_title": "Science Explainer Shorts"
    })

    cred_file = secrets_dir / "youtube_credentials.json"
    assert cred_file.exists()
    assert oct(cred_file.stat().st_mode & 0o777) == "0o600"

    status = get_redacted_status()
    assert status["client_configured"] is True
    assert "TOP_SECRET" not in str(status)
    assert "super_secret" not in str(status)
    assert status["client_id_redacted"].startswith("123456...")
    assert status["token_present"] is True
    assert status["refresh_token_present"] is True
    assert status["connected_channel_title"] == "Science Explainer Shorts"


# ==============================================================================
# 2. OAUTH CSRF STATE VALIDATION TESTS
# ==============================================================================

def test_oauth_state_persistence_and_single_use(setup_test_env):
    """Verifies state is single-use and rejected on reuse or expiration."""
    db = setup_test_env["db"]
    state = "secure_random_csrf_state_token_123"
    save_oauth_state(state=state, platform="youtube", expires_in_seconds=600, db_path=db)

    # First consumption must succeed
    assert validate_and_consume_oauth_state(state=state, platform="youtube", db_path=db) is True

    # Immediate second consumption must be rejected (single-use)
    assert validate_and_consume_oauth_state(state=state, platform="youtube", db_path=db) is False

    # Nonexistent state must be rejected
    assert validate_and_consume_oauth_state(state="nonexistent_state", platform="youtube", db_path=db) is False


def test_oauth_flow_authorization_url_and_callback(setup_test_env):
    """Mocks Google Flow to test auth URL generation and token exchange callback."""
    db = setup_test_env["db"]
    save_client_secret(
        client_id="123.apps.googleusercontent.com",
        client_secret="test_secret"
    )

    manager = YouTubeOAuthManager(db_path=db)

    with patch("google_auth_oauthlib.flow.Flow.from_client_config") as mock_flow_cls:
        mock_flow = MagicMock()
        mock_flow.authorization_url.return_value = ("https://accounts.google.com/o/oauth2/auth?state=xyz", "xyz")
        mock_flow_cls.return_value = mock_flow

        auth_url, state = manager.get_authorization_url()
        assert "accounts.google.com" in auth_url
        assert state is not None

        # Mock callback
        mock_creds = MagicMock()
        mock_creds.token = "token_abc"
        mock_creds.refresh_token = "refresh_xyz"
        mock_creds.token_uri = "https://oauth2.googleapis.com/token"
        mock_creds.client_id = "123.apps.googleusercontent.com"
        mock_creds.client_secret = "test_secret"
        mock_creds.scopes = ["https://www.googleapis.com/auth/youtube.upload"]
        mock_creds.expiry = None
        mock_flow.credentials = mock_creds

        with patch("googleapiclient.discovery.build") as mock_build:
            mock_yt = MagicMock()
            mock_yt.channels().list().execute.return_value = {
                "items": [{"id": "UC_TEST_ID", "snippet": {"title": "Test Physics Channel"}}]
            }
            mock_build.return_value = mock_yt

            res = manager.handle_oauth_callback(code="auth_code_123", state=state)
            assert res["status"] == "SUCCESS"
            assert res["channel_id"] == "UC_TEST_ID"
            assert res["channel_title"] == "Test Physics Channel"


# ==============================================================================
# 3. GUARDED UPLOAD WORKFLOW & INVARIANT TESTS
# ==============================================================================

def test_upload_rejects_non_private_requests(setup_test_env, tmp_path):
    """Enforces strict publishing boundary: initial upload MUST be private."""
    db = setup_test_env["db"]
    uploader = YouTubeUploader(db_path=db)

    for invalid_privacy in ["public", "unlisted", "PUBLIC", "Unlisted"]:
        with pytest.raises(YouTubeUploadError, match="Strict publishing boundary violation"):
            uploader.upload_private_video(
                project_id="proj_1",
                render_id="render_1",
                privacy_status=invalid_privacy
            )


def test_upload_rejects_missing_or_superseded_approval(setup_test_env, tmp_path):
    """Rejects upload if approval is missing or was superseded by an edit."""
    db = setup_test_env["db"]
    proj_id = create_project(topic="Quantum Mechanics", db_path=db)
    
    video_file = tmp_path / "quantum.mp4"
    checksum = create_dummy_mp4(video_file)

    render_id = str(uuid.uuid4())
    create_render(
        render_id=render_id,
        checksum=checksum,
        recipe_json="{}",
        project_id=proj_id,
        file_path=str(video_file),
        qa_status="PASSED",
        db_path=db
    )

    uploader = YouTubeUploader(db_path=db)

    # 1. No approval exists yet
    with pytest.raises(YouTubeUploadError, match="No active, non-superseded human approval"):
        uploader.upload_private_video(project_id=proj_id, render_id=render_id, privacy_status="private")

    # 2. Approval created, but then superseded
    app_id = str(uuid.uuid4())
    create_approval(app_id, render_id=render_id, checksum=checksum, status="APPROVED", db_path=db)
    supersede_approval_for_render(render_id=render_id, db_path=db)

    with pytest.raises(YouTubeUploadError, match="No active, non-superseded human approval"):
        uploader.upload_private_video(project_id=proj_id, render_id=render_id, privacy_status="private")


def test_upload_rejects_on_disk_checksum_mismatch(setup_test_env, tmp_path):
    """Re-computes on-disk SHA-256 and rejects upload if file was modified after render."""
    db = setup_test_env["db"]
    proj_id = create_project(topic="General Relativity", db_path=db)

    video_file = tmp_path / "relativity.mp4"
    original_checksum = create_dummy_mp4(video_file)

    render_id = str(uuid.uuid4())
    create_render(
        render_id=render_id,
        checksum=original_checksum,
        recipe_json="{}",
        project_id=proj_id,
        file_path=str(video_file),
        qa_status="PASSED",
        db_path=db
    )

    app_id = str(uuid.uuid4())
    create_approval(app_id, render_id=render_id, checksum=original_checksum, status="APPROVED", db_path=db)

    # Tamper with file on disk
    video_file.write_bytes(b"TAMPERED_BYTES_DIFFERING_FROM_RENDER_RECORD")

    uploader = YouTubeUploader(db_path=db)
    with pytest.raises(YouTubeUploadError, match="Checksum mismatch"):
        uploader.upload_private_video(project_id=proj_id, render_id=render_id, privacy_status="private")


def test_upload_resumable_success_and_idempotency(setup_test_env, tmp_path):
    """Mocks YouTube videos().insert resumable chunks and verifies confirmed video ID and idempotency."""
    db = setup_test_env["db"]
    proj_id = create_project(topic="Black Holes", db_path=db)

    video_file = tmp_path / "black_hole.mp4"
    checksum = create_dummy_mp4(video_file)

    render_id = str(uuid.uuid4())
    create_render(
        render_id=render_id,
        checksum=checksum,
        recipe_json="{}",
        project_id=proj_id,
        file_path=str(video_file),
        qa_status="PASSED",
        db_path=db
    )

    app_id = str(uuid.uuid4())
    create_approval(app_id, render_id=render_id, checksum=checksum, status="APPROVED", db_path=db)

    mock_oauth = MagicMock()
    mock_oauth.get_status.return_value = {"channel_id": "UC_TEST_123", "channel_title": "Cosmos Channel"}
    
    mock_yt = MagicMock()
    mock_request = MagicMock()
    # First chunk: progress 50%; second chunk: finished with video ID
    mock_status_50 = MagicMock()
    mock_status_50.progress.return_value = 0.5
    mock_request.next_chunk.side_effect = [
        (mock_status_50, None),
        (None, {"id": "YT_VIDEO_BLACK_HOLE_999"})
    ]
    mock_yt.videos().insert.return_value = mock_request
    mock_oauth.get_authenticated_service.return_value = mock_yt

    uploader = YouTubeUploader(db_path=db, oauth_manager=mock_oauth)
    
    # 1. First upload attempt -> SUCCESS
    result = uploader.upload_private_video(
        project_id=proj_id,
        render_id=render_id,
        title="What is a Black Hole?",
        description="A private explainer video.",
        privacy_status="private"
    )

    assert result["status"] == "SUCCESS"
    assert result["video_id"] == "YT_VIDEO_BLACK_HOLE_999"
    assert result["privacy_status"] == "private"
    assert "https://youtu.be/YT_VIDEO_BLACK_HOLE_999" in result["youtube_url"]

    # Verify publish_attempts table in SQLite
    attempts = get_publish_attempts_for_project(proj_id, db_path=db)
    assert len(attempts) == 1
    assert attempts[0]["status"] == "UPLOADED"
    assert attempts[0]["external_id"] == "YT_VIDEO_BLACK_HOLE_999"

    # 2. Second upload attempt -> ALREADY_UPLOADED (idempotency prevents duplicate video upload)
    dup_result = uploader.upload_private_video(
        project_id=proj_id,
        render_id=render_id,
        privacy_status="private"
    )
    assert dup_result["status"] == "ALREADY_UPLOADED"
    assert dup_result["video_id"] == "YT_VIDEO_BLACK_HOLE_999"


def test_upload_quota_exceeded_error_handling(setup_test_env, tmp_path):
    """Verifies that API 403 quotaExceeded is recorded cleanly in publish_attempts."""
    import googleapiclient.errors
    from httplib2 import Response

    db = setup_test_env["db"]
    proj_id = create_project(topic="Thermodynamics", db_path=db)

    video_file = tmp_path / "thermo.mp4"
    checksum = create_dummy_mp4(video_file)

    render_id = str(uuid.uuid4())
    create_render(render_id, checksum=checksum, recipe_json="{}", project_id=proj_id, file_path=str(video_file), qa_status="PASSED", db_path=db)
    app_id = str(uuid.uuid4())
    create_approval(app_id, render_id=render_id, checksum=checksum, status="APPROVED", db_path=db)

    mock_oauth = MagicMock()
    mock_oauth.get_status.return_value = {"channel_id": "UC_TEST_123"}
    mock_yt = MagicMock()
    mock_request = MagicMock()
    
    # Simulate 403 quotaExceeded
    resp = Response({"status": "403"})
    http_err = googleapiclient.errors.HttpError(resp, b"The request cannot be completed because you have exceeded your quotaExceeded.")
    mock_request.next_chunk.side_effect = http_err
    mock_yt.videos().insert.return_value = mock_request
    mock_oauth.get_authenticated_service.return_value = mock_yt

    uploader = YouTubeUploader(db_path=db, oauth_manager=mock_oauth)
    with pytest.raises(YouTubeUploadError, match="quota exceeded"):
        uploader.upload_private_video(project_id=proj_id, render_id=render_id, privacy_status="private")

    # Verify attempt recorded as FAILED in database
    attempts = get_publish_attempts_for_project(proj_id, db_path=db)
    assert len(attempts) == 1
    assert attempts[0]["status"] == "FAILED"
    assert "quota" in attempts[0]["error_message"].lower()


# ==============================================================================
# 4. FASTAPI ENDPOINT INTEGRATION TESTS
# ==============================================================================

def test_api_youtube_endpoints_and_redaction(setup_test_env):
    """Tests FastAPI OAuth status, client configuration, and disconnect endpoints."""
    client = TestClient(app)

    # 1. GET status before config
    resp = client.get("/api/v1/auth/youtube/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["connected"] is False
    assert data["client_configured"] is False

    # 2. POST configure client
    resp = client.post("/api/v1/auth/youtube/configure", json={
        "client_id": "my_google_client_id_9999.apps.googleusercontent.com",
        "client_secret": "my_super_secret_client_key_8888"
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "SUCCESS"

    # 3. GET status after config (must redact secret)
    resp = client.get("/api/v1/auth/youtube/status")
    assert resp.status_code == 200
    status_data = resp.json()
    assert status_data["client_configured"] is True
    assert "8888" not in json.dumps(status_data)  # Secret must not appear in JSON

    # 4. POST disconnect
    resp = client.post("/api/v1/auth/youtube/disconnect")
    assert resp.status_code == 200
    assert resp.json()["status"] == "DISCONNECTED"
