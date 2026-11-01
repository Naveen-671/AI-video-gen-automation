"""Unit and integration tests for Phase 2B local Kokoro TTS integration and pipeline."""

import os
import uuid
import hashlib
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from backend.app.api.main import app
from backend.app.db.connection import init_db, get_connection
from backend.app.db.repository import (
    create_project,
    get_project,
    create_render,
    set_project_render,
    create_approval,
    update_project_narration,
    update_project_storyboard
)
from backend.app.media.narration import (
    LocalTTSAdapter,
    SilentNarrationAdapter,
    ManualAudioAdapter,
    get_narration_adapter,
    NarrationAdapterError
)
from backend.app.worker.runner import WorkerRunner
from backend.app.media.qa import TechnicalQA

client = TestClient(app)


@pytest.fixture
def test_db(tmp_path: Path):
    db_file = tmp_path / "test_tts.db"
    init_db(db_file)
    return db_file


def test_kokoro_valid_generation_english(tmp_path: Path):
    """Verifies that Kokoro synthesizes valid English speech with deterministic checksum."""
    adapter = LocalTTSAdapter()
    out_wav = tmp_path / "test_en.wav"
    
    meta = adapter.synthesize(
        text="The mysteries of black holes continue to challenge astrophysicists worldwide.",
        output_path=out_wav,
        voice="af_bella",
        speed=1.0,
        lang="en-us"
    )

    assert out_wav.exists()
    assert out_wav.stat().st_size > 0
    assert meta["duration"] > 2.0
    assert meta["sample_rate"] == 24000
    assert meta["channels"] == 1
    assert meta["voice"] == "af_bella"

    # Verify checksum matches disk file
    hasher = hashlib.sha256()
    with out_wav.open("rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    assert meta["checksum"] == hasher.hexdigest()


def test_kokoro_valid_generation_hindi(tmp_path: Path):
    """Verifies that Kokoro synthesizes Hindi speech using hf_alpha."""
    adapter = LocalTTSAdapter()
    out_wav = tmp_path / "test_hi.wav"
    
    meta = adapter.synthesize(
        text="नमस्ते, यह ब्रह्मांड के रहस्यों की खोज है।",
        output_path=out_wav,
        voice="hf_alpha",
        speed=1.0,
        lang="hi"
    )

    assert out_wav.exists()
    assert out_wav.stat().st_size > 0
    assert meta["duration"] > 1.5
    assert meta["voice"] == "hf_alpha"
    assert meta["lang"] == "hi"


def test_kokoro_empty_text_rejection(tmp_path: Path):
    """Empty or whitespace text must fail-closed immediately without inference."""
    adapter = LocalTTSAdapter()
    out_wav = tmp_path / "empty.wav"

    with pytest.raises(NarrationAdapterError) as exc_info:
        adapter.synthesize(text="   ", output_path=out_wav)
    assert "input text is empty" in str(exc_info.value)
    assert not out_wav.exists()


def test_kokoro_unsupported_voice_rejection(tmp_path: Path):
    """Requesting an invalid or nonexistent voice must raise NarrationAdapterError."""
    adapter = LocalTTSAdapter()
    out_wav = tmp_path / "bad_voice.wav"

    with pytest.raises(NarrationAdapterError) as exc_info:
        adapter.synthesize(
            text="Hello world.",
            output_path=out_wav,
            voice="nonexistent_robot_voice"
        )
    assert "Unsupported voice" in str(exc_info.value)
    assert not out_wav.exists()


def test_kokoro_missing_model_files_fail_closed(tmp_path: Path):
    """Missing model or voice file must fail-closed with clear error and no cloud fallback."""
    bad_adapter = LocalTTSAdapter(
        model_path=tmp_path / "nonexistent.onnx",
        voices_path=tmp_path / "nonexistent.bin"
    )

    with pytest.raises(NarrationAdapterError) as exc_info:
        bad_adapter.synthesize(text="Fail closed test.", output_path=tmp_path / "test.wav")
    assert "not found at" in str(exc_info.value)


def test_kokoro_speed_bounds(tmp_path: Path):
    """Speeds outside 0.5 to 2.0 must be rejected."""
    adapter = LocalTTSAdapter()
    with pytest.raises(NarrationAdapterError) as exc_info:
        adapter.synthesize(text="Speed test.", output_path=tmp_path / "speed.wav", speed=3.5)
    assert "out of valid range" in str(exc_info.value)


def test_adapter_factory_modes():
    """Verifies that get_narration_adapter preserves silent and manual_audio while supporting local_tts."""
    silent = get_narration_adapter("silent")
    assert isinstance(silent, SilentNarrationAdapter)

    manual = get_narration_adapter("manual_audio")
    assert isinstance(manual, ManualAudioAdapter)

    local = get_narration_adapter("local_tts")
    assert isinstance(local, LocalTTSAdapter)

    with pytest.raises(ValueError):
        get_narration_adapter("cloud_polly")  # Disallowed cloud provider


def test_prepare_audio_padding(tmp_path: Path):
    """prepare_audio pads trailing silence so total audio matches target Short duration."""
    adapter = LocalTTSAdapter()
    out_wav = tmp_path / "padded.wav"
    target_duration = 6.0

    result_path = adapter.prepare_audio(
        duration_seconds=target_duration,
        output_path=out_wav,
        text="Brief note.",
        voice="af_bella",
        pad_to_duration=True
    )

    assert result_path.exists()
    import soundfile as sf
    data, sr = sf.read(str(result_path))
    actual_dur = len(data) / float(sr)
    assert actual_dur >= target_duration - 0.05


def test_narration_change_invalidates_render_approval(test_db: Path):
    """Modifying narration mode or voice supersedes any existing render approvals (ADR-02 / ADR-04)."""
    proj_id = create_project(
        topic="Narration Invalidation Test",
        narration_mode="silent",
        db_path=test_db
    )

    # Simulate render and approved approval
    render_id = str(uuid.uuid4())
    checksum = "sha256_mock_render_tts_invalidation"
    create_render(render_id, checksum=checksum, recipe_json="{}", project_id=proj_id, db_path=test_db)
    set_project_render(proj_id, render_id, status="APPROVED", db_path=test_db)
    
    app_id = str(uuid.uuid4())
    create_approval(app_id, render_id=render_id, checksum=checksum, status="APPROVED", db_path=test_db)

    # Verify project has render and approval active
    proj = get_project(proj_id, db_path=test_db)
    assert proj["active_approval"]["status"] == "APPROVED"

    # Now update narration settings to local_tts with af_bella
    success = update_project_narration(
        project_id=proj_id,
        narration_mode="local_tts",
        narration_voice="af_bella",
        db_path=test_db
    )
    assert success is True

    # Check that approval was superseded and current_render_id was cleared
    proj_after = get_project(proj_id, db_path=test_db)
    assert proj_after["current_render_id"] is None
    assert proj_after["active_approval"] is None

    conn = get_connection(test_db)
    try:
        app_row = conn.execute("SELECT status, superseded_at FROM approvals WHERE id = ?", (app_id,)).fetchone()
        assert app_row["superseded_at"] is not None
    finally:
        conn.close()


def test_api_tts_voices_endpoint():
    """FastAPI GET /tts/voices returns all available Kokoro voices."""
    response = client.get("/tts/voices")
    assert response.status_code == 200
    data = response.json()
    assert "voices" in data
    voices = data["voices"]
    assert len(voices) >= 50
    assert "af_bella" in voices
    assert "hf_alpha" in voices


def test_e2e_local_tts_pipeline_render(test_db: Path, tmp_path: Path):
    """End-to-end test: creates project with local_tts narration, runs worker render, validates MP4 & audio."""
    proj_id = create_project(
        topic="Gravity Waves",
        title="What Are Gravitational Waves?",
        target_duration=9.0,
        narration_mode="local_tts",
        narration_voice="af_bella",
        scenes=[
            {
                "scene_index": 0,
                "scene_title": "The Cosmic Ripple",
                "narration_text": "Gravitational waves are ripples in the fabric of spacetime itself.",
                "caption_text": "Ripples in Spacetime",
                "duration_seconds": 4.5
            },
            {
                "scene_index": 1,
                "scene_title": "Massive Collisions",
                "narration_text": "They are unleashed when massive black holes collide in deep space.",
                "caption_text": "Colliding Black Holes",
                "duration_seconds": 4.5
            }
        ],
        db_path=test_db
    )

    worker = WorkerRunner(db_path=test_db)
    result = worker.process_render_project(proj_id)

    assert result["qa_status"] == "PASSED"
    assert "render_checksum" in result
    out_mp4 = Path(result["file_path"])
    assert out_mp4.exists()
    assert out_mp4.stat().st_size > 0

    # Inspect rendered video with TechnicalQA
    qa_res = TechnicalQA.inspect_and_verify(
        video_path=out_mp4,
        expected_width=720,
        expected_height=1280,
        expected_duration=9.0,
        audio_expected=True
    )
    assert qa_res["passed"] is True, f"QA failed: {qa_res['failure_reasons']}"
    assert qa_res["details"]["audio_codec"] == "aac"
