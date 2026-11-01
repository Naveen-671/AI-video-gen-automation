"""Tests for Google Flow Handoff and Ingestion Pipeline (Track 1)."""

import os
import json
import subprocess
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from backend.app.api.main import app
from backend.app.config import DB_PATH, MEDIA_DIR
from backend.app.db.connection import init_db
from backend.app.db.repository import (
    create_project,
    get_project,
    create_render,
    create_approval,
    get_connection,
    get_asset_provenances,
    get_render,
    update_project_storyboard
)
from backend.app.worker.runner import WorkerRunner
from backend.app.media.flow_handoff import (
    build_flow_prompt_for_scene,
    generate_flow_manifest,
    export_flow_manifest
)
from backend.app.media.flow_ingestion import (
    validate_flow_video,
    import_and_bind_flow_video,
    list_inbox_files,
    ValidationStatus,
    FlowValidationError,
    INBOX_DIR
)


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    test_db = tmp_path / "test_flow.db"
    test_media = tmp_path / "media"
    test_inbox = tmp_path / "inbox"
    test_media.mkdir(parents=True, exist_ok=True)
    test_inbox.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("backend.app.config.DB_PATH", test_db)
    monkeypatch.setattr("backend.app.config.MEDIA_DIR", test_media)
    monkeypatch.setattr("backend.app.db.repository.DB_PATH", test_db)
    monkeypatch.setattr("backend.app.api.main.DB_PATH", test_db)
    monkeypatch.setattr("backend.app.api.main.MEDIA_DIR", test_media)
    monkeypatch.setattr("backend.app.api.main.INBOX_DIR", test_inbox)
    monkeypatch.setattr("backend.app.media.flow_ingestion.DB_PATH", test_db)
    monkeypatch.setattr("backend.app.media.flow_ingestion.MEDIA_DIR", test_media)
    monkeypatch.setattr("backend.app.media.flow_ingestion.INBOX_DIR", test_inbox)
    monkeypatch.setattr("backend.app.worker.runner.MEDIA_DIR", test_media)

    init_db(test_db)
    return test_db, test_media, test_inbox


def create_synthetic_mp4(
    path: Path,
    width: int = 1080,
    height: int = 1920,
    duration: float = 3.0,
    color: str = "blue",
    add_motion: bool = True
) -> Path:
    """Creates a valid synthetic MP4 clip with moving color/noise using FFmpeg."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if add_motion:
        # Gradiated moving test pattern
        filter_str = f"testsrc=size={width}x{height}:rate=30,format=yuv420p"
    else:
        # Pure static solid color (for frozen/blank tests)
        filter_str = f"color=c={color}:s={width}x{height}:r=30,format=yuv420p"

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", filter_str,
        "-t", f"{duration:.3f}",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        str(path)
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return path


def test_flow_prompt_generation_and_export(setup_test_db):
    test_db, test_media, _ = setup_test_db
    p_id = create_project(
        title="Cosmic Supermassive Black Holes",
        topic="Supermassive Black Hole Singularity",
        target_audience="curious_minds",
        db_path=test_db
    )

    client = TestClient(app)
    resp = client.get(f"/projects/{p_id}/flow-prompts")
    assert resp.status_code == 200
    data = resp.json()

    assert "manifest" in data
    manifest = data["manifest"]
    assert manifest["project_id"] == p_id
    assert manifest["total_scenes"] > 0

    scene_0 = manifest["scenes"][0]
    assert scene_0["aspect_ratio"] == "9:16"
    assert scene_0["requested_duration"] in ("4s", "8s")
    assert "no text" in scene_0["forbidden_artifacts"].lower()
    assert "9:16" in scene_0["exact_prompt"]

    # Verify durable file creation
    manifest_file = Path(data["manifest_path"])
    assert manifest_file.exists()
    assert len(data["scene_prompt_files"]) == manifest["total_scenes"]
    for sf in data["scene_prompt_files"]:
        assert Path(sf).exists()


def test_validate_flow_video_valid_9_16(tmp_path):
    clip = create_synthetic_mp4(tmp_path / "valid_flow.mp4", width=1080, height=1920, duration=4.0, add_motion=True)
    res = validate_flow_video(clip, target_scene_duration=4.0)

    assert res.status == ValidationStatus.VALIDATED
    assert res.source_width == 1080
    assert res.source_height == 1920
    assert res.source_aspect_ratio == "9:16"
    assert 3.9 <= res.source_duration_seconds <= 4.1
    assert not res.is_blank
    assert not res.is_frozen
    assert not res.is_corrupt
    assert len(res.sha256_checksum) == 64


def test_validate_flow_video_detects_blank_media(tmp_path):
    # Pure black static video
    black_clip = create_synthetic_mp4(tmp_path / "black.mp4", width=1080, height=1920, duration=3.0, color="black", add_motion=False)
    res = validate_flow_video(black_clip)

    assert res.status == ValidationStatus.REJECTED
    assert res.is_blank is True
    assert any("blank" in err.lower() for err in res.errors)


def test_validate_flow_video_detects_frozen_frames(tmp_path):
    # Solid blue static video (non-black, but zero frame delta)
    frozen_clip = create_synthetic_mp4(tmp_path / "frozen.mp4", width=1080, height=1920, duration=3.0, color="blue", add_motion=False)
    res = validate_flow_video(frozen_clip)

    assert res.status == ValidationStatus.REJECTED
    assert res.is_frozen is True
    assert any("frozen" in err.lower() for err in res.errors)


def test_validate_flow_video_flags_non_9_16_horizontal(tmp_path):
    # 16:9 horizontal clip
    horiz_clip = create_synthetic_mp4(tmp_path / "horiz.mp4", width=1920, height=1080, duration=3.0, add_motion=True)
    res = validate_flow_video(horiz_clip)

    # Must be marked REVIEW_REQUIRED with explicit warning about post-processing reframing
    assert res.status == ValidationStatus.REVIEW_REQUIRED
    assert res.source_aspect_ratio == "1920:1080"
    assert any("not native 9:16" in w for w in res.warnings)


def test_validate_flow_video_rejects_too_short(tmp_path):
    short_clip = create_synthetic_mp4(tmp_path / "short.mp4", width=1080, height=1920, duration=0.4, add_motion=True)
    res = validate_flow_video(short_clip)

    assert res.status == ValidationStatus.REJECTED
    assert any("too short" in err for err in res.errors)


def test_import_and_bind_flow_video_enforces_user_confirmation(setup_test_db, tmp_path):
    test_db, test_media, _ = setup_test_db
    p_id = create_project(title="Test", topic="Topic", target_audience="all", db_path=test_db)
    proj = get_project(p_id, db_path=test_db)
    scene_id = proj["scenes"][0]["id"]

    valid_clip = create_synthetic_mp4(tmp_path / "clip.mp4", width=1080, height=1920, duration=4.0)

    # Must raise if confirmed_by_user is False
    with pytest.raises(FlowValidationError, match="User confirmation is required"):
        import_and_bind_flow_video(
            project_id=p_id,
            scene_id=scene_id,
            source_file_path=valid_clip,
            confirmed_by_user=False,
            db_path=test_db,
            media_dir=test_media
        )


def test_import_and_bind_flow_video_invalidates_prior_approvals(setup_test_db, tmp_path):
    test_db, test_media, test_inbox = setup_test_db
    p_id = create_project(title="Test Invalidation", topic="Black Holes", target_audience="all", db_path=test_db)
    proj = get_project(p_id, db_path=test_db)
    scene_id = proj["scenes"][0]["id"]

    # Simulate an approved render
    import uuid
    r_id = create_render(p_id, "checksum123", "/path/video.mp4", db_path=test_db)
    create_approval(
        approval_id=str(uuid.uuid4()),
        render_id=r_id,
        checksum="checksum123",
        reviewer="human_reviewer",
        notes="Pre-approved",
        db_path=test_db
    )

    # Set project status to APPROVED
    conn = get_connection(test_db)
    conn.execute("UPDATE projects SET status = 'APPROVED', current_render_id = ? WHERE id = ?", (r_id, p_id))
    conn.commit()
    conn.close()

    # Import Flow video with user confirmation
    flow_clip = test_inbox / "my_flow_render.mp4"
    create_synthetic_mp4(flow_clip, width=1080, height=1920, duration=4.0, add_motion=True)

    bind_res = import_and_bind_flow_video(
        project_id=p_id,
        scene_id=scene_id,
        source_file_path=flow_clip,
        confirmed_by_user=True,
        db_path=test_db,
        media_dir=test_media
    )

    assert bind_res["success"] is True
    assert Path(bind_res["bound_path"]).exists()

    # Verify project reverted to STORYBOARD and approval was superseded
    updated_proj = get_project(p_id, db_path=test_db)
    assert updated_proj["status"] == "STORYBOARD"
    assert updated_proj["current_render_id"] is None

    conn = get_connection(test_db)
    appr = conn.execute("SELECT superseded_at FROM approvals WHERE render_id = ?", (r_id,)).fetchone()
    conn.close()
    assert appr["superseded_at"] is not None

    # Verify asset provenance record
    provenances = get_asset_provenances(p_id, db_path=test_db)
    assert len(provenances) == 1
    assert provenances[0]["asset_type"] == "FLOW_GENERATED"
    assert provenances[0]["rights_status"] == "VERIFIED_FREE"


def test_inbox_api_endpoints(setup_test_db):
    test_db, _, test_inbox = setup_test_db
    p_id = create_project(title="Test Inbox API", topic="Physics", target_audience="all", db_path=test_db)
    proj = get_project(p_id, db_path=test_db)
    scene_id = proj["scenes"][0]["id"]

    # Place a clip in inbox
    inbox_file = test_inbox / "flow_scene_01.mp4"
    create_synthetic_mp4(inbox_file, width=1080, height=1920, duration=4.0, add_motion=True)

    client = TestClient(app)

    # 1. List inbox files
    list_resp = client.get("/inbox/files")
    assert list_resp.status_code == 200
    files = list_resp.json()["files"]
    assert len(files) == 1
    assert files[0]["filename"] == "flow_scene_01.mp4"

    # 2. Bind inbox file to scene
    bind_resp = client.post(
        f"/projects/{p_id}/scenes/{scene_id}/bind-inbox-file",
        json={"filename": "flow_scene_01.mp4", "confirmed_by_user": True}
    )
    assert bind_resp.status_code == 200
    b_data = bind_resp.json()
    assert b_data["success"] is True
    assert b_data["validation"]["status"] == "VALIDATED"
    assert Path(b_data["bound_path"]).exists()


def test_render_fails_closed_when_flow_required_footage_missing(setup_test_db):
    test_db, test_media, _ = setup_test_db
    p_id = create_project(title="Cosmic Voids", topic="Space Voids", target_audience="curious", db_path=test_db)

    # Calling flow-prompts exports manifest and marks scenes as FLOW_REQUIRED in DB
    client = TestClient(app)
    resp = client.get(f"/projects/{p_id}/flow-prompts")
    assert resp.status_code == 200

    # Default render call without allow_placeholder_fallback flag (or False) must reject pre-flight
    resp = client.post(f"/projects/{p_id}/render")
    assert resp.status_code == 400
    assert "Required footage missing" in resp.json()["detail"]
    assert "Scene 1" in resp.json()["detail"]

    # Worker runner should also fail-closed if invoked directly with allow_placeholder_fallback=False
    runner = WorkerRunner(db_path=test_db)
    with pytest.raises(RuntimeError, match="Missing required footage"):
        runner.process_render_project({
            "project_id": p_id,
            "width": 360,
            "height": 640,
            "fps": 30,
            "enable_motion": False,
            "enable_video_ingest": True,
            "enable_transitions": False,
            "allow_placeholder_fallback": False
        })


def test_render_with_explicit_placeholder_fallback_is_flagged(setup_test_db):
    test_db, test_media, _ = setup_test_db
    p_id = create_project(title="Cosmic Voids Fallback", topic="Space Voids", target_audience="curious", db_path=test_db)
    client = TestClient(app)
    resp = client.get(f"/projects/{p_id}/flow-prompts")
    assert resp.status_code == 200

    # With allow_placeholder_fallback=true, API accepts job
    resp = client.post(f"/projects/{p_id}/render?allow_placeholder_fallback=true")
    assert resp.status_code == 200

    # Process through runner with allow_placeholder_fallback=True
    proj = get_project(p_id, db_path=test_db)
    short_scenes = [proj["scenes"][0]]
    short_scenes[0]["duration_seconds"] = 3.0
    update_project_storyboard(p_id, short_scenes, db_path=test_db)

    runner = WorkerRunner(db_path=test_db)
    result = runner.process_render_project({
        "project_id": p_id,
        "width": 360,
        "height": 640,
        "fps": 15,
        "enable_motion": False,
        "enable_video_ingest": False,
        "enable_transitions": False,
        "allow_placeholder_fallback": True
    })

    assert result["status"] == "SUCCESS"
    render_rec = get_render(result["render_id"], db_path=test_db)
    recipe = json.loads(render_rec["recipe_json"])
    assert recipe["contains_placeholders"] is True
    assert any(a["visual_source_type"] == "EXPLICIT_FALLBACK" for a in recipe["asset_manifest"])


def test_imported_flow_video_takes_precedence_in_render(setup_test_db, tmp_path):
    test_db, test_media, test_inbox = setup_test_db
    p_id = create_project(title="Real Footage Test", topic="Black Holes", target_audience="curious", db_path=test_db)
    proj = get_project(p_id, db_path=test_db)
    single_scene = [proj["scenes"][0]]
    single_scene[0]["duration_seconds"] = 3.0
    update_project_storyboard(p_id, single_scene, db_path=test_db)

    # Re-fetch project to get new scene ID generated by update_project_storyboard
    proj = get_project(p_id, db_path=test_db)
    target_scene = proj["scenes"][0]
    target_scene_id = target_scene["id"]

    # Calling flow-prompts marks scene as FLOW_REQUIRED
    client = TestClient(app)
    resp = client.get(f"/projects/{p_id}/flow-prompts")
    assert resp.status_code == 200

    # Import a real synthetic video clip into this scene
    clip = test_inbox / "real_flow_asset.mp4"
    create_synthetic_mp4(clip, width=1080, height=1920, duration=3.5, add_motion=True)

    bind_res = import_and_bind_flow_video(
        project_id=p_id,
        scene_id=target_scene_id,
        source_file_path=clip,
        confirmed_by_user=True,
        db_path=test_db,
        media_dir=test_media
    )
    assert bind_res["success"] is True

    # Now rendering with allow_placeholder_fallback=False MUST SUCCEED because real footage is present
    resp = client.post(f"/projects/{p_id}/render?allow_placeholder_fallback=false")
    assert resp.status_code == 200

    # Run the worker
    runner = WorkerRunner(db_path=test_db)
    result = runner.process_render_project({
        "project_id": p_id,
        "width": 360,
        "height": 640,
        "fps": 15,
        "enable_motion": False,
        "enable_video_ingest": False,
        "enable_transitions": False,
        "allow_placeholder_fallback": False
    })

    assert result["status"] == "SUCCESS"
    render_rec = get_render(result["render_id"], db_path=test_db)
    recipe = json.loads(render_rec["recipe_json"])
    assert recipe["contains_placeholders"] is False
    assert len(recipe["asset_manifest"]) == 1
    assert recipe["asset_manifest"][0]["visual_source_type"] == "FLOW_GENERATED"
    assert recipe["asset_manifest"][0]["sha256_checksum"] == bind_res["validation"]["sha256_checksum"]

