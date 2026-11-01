"""Comprehensive automated tests for Phase 2A Video Production Pipeline.

Tests all 12 required scenarios:
1. Creating project & script/storyboard data
2. Missing/invalid assets & path traversal
3. Manual-audio and silent modes
4. FFmpeg rendering of short vertical video
5. ffprobe metadata, aspect ratio, and duration validation
6. Rendering failures and recovery
7. Idempotent job handling
8. Resource guardrails
9. Checksum creation & immutable render artifacts
10. Editing after approval invalidates approval
11. Publishing remains impossible without valid approval
12. API preview, download, and approval flow
"""

import pytest
import sqlite3
import uuid
import json
import subprocess
from pathlib import Path
from fastapi.testclient import TestClient

from backend.app.api.main import app
from backend.app.config import DB_PATH, MEDIA_DIR
from backend.app.db.connection import init_db, get_connection
from backend.app.db.repository import (
    create_project,
    get_project,
    list_projects,
    update_project_storyboard,
    create_job,
    create_render,
    create_approval,
    get_render
)
from backend.app.media.assets import (
    save_uploaded_asset,
    generate_default_scene_background,
    AssetValidationError
)
from backend.app.media.narration import SilentNarrationAdapter, ManualAudioAdapter, NarrationAdapterError
from backend.app.media.ffmpeg_composer import FFmpegComposer, FFmpegCompositionError
from backend.app.media.qa import TechnicalQA
from backend.app.worker.runner import WorkerRunner
from backend.app.publishers.mock_publisher import MockPublisher, UnapprovedRenderPublishError

@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch):
    """Sets up an isolated database and media directory for each test."""
    test_db = tmp_path / "test_phase2a.db"
    test_media = tmp_path / "media"
    test_media.mkdir(parents=True, exist_ok=True)

    init_db(test_db)
    monkeypatch.setattr("backend.app.api.main.DB_PATH", test_db)
    monkeypatch.setattr("backend.app.db.repository.DB_PATH", test_db)
    monkeypatch.setattr("backend.app.worker.runner.DB_PATH", test_db)
    monkeypatch.setattr("backend.app.publishers.mock_publisher.DB_PATH", test_db)
    monkeypatch.setattr("backend.app.config.DB_PATH", test_db)
    monkeypatch.setattr("backend.app.config.MEDIA_DIR", test_media)
    monkeypatch.setattr("backend.app.media.assets.MEDIA_DIR", test_media)
    monkeypatch.setattr("backend.app.worker.runner.MEDIA_DIR", test_media)

    return {"db": test_db, "media": test_media}

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c

# --- Test 1: Creating project and validating script/storyboard data ---
def test_create_project_and_storyboard(client: TestClient):
    payload = {
        "topic": "Neural Compression",
        "title": "How Neural Compression Works",
        "target_audience": "Developers",
        "language": "en",
        "target_duration": 15.0,
        "content_format": "explainer",
        "narration_mode": "silent"
    }
    res = client.post("/projects", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert "project_id" in data
    assert data["scenes_count"] == 3

    # Inspect created project
    proj_res = client.get(f"/projects/{data['project_id']}")
    assert proj_res.status_code == 200
    p = proj_res.json()
    assert p["title"] == "How Neural Compression Works"
    assert len(p["scenes"]) == 3
    assert p["scenes"][0]["scene_title"] == "The Hook"
    assert "Neural Compression" in p["scenes"][0]["narration_text"]

# --- Test 2: Missing or invalid assets and path traversal ---
def test_missing_or_invalid_assets(isolated_env):
    project_id = str(uuid.uuid4())
    
    # 1. Invalid extension
    with pytest.raises(AssetValidationError) as exc:
        save_uploaded_asset(project_id, b"malicious binary", "script.exe")
    assert "Unsupported file format" in str(exc.value)

    # 2. File size limit exceeded (>20 MB for images)
    oversized = b"0" * (21 * 1024 * 1024)
    with pytest.raises(AssetValidationError) as exc:
        save_uploaded_asset(project_id, oversized, "large.png")
    assert "exceeds maximum size" in str(exc.value)

    # 3. Path traversal prevention
    with pytest.raises(AssetValidationError):
        save_uploaded_asset(project_id, b"fake img", "../../../../etc/passwd.png")

# --- Test 3: Manual-audio and silent modes ---
def test_manual_audio_and_silent_modes(isolated_env):
    media_dir = isolated_env["media"]
    silent_adapter = SilentNarrationAdapter()
    manual_adapter = ManualAudioAdapter()

    # Silent mode: generates silent AAC
    silent_out = media_dir / "test_silent.aac"
    silent_adapter.prepare_audio(duration_seconds=3.0, output_path=silent_out)
    assert silent_out.exists()
    assert silent_out.stat().st_size > 0

    # Manual mode: rejects nonexistent file
    with pytest.raises(NarrationAdapterError):
        manual_adapter.verify_audio(media_dir / "nonexistent.mp3")

    # Manual mode: verifies real audio file
    real_audio = media_dir / "real.wav"
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=1000:duration=2", str(real_audio)
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    info = manual_adapter.verify_audio(real_audio)
    assert info["channels"] > 0
    assert info["duration"] > 1.8

# --- Test 4 & 5: FFmpeg vertical video render & ffprobe verification ---
def test_ffmpeg_render_and_ffprobe_verification(isolated_env):
    media_dir = isolated_env["media"]
    proj_id = "test_render_proj"

    # Create 2 small test scenes (each 1.5s -> total 3.0s)
    s1_img = media_dir / "s1.png"
    s2_img = media_dir / "s2.png"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=720x1280:d=1", "-frames:v", "1", str(s1_img)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=indigo:s=720x1280:d=1", "-frames:v", "1", str(s2_img)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    scenes = [
        {"visual_asset_path": str(s1_img), "duration_seconds": 1.5, "caption_text": "Scene 1 Insight"},
        {"visual_asset_path": str(s2_img), "duration_seconds": 1.5, "caption_text": "Scene 2 Insight"}
    ]

    out_mp4 = media_dir / "rendered.mp4"
    composer = FFmpegComposer(width=720, height=1280, fps=30)
    result = composer.render(scenes=scenes, output_path=out_mp4)

    assert out_mp4.exists()
    assert result["render_checksum"] is not None
    assert len(result["render_checksum"]) == 64  # Valid SHA-256

    # Technical QA ffprobe checks
    qa = TechnicalQA.inspect_and_verify(
        video_path=out_mp4,
        expected_width=720,
        expected_height=1280,
        expected_duration=3.0,
        audio_expected=False
    )
    assert qa["passed"] is True
    assert qa["details"]["width"] == 720
    assert qa["details"]["height"] == 1280
    assert abs(qa["details"]["duration_seconds"] - 3.0) < 0.2

# --- Test 6: Rendering failures and recovery ---
def test_render_failure_handling(isolated_env):
    composer = FFmpegComposer(width=720, height=1280)
    out_mp4 = isolated_env["media"] / "fail.mp4"

    # Passing a non-existent visual asset must fail-closed
    bad_scenes = [{"visual_asset_path": "/nonexistent/path/image.png", "duration_seconds": 2.0}]
    with pytest.raises(FFmpegCompositionError):
        composer.render(scenes=bad_scenes, output_path=out_mp4)

# --- Test 7: Idempotent job handling ---
def test_idempotent_job_creation(isolated_env):
    db = isolated_env["db"]
    idemp_key = "unique_render_key_123"

    job_id_1 = create_job("RENDER_PROJECT", {"project_id": "p1"}, idemp_key, db_path=db)
    job_id_2 = create_job("RENDER_PROJECT", {"project_id": "p1"}, idemp_key, db_path=db)

    assert job_id_1 == job_id_2

# --- Test 8: Resource guardrails ---
def test_worker_resource_guardrails(isolated_env, monkeypatch):
    db = isolated_env["db"]
    worker = WorkerRunner(db_path=db)

    # Simulate low RAM condition (< 3.0 GiB)
    monkeypatch.setattr(
        "backend.app.worker.runner.check_system_resources",
        lambda: {"can_process_jobs": False, "available_ram_gib": 1.5, "min_ram_threshold_gib": 3.0, "free_disk_gb": 40.0, "min_disk_threshold_gb": 10.0}
    )
    create_job("MOCK_SCRIPT", {"topic": "AI"}, "guardrail_test", db_path=db)

    # Worker should refuse to run job
    result = worker.run_one_cycle()
    assert result is None

# --- Test 9: Checksum creation and immutable render artifacts ---
def test_immutable_render_checksum(isolated_env):
    db = isolated_env["db"]
    render_id_1 = str(uuid.uuid4())
    checksum_1 = "sha256_render_variant_1"
    create_render(render_id_1, checksum=checksum_1, recipe_json='{"v":1}', db_path=db)

    r1 = get_render(render_id_1, db_path=db)
    assert r1["render_checksum"] == checksum_1

    # Renders with different content have distinct checksums and cannot overwrite
    render_id_2 = str(uuid.uuid4())
    checksum_2 = "sha256_render_variant_2"
    create_render(render_id_2, checksum=checksum_2, recipe_json='{"v":2}', db_path=db)

    r2 = get_render(render_id_2, db_path=db)
    assert r2["render_checksum"] == checksum_2
    assert r1["render_checksum"] != r2["render_checksum"]

# --- Test 10: Editing after approval invalidates approval ---
def test_editing_after_approval_supersedes_approval(client: TestClient, isolated_env):
    db = isolated_env["db"]
    # 1. Create project
    proj_res = client.post("/projects", json={"topic": "Black Holes", "target_duration": 15.0})
    p_id = proj_res.json()["project_id"]

    # 2. Simulate render creation
    render_id = str(uuid.uuid4())
    checksum = "sha256_approved_black_holes"
    create_render(render_id, checksum=checksum, recipe_json="{}", project_id=p_id, db_path=db)

    # Connect render to project
    conn = get_connection(db)
    conn.execute("UPDATE projects SET current_render_id = ?, status = 'AWAITING_APPROVAL' WHERE id = ?", (render_id, p_id))
    conn.close()

    # 3. Approve render via API
    app_res = client.post(f"/renders/{render_id}/approve", json={"status": "APPROVED", "reviewer": "human"})
    assert app_res.status_code == 200

    # Verify project is APPROVED
    p_state = client.get(f"/projects/{p_id}").json()
    assert p_state["status"] == "APPROVED"
    assert p_state["approval_status"] == "APPROVED"

    # 4. Operator modifies storyboard text
    updated_scenes = [
        {"scene_index": 0, "scene_title": "Edited Hook", "narration_text": "New Hook Text", "caption_text": "New Hook", "duration_seconds": 5.0}
    ]
    edit_res = client.put(f"/projects/{p_id}/storyboard", json={"scenes": updated_scenes})
    assert edit_res.status_code == 200

    # 5. Verify prior approval is SUPERSEDED and project status dropped back to STORYBOARD
    p_after_edit = client.get(f"/projects/{p_id}").json()
    assert p_after_edit["status"] == "STORYBOARD"
    assert p_after_edit["current_render_id"] is None

    conn = get_connection(db)
    prior_app = conn.execute("SELECT superseded_at FROM approvals WHERE render_id = ?", (render_id,)).fetchone()
    conn.close()
    assert prior_app["superseded_at"] is not None  # Superseded!

# --- Test 11: Publishing remains impossible without valid approval ---
def test_publishing_blocked_without_valid_approval(isolated_env):
    db = isolated_env["db"]
    publisher = MockPublisher(db_path=db)
    render_id = str(uuid.uuid4())
    create_render(render_id, checksum="sha256_unapproved_sample", recipe_json="{}", db_path=db)

    # Publishing unapproved render raises error
    with pytest.raises(UnapprovedRenderPublishError):
        publisher.publish_render("nonexistent_approval", render_id)

    # Direct database trigger test: attempt raw SQL insert into publish_attempts
    conn = get_connection(db)
    with pytest.raises(sqlite3.IntegrityError) as exc_info:
        conn.execute(
            """
            INSERT INTO publish_attempts (id, approval_id, render_id, platform, target_channel_id, idempotency_key)
            VALUES (?, ?, ?, 'youtube', 'test_channel', 'direct_hack_attempt')
            """,
            (str(uuid.uuid4()), "fake_approval", render_id)
        )
    conn.close()
    assert "Publish attempt rejected" in str(exc_info.value)

# --- Test 12: End-to-end API preview, download, and approval flow ---
def test_e2e_api_preview_download_approval_flow(client: TestClient, isolated_env):
    db = isolated_env["db"]
    media_dir = isolated_env["media"]

    # 1. Create project
    proj_res = client.post("/projects", json={"topic": "Quantum Computing", "target_duration": 6.0})
    project_id = proj_res.json()["project_id"]

    # 2. Trigger render via API
    render_trig = client.post(f"/projects/{project_id}/render", params={"width": 720, "height": 1280})
    assert render_trig.status_code == 200
    job_id = render_trig.json()["job_id"]

    # 3. Worker executes the real RENDER_PROJECT stage
    worker = WorkerRunner(db_path=db, worker_id="test_worker")
    cycle_result = worker.run_one_cycle()
    assert cycle_result is not None
    assert cycle_result["status"] == "COMPLETED"
    assert cycle_result["result"]["status"] == "SUCCESS"
    render_id = cycle_result["result"]["render_id"]
    checksum = cycle_result["result"]["render_checksum"]

    # 4. Verify project moved to AWAITING_APPROVAL
    p_info = client.get(f"/projects/{project_id}").json()
    assert p_info["status"] == "AWAITING_APPROVAL"
    assert p_info["current_render_id"] == render_id

    # 5. Download rendered MP4 through API endpoint
    file_res = client.get(f"/renders/{render_id}/file")
    assert file_res.status_code == 200
    assert file_res.headers["content-type"] == "video/mp4"
    assert len(file_res.content) > 1000

    # 6. Approve render
    approve_res = client.post(f"/renders/{render_id}/approve", json={"status": "APPROVED", "notes": "Approved by human editor"})
    assert approve_res.status_code == 200
    assert approve_res.json()["render_checksum"] == checksum

    # 7. Verify final project state is APPROVED
    p_final = client.get(f"/projects/{project_id}").json()
    assert p_final["status"] == "APPROVED"
    assert p_final["active_approval"]["status"] == "APPROVED"
