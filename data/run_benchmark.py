"""Stage 3 Benchmark Script: 1080x1920 Short on Gravitational Time Dilation."""

import time
import json
import psutil
import subprocess
from pathlib import Path

from backend.app.config import DB_PATH, MEDIA_DIR
from backend.app.db.connection import init_db
from backend.app.db.repository import (
    create_project,
    get_project,
    create_fact_source,
    create_fact_claim,
    get_asset_provenances,
    get_editorial_review
)
from backend.app.worker.runner import WorkerRunner
from backend.app.media.qa import TechnicalQA

def run_benchmark():
    print("=== STARTING STAGE 3 BENCHMARK: 1080x1920 Ken Burns Short ===")
    init_db(DB_PATH)
    start_time = time.time()
    process = psutil.Process()
    ram_before_mb = process.memory_info().rss / (1024 * 1024)

    # 1. Register FactLedger Provenance
    proj_id = "stage3_benchmark_dilation"
    
    # Clean any prior test run for idempotency
    import sqlite3
    con = sqlite3.connect(str(DB_PATH))
    con.execute("DELETE FROM projects WHERE id = ?", (proj_id,))
    con.execute("DELETE FROM fact_sources WHERE project_id = ?", (proj_id,))
    con.execute("DELETE FROM fact_claims WHERE project_id = ?", (proj_id,))
    con.execute("DELETE FROM asset_provenance WHERE project_id = ?", (proj_id,))
    con.execute("DELETE FROM editorial_reviews WHERE project_id = ?", (proj_id,))
    con.commit()
    con.close()

    # 1. Create Project first (satisfies foreign keys for fact sources & claims)
    scenes = [
        {
            "scene_index": 0,
            "scene_title": "Your Feet Are Younger Than Your Head",
            "narration_text": "Believe it or not, your head is aging faster than your feet right now.",
            "caption_text": "Your head is aging faster than your feet right now.",
            "duration_seconds": 5.5,
            "motion_preset": "zoom_in",
            "supporting_claim_ids": ["claim_gravity_dilation"]
        },
        {
            "scene_index": 1,
            "scene_title": "Einstein's Curved Spacetime",
            "narration_text": "Albert Einstein revealed that Earth's mass curves the fabric of spacetime itself. Closer to the core at sea level, stronger gravity drags time, making every single second tick slower.",
            "caption_text": "Stronger gravity at sea level drags spacetime slower.",
            "duration_seconds": 7.0,
            "motion_preset": "pan_left",
            "supporting_claim_ids": ["claim_gravity_dilation"]
        },
        {
            "scene_index": 2,
            "scene_title": "NIST Millimeter Precision",
            "narration_text": "This isn't just theory. Physicists at NIST measured this time warp using optical atomic clocks separated by a single millimeter.",
            "caption_text": "NIST atomic clocks measured this warp across 1 millimeter.",
            "duration_seconds": 6.5,
            "motion_preset": "tilt_up",
            "supporting_claim_ids": ["claim_nist_millimeter"]
        },
        {
            "scene_index": 3,
            "scene_title": "GPS Orbital Relativity",
            "narration_text": "Up in orbit, GPS satellites feel weaker gravity. Their clocks run thirty-eight microseconds faster every day. Without relativity math, your phone's GPS would drift ten kilometers daily.",
            "caption_text": "GPS clocks run 38 microseconds faster every day.",
            "duration_seconds": 7.5,
            "motion_preset": "zoom_out",
            "supporting_claim_ids": ["claim_gps_38us"]
        },
        {
            "scene_index": 4,
            "scene_title": "Gravity's Universal Toll",
            "narration_text": "So remember, next time you climb a mountain: gravity shapes your reality with every passing second.",
            "caption_text": "Gravity shapes your reality with every passing second.",
            "duration_seconds": 5.5,
            "motion_preset": "tilt_down",
            "supporting_claim_ids": ["claim_gravity_dilation"]
        }
    ]

    proj_id = create_project(
        topic="Why time moves slightly slower at sea level than at high altitude",
        title="Why Time Moves Slower At Sea Level",
        content_format="explainer",
        target_audience="Curious Science Thinkers",
        language="en",
        target_duration=32.0,
        narration_mode="local_tts",
        narration_voice="af_bella",
        narrative_archetype="CURIOSITY_GAP",
        scenes=scenes,
        db_path=DB_PATH
    )

    project = get_project(proj_id, db_path=DB_PATH)

    # 2. Register FactLedger Provenance
    src1_id = create_fact_source(
        source_id="src_nist_relativity",
        url="https://www.nist.gov/news-events/news/2022/02/jila-ultracold-microscopic-clocks",
        title="NIST / JILA Millimeter Gravitational Redshift Experiment",
        published_date="2022-02-16",
        project_id=proj_id,
        raw_excerpt="Optical lattice atomic clocks demonstrate gravitational redshift across a single millimeter vertical separation.",
        http_status=200,
        db_path=DB_PATH
    )

    src2_id = create_fact_source(
        source_id="src_gps_relativity",
        url="https://www.astronomy.ohio-state.edu/pogge.1/Ast162/Unit5/gps.html",
        title="Real-World Relativity: The GPS Navigation System",
        published_date="2021-05-10",
        project_id=proj_id,
        raw_excerpt="General Relativity predicts satellite clocks tick 45.9 microseconds faster per day, while Special Relativity predicts 7.2 microseconds slower. Net difference is +38.6 microseconds daily.",
        http_status=200,
        db_path=DB_PATH
    )

    claim1_id = create_fact_claim(
        claim_id="claim_gravity_dilation",
        source_id=src1_id,
        project_id=proj_id,
        claim_text="Clocks tick slower near Earth's surface due to gravitational time dilation.",
        quote_excerpt="demonstrate gravitational redshift",
        evidence_status="VERIFIED",
        db_path=DB_PATH
    )

    claim2_id = create_fact_claim(
        claim_id="claim_nist_millimeter",
        source_id=src1_id,
        project_id=proj_id,
        claim_text="NIST atomic clocks measured time dilation across a single millimeter height difference.",
        quote_excerpt="gravitational redshift across a single millimeter vertical separation",
        evidence_status="VERIFIED",
        db_path=DB_PATH
    )

    claim3_id = create_fact_claim(
        claim_id="claim_gps_38us",
        source_id=src2_id,
        project_id=proj_id,
        claim_text="GPS satellite clocks run approximately 38 microseconds faster per day due to relativistic effects.",
        quote_excerpt="Net difference is +38.6 microseconds daily",
        evidence_status="VERIFIED",
        db_path=DB_PATH
    )

    project = get_project(proj_id, db_path=DB_PATH)
    assert project is not None
    print(f"Project created: {project['id']} - Title: {project['title']} - Scenes: {len(project.get('scenes', []))}")

    # 3. Execute Worker Render at 1080x1920 with Ken Burns Motion and Audio Ducking
    worker = WorkerRunner(db_path=DB_PATH)
    render_payload = {
        "project_id": proj_id,
        "width": 1080,
        "height": 1920,
        "fps": 30,
        "enable_motion": True,
        "enable_bg_music": True
    }

    render_start = time.time()
    render_res = worker.process_render_project(render_payload)
    render_duration = time.time() - render_start

    ram_after_mb = process.memory_info().rss / (1024 * 1024)
    peak_ram_mb = max(ram_before_mb, ram_after_mb)

    # 4. Gather Artifacts & Metrics
    out_mp4 = Path(render_res["file_path"])
    checksum = render_res["render_checksum"]
    file_size_mb = out_mp4.stat().st_size / (1024 * 1024)

    # Technical QA
    qa_res = TechnicalQA.inspect_and_verify(
        video_path=out_mp4,
        expected_width=1080,
        expected_height=1920,
        expected_duration=32.0,
        audio_expected=True
    )

    # Editorial Review
    editorial_res = get_editorial_review(proj_id, render_id=render_res["render_id"], db_path=DB_PATH)
    provenance_records = get_asset_provenances(proj_id, db_path=DB_PATH)

    benchmark_data = {
        "benchmark_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "project_id": proj_id,
        "title": project["title"],
        "topic": project["topic"],
        "resolution": "1080x1920",
        "fps": 30,
        "total_video_duration_seconds": qa_res["details"]["duration_seconds"],
        "render_time_seconds": round(render_duration, 2),
        "file_size_mb": round(file_size_mb, 2),
        "render_checksum": checksum,
        "file_path": str(out_mp4),
        "peak_ram_mb": round(peak_ram_mb, 1),
        "audio_mode": render_res["audio_mix"]["mode"],
        "integrated_lufs": render_res["audio_mix"]["integrated_lufs"],
        "true_peak_dbfs": render_res["audio_mix"]["true_peak_dbfs"],
        "technical_qa": {
            "passed": qa_res["passed"],
            "failure_reasons": qa_res["failure_reasons"],
            "warnings": qa_res["warnings"],
            "video_codec": qa_res["details"]["video_codec"],
            "audio_codec": qa_res["details"]["audio_codec"],
            "black_frame_detected": qa_res["details"]["black_frame_detected"],
            "freeze_frame_detected": qa_res["details"]["freeze_frame_detected"]
        },
        "editorial_qa": {
            "overall_status": editorial_res["overall_status"] if editorial_res else "UNKNOWN",
            "score": editorial_res["score"] if editorial_res else 0,
            "hook_evaluation": editorial_res.get("hook_evaluation") if editorial_res else {},
            "pacing_evaluation": editorial_res.get("pacing_evaluation") if editorial_res else {},
            "relevance_evaluation": editorial_res.get("relevance_evaluation") if editorial_res else {},
            "audio_evaluation": editorial_res.get("audio_evaluation") if editorial_res else {},
            "warnings": editorial_res.get("warnings") if editorial_res else []
        },
        "asset_provenances": provenance_records
    }

    out_json = Path("data/benchmark_stage3_results.json")
    with out_json.open("w", encoding="utf-8") as f:
        json.dump(benchmark_data, f, indent=2)

    print("\n=== BENCHMARK COMPLETED SUCCESSFULLY ===")
    print(f"Output Video: {out_mp4}")
    print(f"Checksum: {checksum}")
    print(f"Duration: {qa_res['details']['duration_seconds']}s")
    print(f"File Size: {file_size_mb:.2f} MB")
    print(f"Render Time: {render_duration:.2f}s")
    print(f"Technical QA Passed: {qa_res['passed']}")
    print(f"Editorial Score: {benchmark_data['editorial_qa']['score']}/100 ({benchmark_data['editorial_qa']['overall_status']})")
    print(f"Audio Loudness: {benchmark_data['integrated_lufs']} LUFS (Peak: {benchmark_data['true_peak_dbfs']} dBFS)")
    print(f"Results recorded in: {out_json}")

if __name__ == "__main__":
    run_benchmark()
