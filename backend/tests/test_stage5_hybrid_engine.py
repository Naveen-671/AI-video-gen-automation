"""
Comprehensive unit and integration tests for Stage 5 Hybrid High-Craft Visual Engine:
- NASA and Wikimedia video ingestion adapters with licensing and size guardrails
- FFprobe metadata extraction
- VideoReframer vertical 1080x1920 cropping with configurable anchors
- SceneVisualSelector modality classification and fail-closed fallback
- FFmpegComposer xfade transitions with handle extension duration preservation
- Full worker render execution with transitions and hybrid visual assets
"""

import hashlib
import json
import subprocess
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from backend.app.config import DB_PATH, MEDIA_DIR
from backend.app.db.connection import init_db, get_connection
from backend.app.db.repository import (
    create_project,
    update_project_storyboard,
    save_asset_provenance,
    get_asset_provenances,
    get_render
)
from backend.app.media.ffmpeg_composer import FFmpegComposer
from backend.app.media.reframing import VideoReframer
from backend.app.media.video_adapters import (
    NASAVideoAdapter,
    WikimediaVideoAdapter,
    probe_video_metadata,
    MAX_VIDEO_BYTES
)
from backend.app.media.visual_selector import SceneVisualSelector
from backend.app.worker.runner import WorkerRunner


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path):
    test_db = tmp_path / "test_stage5.db"
    init_db(test_db)
    return test_db


def create_synthetic_mp4(path: Path, width: int = 640, height: int = 360, duration: float = 2.0, fps: int = 30):
    """Generates a small valid MP4 video using FFmpeg testsrc for testing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"testsrc=size={width}x{height}:rate={fps}",
        "-t", f"{duration:.2f}",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-pix_fmt", "yuv420p",
        str(path)
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    return path


def test_probe_video_metadata(tmp_path):
    clip = create_synthetic_mp4(tmp_path / "test_probe.mp4", width=320, height=240, duration=1.5)
    meta = probe_video_metadata(clip)
    assert meta["width"] == 320
    assert meta["height"] == 240
    assert 1.4 <= meta["duration"] <= 1.6
    assert "h264" in meta["codec"]


def test_video_reframer_anchors(tmp_path):
    src_clip = create_synthetic_mp4(tmp_path / "source_land.mp4", width=1280, height=720, duration=2.0)
    reframer = VideoReframer()

    for anchor in ["center", "top", "bottom"]:
        out_clip = tmp_path / f"reframed_{anchor}.mp4"
        reframer.reframe_clip(
            input_video_path=src_clip,
            output_clip_path=out_clip,
            duration=3.0,
            anchor=anchor,
            target_w=1080,
            target_h=1920
        )
        assert out_clip.exists()
        meta = probe_video_metadata(out_clip)
        assert meta["width"] == 1080
        assert meta["height"] == 1920
        assert 2.9 <= meta["duration"] <= 3.1


def test_nasa_video_adapter_search_and_rights_guardrail(tmp_path):
    adapter = NASAVideoAdapter()
    project_id = f"proj_{uuid.uuid4().hex[:8]}"

    # Mock NASA search response: 1 proprietary item (rejected), 1 open public domain item
    search_response_data = {
        "collection": {
            "items": [
                {
                    "data": [{
                        "nasa_id": "PROPRIETARY_CLIP",
                        "title": "Documentary Clip",
                        "description": "Copyright 2024 Discovery Inc. All rights reserved.",
                        "center": "HQ"
                    }]
                },
                {
                    "data": [{
                        "nasa_id": "OPEN_ORBIT_CLIP",
                        "title": "Earth from Orbit",
                        "description": "Public domain footage captured from ISS.",
                        "center": "JSC"
                    }]
                }
            ]
        }
    }

    manifest_response_data = {
        "collection": {
            "items": [
                {"href": "https://example.com/OPEN_ORBIT_CLIP~orig.mp4"},
                {"href": "https://example.com/OPEN_ORBIT_CLIP~medium.mp4"}
            ]
        }
    }

    # Generate real small mp4 bytes to serve as mock stream
    dummy_mp4 = create_synthetic_mp4(tmp_path / "dummy_stream.mp4", width=320, height=240, duration=1.0)
    dummy_bytes = dummy_mp4.read_bytes()

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client

    def get_side_effect(url, *args, **kwargs):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        if "search?" in url:
            mock_resp.json.return_value = search_response_data
        elif "asset/OPEN_ORBIT_CLIP" in url:
            mock_resp.json.return_value = manifest_response_data
        return mock_resp

    mock_client.get.side_effect = get_side_effect

    # Mock stream response
    class MockStreamContext:
        def __enter__(self):
            resp = MagicMock()
            resp.status_code = 200
            resp.headers = {"content-type": "video/mp4", "content-length": str(len(dummy_bytes))}
            resp.iter_bytes.return_value = [dummy_bytes]
            return resp
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_client.stream.return_value = MockStreamContext()

    with patch("httpx.Client", return_value=mock_client):
        result = adapter.search_video(project_id, "Earth orbit ISS")

    assert result is not None
    assert result.asset_type == "NASA"
    assert result.rights_status == "PUBLIC_DOMAIN"
    assert "OPEN_ORBIT_CLIP" in result.source_url
    assert result.local_path.exists()
    assert result.original_width == 320
    assert result.original_height == 240


def test_nasa_video_adapter_size_limit_rejection(tmp_path):
    adapter = NASAVideoAdapter(max_download_bytes=1000)
    dest_path = tmp_path / "oversize.mp4"

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    class MockStreamContext:
        def __enter__(self):
            resp = MagicMock()
            resp.status_code = 200
            resp.headers = {"content-type": "video/mp4", "content-length": "5000"}
            return resp
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_client.stream.return_value = MockStreamContext()

    with pytest.raises(ValueError, match="exceeds limit"):
        adapter._stream_download_video("https://example.com/huge.mp4", dest_path, mock_client)


def test_wikimedia_video_adapter_license_filtering(tmp_path):
    adapter = WikimediaVideoAdapter()
    project_id = f"proj_{uuid.uuid4().hex[:8]}"

    # Mock 1 rejected NC license, 1 accepted CC-BY-SA license
    wiki_response_data = {
        "query": {
            "pages": {
                "101": {
                    "title": "File:Restricted.webm",
                    "imageinfo": [{
                        "url": "https://example.com/restricted.webm",
                        "size": 5000,
                        "mime": "video/webm",
                        "extmetadata": {"LicenseShortName": {"value": "CC-BY-NC-4.0"}}
                    }]
                },
                "102": {
                    "title": "File:OpenSatellite.webm",
                    "imageinfo": [{
                        "url": "https://example.com/satellite.webm",
                        "size": 5000,
                        "mime": "video/webm",
                        "extmetadata": {
                            "LicenseShortName": {"value": "CC-BY-SA-4.0"},
                            "Artist": {"value": "<b>ESA/Hubble</b>"}
                        }
                    }]
                }
            }
        }
    }

    dummy_webm = create_synthetic_mp4(tmp_path / "dummy_wiki.mp4", width=320, height=240, duration=1.0)
    dummy_bytes = dummy_webm.read_bytes()

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = wiki_response_data
    mock_client.get.return_value = mock_resp

    class MockStreamContext:
        def __enter__(self):
            resp = MagicMock()
            resp.status_code = 200
            resp.headers = {"content-type": "video/webm"}
            resp.iter_bytes.return_value = [dummy_bytes]
            return resp
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_client.stream.return_value = MockStreamContext()

    with patch("httpx.Client", return_value=mock_client):
        result = adapter.search_video(project_id, "satellite orbit")

    assert result is not None
    assert result.asset_type == "WIKIMEDIA"
    assert "CC-BY-SA" in result.license
    assert result.author == "ESA/Hubble"
    assert result.rights_status == "VERIFIED_FREE"


def test_scene_visual_selector_classification_and_fallbacks(setup_test_db, tmp_path):
    selector = SceneVisualSelector(db_path=setup_test_db)
    project_id = create_project(
        topic="Gravitational Time Dilation",
        title="Gravitational Time Dilation Test",
        db_path=setup_test_db
    )

    # Procedural beat: formulas / atomic clocks
    proc_scene = {
        "scene_index": 0,
        "scene_title": "Atomic Clock Verification",
        "narration": "In 2022, NIST optical lattice atomic clocks measured time dilation across a millimeter.",
        "visual_description": "Einstein relativity formula and precision measurement diagram."
    }
    modality = selector.classify_scene_modality(proc_scene, "Gravitational Time Dilation")
    assert modality == "PROCEDURAL"

    # Observational beat: orbit / cosmic
    obs_scene = {
        "scene_index": 1,
        "scene_title": "Earth from Orbit",
        "narration": "Satellites orbiting high above Earth experience less gravitational curvature.",
        "visual_description": "Curving blue Earth seen from satellite orbit in space."
    }
    modality_obs = selector.classify_scene_modality(obs_scene, "Gravitational Time Dilation")
    assert modality_obs == "VIDEO"

    # Test procedural resolution creates valid 1080x1920 image and records provenance
    res = selector.resolve_visual_for_scene(
        project_id=project_id,
        scene=proc_scene,
        topic="Gravitational Time Dilation",
        duration=3.0,
        enable_video=True
    )
    assert res.local_path.exists()
    assert res.asset_type == "PROCEDURAL"
    assert res.selection_reason is not None

    provs = get_asset_provenances(project_id, setup_test_db)
    assert len(provs) >= 1
    assert provs[0]["media_type"] == "image"
    assert "Mathematical" in provs[0]["selection_reason"]


def test_ffmpeg_composer_xfade_transitions_duration_preservation(tmp_path):
    clip1 = create_synthetic_mp4(tmp_path / "clip1.mp4", width=1080, height=1920, duration=4.0)
    clip2 = create_synthetic_mp4(tmp_path / "clip2.mp4", width=1080, height=1920, duration=4.0)

    scenes = [
        {"visual_asset_path": str(clip1), "duration_seconds": 3.0, "motion_preset": "static"},
        {"visual_asset_path": str(clip2), "duration_seconds": 3.0, "motion_preset": "static"}
    ]

    out_mp4 = tmp_path / "xfade_render.mp4"
    composer = FFmpegComposer(width=1080, height=1920, fps=30)
    result = composer.render(
        scenes=scenes,
        output_path=out_mp4,
        enable_transitions=True,
        transition_duration=0.5
    )

    assert Path(result["output_path"]).exists()
    assert result["enable_transitions"] is True

    # Probe duration: MUST be 6.0s (3.0 + 3.0), NOT 5.5s!
    meta = probe_video_metadata(out_mp4)
    assert 5.95 <= meta["duration"] <= 6.05


def test_ffmpeg_composer_short_scene_transition_fallback(tmp_path):
    clip1 = create_synthetic_mp4(tmp_path / "clip_short.mp4", width=1080, height=1920, duration=2.0)
    clip2 = create_synthetic_mp4(tmp_path / "clip_norm.mp4", width=1080, height=1920, duration=4.0)

    # Scene 1 is 0.8s, which is < 2 * 0.5s = 1.0s. Must fall back to jump cut (concat)
    scenes = [
        {"visual_asset_path": str(clip1), "duration_seconds": 0.8, "motion_preset": "static"},
        {"visual_asset_path": str(clip2), "duration_seconds": 3.0, "motion_preset": "static"}
    ]

    out_mp4 = tmp_path / "short_fallback_render.mp4"
    composer = FFmpegComposer(width=1080, height=1920, fps=30)
    result = composer.render(
        scenes=scenes,
        output_path=out_mp4,
        enable_transitions=True,
        transition_duration=0.5
    )

    assert Path(result["output_path"]).exists()
    # verify it gracefully rendered via concat
    meta = probe_video_metadata(out_mp4)
    assert 3.7 <= meta["duration"] <= 3.9


def test_end_to_end_worker_hybrid_render(setup_test_db, tmp_path):
    project_id = create_project(
        title="Gravitational Time Dilation Benchmark",
        topic="Gravitational Time Dilation",
        narration_mode="silent",
        db_path=setup_test_db
    )

    # Scene 0: Observational beat (synthetic mp4)
    clip_vid = create_synthetic_mp4(tmp_path / "orbit_beat.mp4", width=640, height=360, duration=3.5)
    scenes = [
        {
            "scene_index": 0,
            "scene_title": "Earth Orbit Beat",
            "narration_text": "Clocks on GPS satellites tick faster than clocks on the ground.",
            "duration_seconds": 3.0,
            "visual_description": "Orbiting satellite over Earth.",
            "visual_asset_path": str(clip_vid),
            "motion_preset": "static"
        },
        {
            "scene_index": 1,
            "scene_title": "Atomic Clock Equation Beat",
            "narration_text": "Einstein proved gravity curves spacetime. NIST measured it across one millimeter.",
            "duration_seconds": 3.0,
            "visual_description": "NIST atomic clock formula millimeter diagram.",
            "motion_preset": "static"
        }
    ]
    update_project_storyboard(project_id, scenes, db_path=setup_test_db)

    runner = WorkerRunner(db_path=setup_test_db)
    render_result = runner.process_render_project({
        "project_id": project_id,
        "width": 720,
        "height": 1280,
        "fps": 30,
        "enable_motion": True,
        "enable_video_ingest": True,
        "enable_transitions": True,
        "transition_duration": 0.5
    })

    assert render_result["status"] == "SUCCESS"
    assert "render_checksum" in render_result
    assert Path(render_result["file_path"]).exists()

    # Verify render record in DB
    render_rec = get_render(render_result["render_id"], setup_test_db)
    assert render_rec is not None
    recipe = json.loads(render_rec["recipe_json"])
    assert recipe["enable_transitions"] is True
    assert recipe["enable_video_ingest"] is True

    # Check that provenance records contain extended columns
    provs = get_asset_provenances(project_id, setup_test_db)
    assert len(provs) >= 1
    for p in provs:
        assert "rights_status" in p
        assert "crop_transform" in p
        assert "selection_reason" in p
