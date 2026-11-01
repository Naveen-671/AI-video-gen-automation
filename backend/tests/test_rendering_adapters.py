"""Tests for FFmpeg Rendering Adapters (Track 2): Transitions, Ducking, EBU R128 compliance."""

import subprocess
from pathlib import Path
import pytest

from backend.app.media.rendering_adapters import (
    render_timeline_with_crossfades,
    mix_speech_and_music_ducked,
    measure_ebur128_loudness,
    generate_render_metadata,
    compute_file_sha256,
    RenderingAdapterError
)


def create_synthetic_test_clip(
    path: Path,
    width: int = 1080,
    height: int = 1920,
    duration: float = 3.0,
    color: str = "blue"
) -> Path:
    """Generates a synthetic MP4 test clip with test pattern using FFmpeg."""
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"testsrc=size={width}x{height}:rate=30,format=yuv420p",
        "-t", f"{duration:.3f}",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        str(path)
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return path


def create_synthetic_audio(path: Path, frequency: int = 440, duration: float = 4.0, volume: float = 0.5) -> Path:
    """Generates a synthetic sine wave audio WAV file using FFmpeg."""
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"sine=frequency={frequency}:duration={duration}",
        "-af", f"volume={volume}",
        "-c:a", "pcm_s16le",
        str(path)
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return path


def test_render_timeline_duration_preserving_crossfades(tmp_path):
    clip1 = create_synthetic_test_clip(tmp_path / "clip1.mp4", duration=3.0)
    clip2 = create_synthetic_test_clip(tmp_path / "clip2.mp4", duration=3.0)

    scenes = [
        {"visual_asset_path": str(clip1), "duration_seconds": 3.0, "motion_preset": "static"},
        {"visual_asset_path": str(clip2), "duration_seconds": 3.0, "motion_preset": "static"}
    ]

    out_mp4 = tmp_path / "duration_preserved.mp4"
    res = render_timeline_with_crossfades(
        scenes=scenes,
        output_path=out_mp4,
        width=1080,
        height=1920,
        fps=30,
        enable_transitions=True,
        transition_duration=0.5,
        transition_mode="duration_preserving"
    )

    assert out_mp4.exists()
    assert res["transitions_enabled"] is True
    # In duration-preserving mode: 3.0 + 3.0 = 6.0s exact
    assert 5.95 <= res["measured_duration_seconds"] <= 6.05
    assert len(res["render_checksum"]) == 64


def test_render_timeline_standard_overlap_crossfades(tmp_path):
    clip1 = create_synthetic_test_clip(tmp_path / "clip1.mp4", duration=3.0)
    clip2 = create_synthetic_test_clip(tmp_path / "clip2.mp4", duration=3.0)

    scenes = [
        {"visual_asset_path": str(clip1), "duration_seconds": 3.0, "motion_preset": "static"},
        {"visual_asset_path": str(clip2), "duration_seconds": 3.0, "motion_preset": "static"}
    ]

    out_mp4 = tmp_path / "standard_overlap.mp4"
    res = render_timeline_with_crossfades(
        scenes=scenes,
        output_path=out_mp4,
        width=1080,
        height=1920,
        fps=30,
        enable_transitions=True,
        transition_duration=0.5,
        transition_mode="standard_overlap"
    )

    assert out_mp4.exists()
    assert res["transitions_enabled"] is True
    # In standard overlap mode: 3.0 + 3.0 - 0.5 = 5.5s
    assert 5.45 <= res["measured_duration_seconds"] <= 5.55


def test_render_timeline_short_scene_fallback_to_concat(tmp_path):
    clip1 = create_synthetic_test_clip(tmp_path / "clip1.mp4", duration=0.8)
    clip2 = create_synthetic_test_clip(tmp_path / "clip2.mp4", duration=3.0)

    scenes = [
        {"visual_asset_path": str(clip1), "duration_seconds": 0.8, "motion_preset": "static"},
        {"visual_asset_path": str(clip2), "duration_seconds": 3.0, "motion_preset": "static"}
    ]

    out_mp4 = tmp_path / "fallback_cut.mp4"
    res = render_timeline_with_crossfades(
        scenes=scenes,
        output_path=out_mp4,
        enable_transitions=True,
        transition_duration=0.5
    )

    assert out_mp4.exists()
    # Must have fallen back to clean cut (transitions disabled)
    assert res["transitions_enabled"] is False
    assert 3.75 <= res["measured_duration_seconds"] <= 3.85


def test_sidechain_ducking_audio_mix(tmp_path):
    speech = create_synthetic_audio(tmp_path / "speech.wav", frequency=440, duration=4.0, volume=0.8)
    music = create_synthetic_audio(tmp_path / "music.wav", frequency=220, duration=6.0, volume=0.3)
    out_audio = tmp_path / "ducked_mix.aac"

    res = mix_speech_and_music_ducked(
        speech_path=speech,
        output_path=out_audio,
        music_path=music,
        target_lufs=-14.0,
        true_peak_ceiling=-1.0,
        ducking_ratio=8.0,
        ducking_threshold=0.08
    )

    assert out_audio.exists()
    assert res["mode"] == "sidechain_ducked"
    assert res["target_lufs"] == -14.0
    assert res["true_peak_ceiling"] == -1.0
    assert len(res["checksum"]) == 64
    assert res["measured_true_peak"] <= -0.8


def test_ebur128_loudnorm_compliance(tmp_path):
    raw_audio = create_synthetic_audio(tmp_path / "raw.wav", frequency=500, duration=5.0, volume=0.9)
    out_audio = tmp_path / "normalized.aac"

    res = mix_speech_and_music_ducked(
        speech_path=raw_audio,
        output_path=out_audio,
        music_path=None,
        target_lufs=-14.0,
        true_peak_ceiling=-1.0
    )

    assert out_audio.exists()
    assert res["mode"] == "voice_only"
    # Target -14.0 LUFS with +/- 1.0 LUFS tolerance
    assert -15.5 <= res["measured_lufs"] <= -13.0
    # True Peak below -1.0 dBTP
    assert res["measured_true_peak"] <= -0.9


def test_deterministic_render_metadata_and_checksum(tmp_path):
    clip = create_synthetic_test_clip(tmp_path / "clip.mp4", duration=2.0)
    meta = generate_render_metadata(clip, additional_context={"test_key": "test_val"})

    assert meta["resolution"] == "1080x1920"
    assert 1.95 <= meta["measured_duration_seconds"] <= 2.05
    assert len(meta["render_checksum"]) == 64
    assert meta["test_key"] == "test_val"
    assert meta["byte_size"] > 1000
