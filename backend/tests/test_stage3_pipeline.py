"""Automated test suite for Stage 3: Visual Assembly, Ken Burns Motion, Audio Mix, and QA."""

import pytest
import sqlite3
import subprocess
from pathlib import Path
from starlette.testclient import TestClient

from backend.app.config import DB_PATH, MEDIA_DIR
from backend.app.db.connection import init_db, get_connection
from backend.app.db.repository import (
    create_project,
    get_project,
    save_asset_provenance,
    get_asset_provenances,
    save_editorial_review,
    get_editorial_review,
    update_project_storyboard,
    create_approval
)
from backend.app.media.visual_adapters import (
    VisualAssetResult,
    UserProvidedAssetAdapter,
    ProceduralGraphicAdapter,
    CompositeVisualResolver
)
from backend.app.media.subtitles import (
    split_into_phrase_chunks,
    generate_ass_subtitles,
    format_timestamp
)
from backend.app.media.audio_mixer import AudioMixer
from backend.app.media.ffmpeg_composer import FFmpegComposer, FFmpegCompositionError
from backend.app.media.qa import TechnicalQA
from backend.app.media.editorial_qa import EditorialQA
from backend.app.worker.runner import WorkerRunner
from backend.app.api.main import app

@pytest.fixture
def stage3_env(tmp_path, monkeypatch):
    test_db = tmp_path / "test_stage3.db"
    test_media = tmp_path / "media"
    test_media.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("backend.app.config.DB_PATH", test_db)
    monkeypatch.setattr("backend.app.config.MEDIA_DIR", test_media)
    monkeypatch.setattr("backend.app.db.repository.DB_PATH", test_db)
    monkeypatch.setattr("backend.app.db.connection.DB_PATH", test_db)
    monkeypatch.setattr("backend.app.api.main.DB_PATH", test_db)
    monkeypatch.setattr("backend.app.media.assets.MEDIA_DIR", test_media)
    monkeypatch.setattr("backend.app.media.visual_adapters.MEDIA_DIR", test_media)

    init_db(test_db)
    return {"db": test_db, "media": test_media}

# --- Test 1: Procedural Graphics Adapter & Themes ---
def test_procedural_graphics_generation(stage3_env):
    adapter = ProceduralGraphicAdapter()
    scene = {
        "scene_index": 0,
        "scene_title": "Gravity Curvature",
        "narration_text": "Massive objects warp spacetime itself."
    }
    res = adapter.resolve_asset("proj_1", scene, "gravity spacetime", width=720, height=1280)
    assert res is not None
    assert res.asset_type == "PROCEDURAL"
    assert res.local_path.exists()
    assert res.local_path.stat().st_size > 5000
    assert len(res.sha256_checksum) == 64
    assert res.license == "CC0 (Procedural Engine Generated)"

# --- Test 2: Asset Provenance Persistence & Priority ---
def test_asset_provenance_persistence(stage3_env):
    db = stage3_env["db"]
    proj_id = create_project(topic="Relativity", target_duration=15.0, db_path=db)

    # Insert a real fact claim first to satisfy foreign key constraint
    from backend.app.db.repository import create_fact_claim
    claim_id = create_fact_claim(
        claim_id="claim_001",
        claim_text="Gravity slows ticking clocks.",
        quote_excerpt="Clocks tick slower near mass.",
        project_id=proj_id,
        evidence_status="VERIFIED",
        db_path=db
    )

    prov_id = save_asset_provenance(
        provenance_id="prov_test_1",
        project_id=proj_id,
        scene_index=0,
        asset_type="NASA",
        local_path="/tmp/fake_nasa.jpg",
        sha256_checksum="a" * 64,
        source_url="https://images.nasa.gov/123",
        author="NASA / JPL-Caltech",
        license="NASA Open Media",
        attribution_text="NASA / JPL-Caltech",
        associated_claim_id=claim_id,
        db_path=db
    )
    assert prov_id == "prov_test_1"

    records = get_asset_provenances(proj_id, db_path=db)
    assert len(records) == 1
    assert records[0]["author"] == "NASA / JPL-Caltech"
    assert records[0]["license"] == "NASA Open Media"
    assert records[0]["associated_claim_id"] == "claim_001"

# --- Test 3: Subtitle Phrase Chunking & Mobile Safe Margins ---
def test_subtitle_phrase_chunking_and_safe_margins(stage3_env):
    media = stage3_env["media"]
    text = "Why does time move slightly slower at sea level than on top of a mountain?"
    chunks = split_into_phrase_chunks(text, max_words_per_chunk=3)
    assert len(chunks) >= 3
    # Check that words are preserved
    reconstructed = " ".join(chunks)
    assert reconstructed == text

    # Test Hindi Unicode preservation
    hindi_text = "समय समुद्र तल पर धीमा क्यों चलता है?"
    hindi_chunks = split_into_phrase_chunks(hindi_text, max_words_per_chunk=3)
    assert len(hindi_chunks) >= 2
    assert "समय" in hindi_chunks[0]

    # Test ASS Subtitle Generation for 1080x1920
    scenes = [
        {"duration_seconds": 4.0, "narration_text": text, "caption_text": text}
    ]
    sub_path = media / "test_1080.ass"
    generate_ass_subtitles(scenes, sub_path, width=1080, height=1920)
    assert sub_path.exists()
    content = sub_path.read_text(encoding="utf-8")
    # Verify 1080p safe margin (margin_v >= 240)
    assert ",240,1" in content
    assert "PlayResX: 1080" in content
    assert "PlayResY: 1920" in content

# --- Test 4: Audio Mixing & Sidechain Ducking ---
def test_audio_mixer_ducking_and_loudness(stage3_env):
    media = stage3_env["media"]
    mixer = AudioMixer()

    speech_wav = media / "speech.wav"
    music_wav = media / "music.wav"
    out_mix = media / "mixed.aac"

    # Synthetic 3s speech & 4s music
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=f=440:d=3", "-c:a", "pcm_s16le", str(speech_wav)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=f=220:d=4", "-c:a", "pcm_s16le", str(music_wav)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    res = mixer.mix_and_duck(
        speech_path=speech_wav,
        output_path=out_mix,
        bg_music_path=music_wav,
        target_lufs=-16.0
    )
    assert out_mix.exists()
    assert res["mode"] == "sidechain_ducked"
    assert -18.5 <= res["integrated_lufs"] <= -13.5
    assert res["true_peak_dbfs"] <= -0.5

# --- Test 5: Ken Burns Motion Presets & FFmpeg Composer ---
def test_ken_burns_motion_presets(stage3_env):
    media = stage3_env["media"]
    img = media / "test_img.png"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=navy:s=720x1280:d=1", "-frames:v", "1", str(img)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    scenes = [
        {"visual_asset_path": str(img), "duration_seconds": 2.0, "motion_preset": "zoom_in"},
        {"visual_asset_path": str(img), "duration_seconds": 2.0, "motion_preset": "pan_left"}
    ]
    out_mp4 = media / "motion_test.mp4"
    composer = FFmpegComposer(width=720, height=1280, fps=30)
    res = composer.render(scenes=scenes, output_path=out_mp4, enable_motion=True)

    assert out_mp4.exists()
    assert len(res["render_checksum"]) == 64

    # Technical QA verification
    qa = TechnicalQA.inspect_and_verify(out_mp4, expected_width=720, expected_height=1280, expected_duration=4.0, audio_expected=False)
    assert qa["passed"] is True, f"QA failed: {qa['failure_reasons']}"
    assert abs(qa["details"]["duration_seconds"] - 4.0) <= 0.2

# --- Test 6: Technical QA Anomaly Detection ---
def test_technical_qa_anomaly_detection(stage3_env):
    media = stage3_env["media"]
    # 1. Non-existent file
    res = TechnicalQA.inspect_and_verify(media / "non_existent.mp4")
    assert res["passed"] is False

    # 2. Corrupt/Empty file
    corrupt = media / "corrupt.mp4"
    corrupt.write_bytes(b"")
    res = TechnicalQA.inspect_and_verify(corrupt)
    assert res["passed"] is False
    assert "empty" in res["failure_reasons"][0]

# --- Test 7: Editorial QA Evaluation & Actionable Warnings ---
def test_editorial_qa_evaluation(stage3_env):
    project = {"narration_mode": "local_tts", "topic": "General Relativity"}
    # Weak scenes: empty hook, identical visual, sluggish pacing, no payoff
    scenes = [
        {"scene_index": 0, "narration_text": "Today we will talk about physics.", "duration_seconds": 9.0, "visual_asset_path": "a.png"},
        {"scene_index": 1, "narration_text": "This is another slide.", "duration_seconds": 9.0, "visual_asset_path": "a.png"}
    ]
    eval_res = EditorialQA.evaluate(project, scenes, asset_provenances=[])
    assert eval_res["score"] < 80
    assert eval_res["overall_status"] in ("WARNING", "FAILED")
    categories = [w["category"] for w in eval_res["warnings"]]
    assert "HOOK" in categories
    assert "RELEVANCE" in categories
    assert "PACING" in categories

# --- Test 8: End-to-End Pipeline Render with Motion & Audio Mix ---
def test_e2e_stage3_pipeline_render(stage3_env):
    db = stage3_env["db"]
    media = stage3_env["media"]

    # Create project with 2 scenes and local TTS narration
    proj_id = create_project(
        topic="Time Dilation",
        title="Why Altitude Changes Time",
        content_format="explainer",
        narration_mode="local_tts",
        narration_voice="af_bella",
        target_duration=8.0,
        scenes=[
            {
                "scene_index": 0,
                "scene_title": "The Gravity Mystery",
                "narration_text": "Why does time move slower at sea level?",
                "caption_text": "Why Time Moves Slower",
                "duration_seconds": 4.0,
                "motion_preset": "zoom_in"
            },
            {
                "scene_index": 1,
                "scene_title": "Spacetime Warp",
                "narration_text": "Earth mass curves spacetime fabric, slowing every ticking clock.",
                "caption_text": "Spacetime Curves Clocks",
                "duration_seconds": 4.0,
                "motion_preset": "zoom_out"
            }
        ],
        db_path=db
    )

    worker = WorkerRunner(db_path=db)
    result = worker.process_render_project({
        "project_id": proj_id,
        "width": 720,
        "height": 1280,
        "enable_motion": True,
        "enable_bg_music": True
    })

    assert result["status"] == "SUCCESS"
    assert result["qa_status"] == "PASSED"
    assert "render_checksum" in result
    out_mp4 = Path(result["file_path"])
    assert out_mp4.exists()

    # Verify editorial review was saved and linked to project
    review = get_editorial_review(proj_id, db_path=db)
    assert review is not None
    assert "score" in review
    assert review["score"] >= 70

    # Verify asset provenance was recorded
    provenances = get_asset_provenances(proj_id, db_path=db)
    assert len(provenances) == 2
    assert all(p["asset_type"] == "PROCEDURAL" for p in provenances)

# --- Test 9: Storyboard Edit Invalidates Render Approval ---
def test_storyboard_edit_invalidates_approval(stage3_env):
    db = stage3_env["db"]
    proj_id = create_project(
        topic="Physics",
        narration_mode="silent",
        target_duration=5.0,
        scenes=[{"scene_index": 0, "narration_text": "Beat 1", "duration_seconds": 5.0}],
        db_path=db
    )
    worker = WorkerRunner(db_path=db)
    res = worker.process_render_project({"project_id": proj_id, "width": 720, "height": 1280})
    render_id = res["render_id"]
    checksum = res["render_checksum"]

    # Approve render
    create_approval("app_01", render_id, checksum, "human_reviewer", "APPROVED", db_path=db)
    p = get_project(proj_id, db_path=db)
    assert p["active_approval"] is not None

    # Edit storyboard
    update_project_storyboard(proj_id, [
        {"scene_index": 0, "narration_text": "Edited Beat 1", "duration_seconds": 6.0}
    ], db_path=db)

    # Verify approval was superseded/invalidated
    p_after = get_project(proj_id, db_path=db)
    assert p_after["active_approval"] is None
    assert p_after["status"] == "STORYBOARD"
