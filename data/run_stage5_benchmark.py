"""
Stage 5 Controlled Benchmark Script:
Compares Track A (Baseline Ken Burns stills) vs. Track B (Hybrid Sourced Video + Procedural Infographics + xfade transitions).
Generates 1080x1920 30fps Short on Gravitational Time Dilation with full metrics.
"""

import hashlib
import json
import logging
import psutil
import sqlite3
import subprocess
import time
import uuid
from pathlib import Path

from backend.app.config import DB_PATH, MEDIA_DIR
from backend.app.db.connection import init_db
from backend.app.db.repository import (
    create_project,
    get_project,
    create_fact_source,
    create_fact_claim,
    get_asset_provenances,
    get_editorial_review,
    update_project_storyboard
)
from backend.app.media.qa import TechnicalQA
from backend.app.worker.runner import WorkerRunner

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("stage5_benchmark")

SCENE_DEFS = [
    {
        "scene_index": 0,
        "scene_title": "Your Feet Are Younger Than Your Head",
        "narration_text": "Believe it or not, your head is aging faster than your feet right now.",
        "caption_text": "Your head is aging faster than your feet right now.",
        "duration_seconds": 5.5,
        "motion_preset": "zoom_in",
        "visual_description": "Curving blue Earth seen from satellite orbit in space.",
        "supporting_claim_ids": ["claim_gravity_dilation"]
    },
    {
        "scene_index": 1,
        "scene_title": "Einstein's Curved Spacetime",
        "narration_text": "Albert Einstein revealed that Earth mass curves the fabric of spacetime itself. Closer to the core at sea level, stronger gravity drags time, making every single second tick slower.",
        "caption_text": "Stronger gravity at sea level drags spacetime slower.",
        "duration_seconds": 7.0,
        "motion_preset": "pan_left",
        "visual_description": "Einstein relativity formula and spacetime curvature grid diagram.",
        "supporting_claim_ids": ["claim_gravity_dilation"]
    },
    {
        "scene_index": 2,
        "scene_title": "NIST Millimeter Precision",
        "narration_text": "This isn't just theory. Physicists at NIST measured this time warp using optical atomic clocks separated by a single millimeter.",
        "caption_text": "NIST atomic clocks measured this warp across 1 millimeter.",
        "duration_seconds": 6.5,
        "motion_preset": "tilt_up",
        "visual_description": "NIST optical lattice atomic clock laser apparatus millimeter diagram.",
        "supporting_claim_ids": ["claim_nist_millimeter"]
    },
    {
        "scene_index": 3,
        "scene_title": "GPS Orbital Relativity",
        "narration_text": "Up in orbit, GPS satellites feel weaker gravity. Their clocks run thirty-eight microseconds faster every day. Without relativity math, your phone's GPS would drift ten kilometers daily.",
        "caption_text": "GPS clocks run 38 microseconds faster every day.",
        "duration_seconds": 7.5,
        "motion_preset": "zoom_out",
        "visual_description": "GPS navigation satellite orbiting planet Earth in deep space.",
        "supporting_claim_ids": ["claim_gps_38us"]
    },
    {
        "scene_index": 4,
        "scene_title": "Gravity's Universal Toll",
        "narration_text": "So remember, next time you climb a mountain: gravity shapes your reality with every passing second.",
        "caption_text": "Gravity shapes your reality with every passing second.",
        "duration_seconds": 5.5,
        "motion_preset": "tilt_down",
        "visual_description": "Mountain summit view looking down on clouds and curvature of Earth.",
        "supporting_claim_ids": ["claim_gravity_dilation"]
    }
]


def setup_project(project_title: str) -> str:
    proj_id = create_project(
        topic="Why time moves slightly slower at sea level than at high altitude",
        title=project_title,
        content_format="explainer",
        target_audience="Curious Science Thinkers",
        language="en",
        target_duration=32.0,
        narration_mode="local_tts",
        narration_voice="af_bella",
        narrative_archetype="CURIOSITY_GAP",
        scenes=SCENE_DEFS,
        db_path=DB_PATH
    )

    src1 = create_fact_source(
        source_id=f"src_nist_{uuid.uuid4().hex[:6]}",
        url="https://www.nist.gov/news-events/news/2022/02/jila-ultracold-microscopic-clocks",
        title="NIST / JILA Millimeter Gravitational Redshift Experiment",
        published_date="2022-02-16",
        project_id=proj_id,
        raw_excerpt="Optical lattice atomic clocks demonstrate gravitational redshift across a single millimeter vertical separation.",
        http_status=200,
        db_path=DB_PATH
    )

    src2 = create_fact_source(
        source_id=f"src_gps_{uuid.uuid4().hex[:6]}",
        url="https://www.astronomy.ohio-state.edu/pogge.1/Ast162/Unit5/gps.html",
        title="Real-World Relativity: The GPS Navigation System",
        published_date="2021-05-10",
        project_id=proj_id,
        raw_excerpt="General Relativity predicts satellite clocks tick 45.9 microseconds faster per day, while Special Relativity predicts 7.2 microseconds slower. Net difference is +38.6 microseconds daily.",
        http_status=200,
        db_path=DB_PATH
    )

    create_fact_claim(
        claim_id=f"claim_grav_{uuid.uuid4().hex[:6]}",
        source_id=src1,
        project_id=proj_id,
        claim_text="Clocks tick slower near Earth's surface due to gravitational time dilation.",
        quote_excerpt="demonstrate gravitational redshift",
        evidence_status="VERIFIED",
        db_path=DB_PATH
    )

    create_fact_claim(
        claim_id=f"claim_nist_{uuid.uuid4().hex[:6]}",
        source_id=src1,
        project_id=proj_id,
        claim_text="NIST atomic clocks measured time dilation across a single millimeter height difference.",
        quote_excerpt="gravitational redshift across a single millimeter vertical separation",
        evidence_status="VERIFIED",
        db_path=DB_PATH
    )

    create_fact_claim(
        claim_id=f"claim_gps_{uuid.uuid4().hex[:6]}",
        source_id=src2,
        project_id=proj_id,
        claim_text="GPS satellite clocks run approximately 38 microseconds faster per day due to relativistic effects.",
        quote_excerpt="Net difference is +38.6 microseconds daily",
        evidence_status="VERIFIED",
        db_path=DB_PATH
    )

    return proj_id


def run_benchmark():
    print("=================================================================")
    print("=== STAGE 5 BENCHMARK: HYBRID HIGH-CRAFT VISUAL ENGINE ===")
    print("=================================================================")
    init_db(DB_PATH)
    process = psutil.Process()

    # --- TRACK A: Baseline Ken Burns Stills (Stage 3 baseline) ---
    print("\n--- Running Track A: Baseline Ken Burns Stills (no transitions, no video clips) ---")
    track_a_proj_id = setup_project("Stage 5 Benchmark - Track A (Ken Burns Baseline)")
    worker = WorkerRunner(db_path=DB_PATH)

    ram_start = process.memory_info().rss / (1024 * 1024)
    t0 = time.time()
    track_a_res = worker.process_render_project({
        "project_id": track_a_proj_id,
        "width": 1080,
        "height": 1920,
        "fps": 30,
        "enable_motion": True,
        "enable_video_ingest": False,
        "enable_transitions": False
    })
    track_a_duration = time.time() - t0
    track_a_ram_mb = max(ram_start, process.memory_info().rss / (1024 * 1024))

    track_a_path = Path(track_a_res["file_path"])
    track_a_qa = TechnicalQA.inspect_and_verify(
        video_path=track_a_path,
        expected_width=1080,
        expected_height=1920,
        expected_duration=32.0,
        audio_expected=True
    )
    track_a_editorial = get_editorial_review(track_a_proj_id, render_id=track_a_res["render_id"], db_path=DB_PATH)
    track_a_provs = get_asset_provenances(track_a_proj_id, db_path=DB_PATH)

    print(f"Track A Render Complete: {track_a_duration:.2f}s | Size: {track_a_path.stat().st_size / (1024*1024):.2f} MB")
    print(f"Track A QA Status: {track_a_qa['passed']} | Editorial Score: {track_a_editorial['score']}")

    # --- TRACK B: Hybrid Sourced Video + Procedural Infographics + xfade Transitions ---
    print("\n--- Running Track B: Hybrid Video Engine (Sourced Video + Procedural + xfade) ---")
    track_b_proj_id = setup_project("Stage 5 Benchmark - Track B (Hybrid Video + xfade)")

    ram_start_b = process.memory_info().rss / (1024 * 1024)
    t0_b = time.time()
    track_b_res = worker.process_render_project({
        "project_id": track_b_proj_id,
        "width": 1080,
        "height": 1920,
        "fps": 30,
        "enable_motion": True,
        "enable_video_ingest": True,
        "enable_transitions": True,
        "transition_duration": 0.5
    })
    track_b_duration = time.time() - t0_b
    track_b_ram_mb = max(ram_start_b, process.memory_info().rss / (1024 * 1024))

    track_b_path = Path(track_b_res["file_path"])
    track_b_qa = TechnicalQA.inspect_and_verify(
        video_path=track_b_path,
        expected_width=1080,
        expected_height=1920,
        expected_duration=32.0,
        audio_expected=True
    )
    track_b_editorial = get_editorial_review(track_b_proj_id, render_id=track_b_res["render_id"], db_path=DB_PATH)
    track_b_provs = get_asset_provenances(track_b_proj_id, db_path=DB_PATH)

    print(f"Track B Render Complete: {track_b_duration:.2f}s | Size: {track_b_path.stat().st_size / (1024*1024):.2f} MB")
    print(f"Track B QA Status: {track_b_qa['passed']} | Editorial Score: {track_b_editorial['score']}")

    # Modality breakdown for Track B
    modalities = {}
    for p in track_b_provs:
        m = p.get("media_type", "image")
        modalities[m] = modalities.get(m, 0) + 1

    comparison = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "resolution": "1080x1920",
        "fps": 30,
        "target_duration_s": 32.0,
        "track_a_baseline": {
            "name": "Track A: Baseline Ken Burns Stills",
            "project_id": track_a_proj_id,
            "render_checksum": track_a_res["render_checksum"],
            "render_time_s": round(track_a_duration, 2),
            "file_size_mb": round(track_a_path.stat().st_size / (1024 * 1024), 2),
            "peak_ram_mb": round(track_a_ram_mb, 1),
            "technical_qa_passed": track_a_qa["passed"],
            "editorial_score": track_a_editorial["score"],
            "transitions_enabled": False,
            "video_ingest_enabled": False,
            "file_path": str(track_a_path)
        },
        "track_b_hybrid": {
            "name": "Track B: Hybrid Sourced Video + Procedural Infographics + xfade Transitions",
            "project_id": track_b_proj_id,
            "render_checksum": track_b_res["render_checksum"],
            "render_time_s": round(track_b_duration, 2),
            "file_size_mb": round(track_b_path.stat().st_size / (1024 * 1024), 2),
            "peak_ram_mb": round(track_b_ram_mb, 1),
            "technical_qa_passed": track_b_qa["passed"],
            "editorial_score": track_b_editorial["score"],
            "transitions_enabled": True,
            "transition_duration_s": 0.5,
            "video_ingest_enabled": True,
            "modalities_count": modalities,
            "file_path": str(track_b_path)
        },
        "track_b_provenance": [
            {
                "scene_index": p["scene_index"],
                "asset_type": p["asset_type"],
                "media_type": p.get("media_type"),
                "rights_status": p.get("rights_status"),
                "selection_reason": p.get("selection_reason"),
                "crop_transform": p.get("crop_transform"),
                "local_path": p["local_path"],
                "sha256_checksum": p["sha256_checksum"]
            }
            for p in track_b_provs
        ]
    }

    out_json = Path("data/benchmark_stage5_results.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(comparison, f, indent=2)

    print(f"\nBenchmark comparison saved to {out_json}")
    return comparison


if __name__ == "__main__":
    run_benchmark()
