"""Generates an end-to-end reviewable 15-30s Short video demonstrating the Flow Handoff & Rendering Adapters."""

import os
import sys
import json
import time
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.app.config import DB_PATH, MEDIA_DIR
from backend.app.db.connection import init_db
from backend.app.db.repository import (
    create_project,
    get_project,
    update_project_storyboard,
    create_render,
    get_asset_provenances
)
from backend.app.media.flow_handoff import export_flow_manifest
from backend.app.media.flow_ingestion import (
    validate_flow_video,
    import_and_bind_flow_video,
    INBOX_DIR
)
from backend.app.media.narration import LocalTTSAdapter
from backend.app.media.audio_mixer import AudioMixer
from backend.app.media.rendering_adapters import (
    render_timeline_with_crossfades,
    generate_render_metadata
)


def run_benchmark():
    print("=" * 60)
    print("STARTING FLOW HANDOFF & RENDERING ADAPTERS BENCHMARK")
    print("=" * 60)

    start_total_time = time.time()
    init_db(DB_PATH)

    # 1. Create a dedicated demonstration project
    topic = "What Really Happens Inside a Black Hole?"
    project_id = create_project(
        title="Inside a Black Hole",
        topic=topic,
        target_audience="curious_minds",
        language="en",
        target_duration=20.0,
        content_format="youtube_shorts",
        narrative_archetype="Counter-Intuitive",
        narration_mode="local_tts",
        narration_voice="af_bella",
        db_path=DB_PATH
    )
    print(f"1. Created Project: {project_id}")

    # 2. Define 4 storyboard scenes (~18s total)
    scenes_data = [
        {
            "scene_index": 0,
            "scene_title": "The Cosmic Trap",
            "narration_text": "You might think a black hole is an empty vacuum sucking in space.",
            "caption_text": "Black holes are not cosmic vacuums.",
            "duration_seconds": 4.5,
            "motion_preset": "static"
        },
        {
            "scene_index": 1,
            "scene_title": "The Warped Horizon",
            "narration_text": "In reality, gravity is so intense that space and time literally swap roles.",
            "caption_text": "Space and time swap roles at the horizon.",
            "duration_seconds": 4.5,
            "motion_preset": "zoom_in"
        },
        {
            "scene_index": 2,
            "scene_title": "Moving Toward Tomorrow",
            "narration_text": "Moving forward in space becomes as inevitable as moving into tomorrow.",
            "caption_text": "The singularity is a moment in time.",
            "duration_seconds": 4.5,
            "motion_preset": "pan_left"
        },
        {
            "scene_index": 3,
            "scene_title": "The Singularity Horizon",
            "narration_text": "The singularity isn't a place in space. It is a moment in your future.",
            "caption_text": "You cannot escape your own future.",
            "duration_seconds": 4.5,
            "motion_preset": "zoom_out"
        }
    ]

    update_project_storyboard(project_id, scenes_data, db_path=DB_PATH)
    project = get_project(project_id, db_path=DB_PATH)
    scenes = project["scenes"]
    print(f"2. Initialized Storyboard with {len(scenes)} scenes (Target Duration: ~18.0s)")

    # 3. Flow Handoff: Generate & Export Flow Prompt Manifest
    flow_export = export_flow_manifest(project, base_media_dir=MEDIA_DIR)
    print(f"3. Exported Google Flow Manifest: {flow_export['manifest_path']}")
    print(f"   Scene 1 Exact Prompt: {flow_export['manifest']['scenes'][0]['exact_prompt'][:80]}...")

    # 4. Create Simulated Flow Video Fixture for Scene 1
    flow_inbox_path = INBOX_DIR / "flow_black_hole_event_horizon.mp4"
    print(f"4. Generating realistic 1080x1920 30fps Flow video fixture: {flow_inbox_path.name}")
    # Procedural cosmic swirling nebula simulation using FFmpeg
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", "mandelbrot=s=1080x1920:r=30:maxiter=100",
        "-t", "4.5",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        str(flow_inbox_path)
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    # 5. Validate & Ingest Flow Video into Scene 1
    t_ingest_start = time.time()
    ingest_result = import_and_bind_flow_video(
        project_id=project_id,
        scene_id=scenes[0]["id"],
        source_file_path=flow_inbox_path,
        confirmed_by_user=True,
        db_path=DB_PATH,
        media_dir=MEDIA_DIR
    )
    t_ingest_sec = time.time() - t_ingest_start
    print(f"5. Flow Video Ingestion Completed in {t_ingest_sec:.2f}s:")
    print(f"   Status: {ingest_result['validation']['status']}")
    print(f"   SHA-256: {ingest_result['validation']['sha256_checksum'][:16]}...")
    print(f"   Source Specs: {ingest_result['validation']['source_width']}x{ingest_result['validation']['source_height']} @ {ingest_result['validation']['source_fps']}fps")
    print(f"   Post-processing note: {ingest_result['validation']['post_processing_note']}")

    # 6. Generate Supporting Visual Backgrounds for Scenes 2, 3, 4
    colors = ["darkblue", "purple", "darkred"]
    for i, s_idx in enumerate([1, 2, 3]):
        scene_obj = scenes[s_idx]
        bg_path = MEDIA_DIR / "projects" / project_id / f"scene_{s_idx + 1}_bg.png"
        bg_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"color=c={colors[i]}:s=1080x1920:d=1",
            "-vframes", "1",
            str(bg_path)
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        # Update scene in DB
        from backend.app.db.repository import update_scene_visual_and_motion
        update_scene_visual_and_motion(scene_obj["id"], str(bg_path), motion_preset=scene_obj.get("motion_preset", "zoom_in"), db_path=DB_PATH)

    # 7. Synthesize Speech Narration via Kokoro TTS
    tts = LocalTTSAdapter()
    full_script = " ".join(s["narration_text"] for s in scenes)
    speech_path = MEDIA_DIR / "projects" / project_id / "narration.wav"
    print("7. Synthesizing full narration via Kokoro-82M ONNX FP16...")
    t_tts_start = time.time()
    tts_res = tts.synthesize(full_script, speech_path, voice="af_bella", speed=1.0)
    t_tts_sec = time.time() - t_tts_start
    print(f"   TTS Synthesized {tts_res['duration']:.2f}s of audio in {t_tts_sec:.2f}s (RTF: {t_tts_sec/tts_res['duration']:.3f})")

    # 8. Mix Audio with Sidechain Ducking & EBU R128 Loudness Normalization
    ambient_path = MEDIA_DIR / "projects" / project_id / "ambient_bed.wav"
    AudioMixer.generate_ambient_bed(ambient_path, duration_seconds=tts_res["duration"] + 2.0)

    final_audio_path = MEDIA_DIR / "projects" / project_id / "final_soundtrack.aac"
    print("8. Mixing soundtrack with sidechain ducking (-14 dB attenuation, -14.0 LUFS target)...")
    mixer = AudioMixer()
    mix_res = mixer.mix_and_duck(
        speech_path=speech_path,
        output_path=final_audio_path,
        bg_music_path=ambient_path,
        target_lufs=-14.0
    )
    print(f"   Soundtrack Mixed: Integrated Loudness = {mix_res['integrated_lufs']} LUFS, True Peak = {mix_res['true_peak_dbfs']} dBTP")

    # 9. Render Final Short Video via Duration-Preserving Rendering Adapter
    out_mp4 = MEDIA_DIR / "projects" / project_id / "final_render_flow_handoff.mp4"
    # Re-fetch updated project with new visual paths
    updated_project = get_project(project_id, db_path=DB_PATH)
    active_scenes = updated_project["scenes"]

    print("9. Rendering final vertical video (1080x1920 @ 30fps) with 0.5s duration-preserving crossfades...")
    t_render_start = time.time()
    render_meta = render_timeline_with_crossfades(
        scenes=active_scenes,
        output_path=out_mp4,
        audio_path=final_audio_path,
        width=1080,
        height=1920,
        fps=30,
        enable_motion=True,
        enable_transitions=True,
        transition_duration=0.5,
        transition_mode="duration_preserving"
    )
    t_render_sec = time.time() - t_render_start

    total_time_sec = time.time() - start_total_time
    print("=" * 60)
    print("BENCHMARK COMPLETED SUCCESSFULLY")
    print(f"Render Output File: {out_mp4}")
    print(f"File Size: {render_meta['byte_size']} bytes ({render_meta['byte_size'] / (1024*1024):.2f} MB)")
    print(f"Measured Duration: {render_meta['measured_duration_seconds']}s")
    print(f"Render Checksum (SHA-256): {render_meta['render_checksum']}")
    print(f"Resolution: {render_meta['resolution']} @ 30fps")
    print(f"Soundtrack Loudness: {render_meta['loudness'].get('integrated_lufs', 'N/A')} LUFS, Peak: {render_meta['loudness'].get('true_peak_dbfs', 'N/A')} dBTP")
    print(f"Render Latency: {t_render_sec:.2f}s | Total Pipeline Time: {total_time_sec:.2f}s")
    print("=" * 60)

    # Save benchmark metrics to JSON
    benchmark_data = {
        "project_id": project_id,
        "topic": topic,
        "sample_output_path": str(out_mp4),
        "checksum_sha256": render_meta["render_checksum"],
        "byte_size": render_meta["byte_size"],
        "measured_duration_seconds": render_meta["measured_duration_seconds"],
        "resolution": render_meta["resolution"],
        "fps": 30,
        "loudness": render_meta["loudness"],
        "ingest_validation": ingest_result["validation"],
        "timings": {
            "tts_latency_seconds": round(t_tts_sec, 2),
            "render_latency_seconds": round(t_render_sec, 2),
            "total_pipeline_seconds": round(total_time_sec, 2)
        }
    }

    result_json_path = REPO_ROOT / "data" / "flow_handoff_benchmark_results.json"
    with open(result_json_path, "w") as f:
        json.dump(benchmark_data, f, indent=2)

    return benchmark_data


if __name__ == "__main__":
    run_benchmark()
