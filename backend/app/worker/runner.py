"""Single-worker runner enforcing 1 GPU/CPU render slot, job leasing, and resource checks."""

import time
import logging
import uuid
import json
from typing import Optional, Dict, Any
from pathlib import Path

from backend.app.config import (
    DB_PATH,
    MEDIA_DIR,
    check_system_resources
)
from backend.app.db.repository import (
    is_global_paused,
    lease_next_job,
    heartbeat_job,
    complete_job,
    fail_job,
    get_project,
    update_scene_visual,
    update_scene_visual_and_motion,
    update_project_audio,
    create_render,
    set_project_render,
    save_editorial_review,
    get_asset_provenances
)
from backend.app.providers.mock_providers import (
    MockLLMProvider,
    MockStillsProvider,
    MockTTSProvider
)
from backend.app.media.assets import generate_default_scene_background
from backend.app.media.subtitles import generate_ass_subtitles
from backend.app.media.narration import get_narration_adapter
from backend.app.media.ffmpeg_composer import FFmpegComposer
from backend.app.media.qa import TechnicalQA
from backend.app.media.visual_adapters import CompositeVisualResolver
from backend.app.media.visual_selector import SceneVisualSelector
from backend.app.media.audio_mixer import AudioMixer
from backend.app.media.editorial_qa import EditorialQA

logger = logging.getLogger("worker_runner")

class WorkerRunner:
    """Worker daemon executing 1 job at a time, enforcing ADR-11 resource limits."""

    def __init__(self, db_path: Path = DB_PATH, worker_id: Optional[str] = None):
        self.db_path = db_path
        self.worker_id = worker_id or f"worker_{uuid.uuid4().hex[:8]}"
        self.llm = MockLLMProvider()
        self.stills = MockStillsProvider()
        self.tts = MockTTSProvider()
        self._running = False

    def check_guardrails(self) -> bool:
        """Returns True if host memory and disk are above safety thresholds."""
        res = check_system_resources()
        if not res["can_process_jobs"]:
            logger.warning(
                f"Worker guardrail triggered: available RAM={res['available_ram_gib']} GiB "
                f"(min {res['min_ram_threshold_gib']}), free disk={res['free_disk_gb']} GB "
                f"(min {res['min_disk_threshold_gb']}). Pausing execution."
            )
            return False
        return True

    def process_render_project(self, payload: Any) -> Dict[str, Any]:
        """Executes full end-to-end rendering pipeline for a project with motion, audio mix, and QA."""
        if isinstance(payload, str):
            payload = {"project_id": payload}
        elif not isinstance(payload, dict):
            payload = {}

        project_id = payload.get("project_id")
        if not project_id:
            raise ValueError("project_id required in RENDER_PROJECT payload.")

        project = get_project(project_id, self.db_path)
        if not project:
            raise ValueError(f"Project {project_id} not found.")

        scenes = project.get("scenes", [])
        if not scenes:
            raise ValueError(f"Project {project_id} has no scenes to render.")

        width = int(payload.get("width", 720))
        height = int(payload.get("height", 1280))
        fps = int(payload.get("fps", 30))
        enable_motion = bool(payload.get("enable_motion", True))
        enable_bg_music = bool(payload.get("enable_bg_music", True))
        enable_video_ingest = bool(payload.get("enable_video_ingest", True))
        enable_transitions = bool(payload.get("enable_transitions", True))
        transition_duration = float(payload.get("transition_duration", 0.5))

        project_dir = MEDIA_DIR / "projects" / project_id
        project_dir.mkdir(parents=True, exist_ok=True)

        # 1. Resolve and ensure visual assets exist for all scenes
        total_duration = 0.0
        selector = SceneVisualSelector(db_path=self.db_path)
        allow_fallback = bool(payload.get("allow_placeholder_fallback", False))
        missing_required_scenes = []

        for i, s in enumerate(scenes):
            s_dur = float(s.get("duration_seconds", 5.0))
            total_duration += s_dur
            v_path = s.get("visual_asset_path")
            source_type = s.get("visual_source_type", "DEFAULT_BACKGROUND")

            # Check if valid asset file is already bound and exists on disk
            if v_path and Path(v_path).exists() and Path(v_path).stat().st_size > 0:
                continue

            # If no asset is present and fallback is NOT explicitly permitted for generated footage:
            if not allow_fallback and source_type in ("FLOW_REQUIRED", "USER_UPLOAD"):
                missing_required_scenes.append(f"Scene {i+1} ('{s.get('scene_title', f'Scene {i+1}')}')")
                continue

            # Fallback path (only when explicitly allowed, or for stock/procedural beats)
            resolved = selector.resolve_visual_for_scene(
                project_id=project_id,
                scene=s,
                topic=project.get("topic", ""),
                duration=s_dur,
                enable_video=enable_video_ingest,
                anchor=s.get("crop_anchor", "center")
            )
            s["visual_asset_path"] = str(resolved.local_path)
            s["asset_provenance_id"] = resolved.associated_claim_id
            s["visual_source_type"] = "EXPLICIT_FALLBACK" if allow_fallback else "CURATED_STOCK"
            if s.get("id"):
                update_scene_visual_and_motion(
                    scene_id=s["id"],
                    visual_asset_path=str(resolved.local_path),
                    motion_preset=s.get("motion_preset", "zoom_in"),
                    visual_source_type=s["visual_source_type"],
                    asset_provenance_id=resolved.associated_claim_id,
                    db_path=self.db_path
                )

        if missing_required_scenes:
            err_msg = (
                f"Render rejected: Missing required footage for {', '.join(missing_required_scenes)}. "
                "Scenes require real imported footage. Please import generated video via Google Flow handoff ('data/inbox/') "
                "or re-trigger render with 'allow_placeholder_fallback=True'."
            )
            logger.warning(err_msg)
            raise RuntimeError(err_msg)

        # 2. Prepare narration audio
        narration_mode = project.get("narration_mode", "silent")
        raw_audio_path: Optional[Path] = None
        audio_expected = (narration_mode in ("manual_audio", "local_tts", "silent"))

        adapter = get_narration_adapter(narration_mode)
        if narration_mode == "manual_audio":
            src_audio = Path(project["narration_audio_path"]) if project.get("narration_audio_path") else None
            raw_audio_path = adapter.prepare_audio(total_duration, project_dir / "narration.aac", source_path=src_audio)
        elif narration_mode == "local_tts":
            narration_texts = [s.get("narration_text", "").strip() for s in scenes if s.get("narration_text", "").strip()]
            full_narration = " ".join(narration_texts)
            if not full_narration:
                full_narration = project.get("title") or project.get("topic") or ""
            voice = project.get("narration_voice") or "af_bella"
            lang = project.get("language") or "en-us"
            if lang == "en":
                lang = "en-us"
            raw_audio_path = adapter.prepare_audio(
                total_duration,
                project_dir / "narration.wav",
                text=full_narration,
                voice=voice,
                lang=lang,
                pad_to_duration=True
            )
            update_project_audio(project_id, str(raw_audio_path), narration_mode="local_tts", db_path=self.db_path)
        else:
            # Silent mode: generate silent audio track for maximum player compatibility
            raw_audio_path = adapter.prepare_audio(total_duration, project_dir / "silent_audio.aac")
            audio_expected = True

        # 3. Audio Production: Mixing, Sidechain Ducking, and Normalization
        mixer = AudioMixer()
        final_audio_path = project_dir / "final_audio_mix.aac"
        bg_music_file: Optional[Path] = None

        if enable_bg_music and narration_mode in ("local_tts", "manual_audio"):
            if payload.get("bg_music_path") and Path(payload["bg_music_path"]).exists():
                bg_music_file = Path(payload["bg_music_path"])
            else:
                # Procedural ambient bed
                ambient_path = project_dir / "ambient_bed.wav"
                mixer.generate_ambient_bed(ambient_path, duration_seconds=total_duration)
                bg_music_file = ambient_path

        mix_metadata = mixer.mix_and_duck(
            speech_path=raw_audio_path,
            output_path=final_audio_path,
            bg_music_path=bg_music_file,
            target_lufs=-16.0
        )

        # 4. Generate phrase-synchronized ASS subtitles
        sub_file = project_dir / "captions.ass"
        generate_ass_subtitles(scenes, sub_file, width=width, height=height)

        # 5. Build and verify exact input asset manifest
        import hashlib
        asset_manifest = []
        for i, s in enumerate(scenes):
            vp = Path(s["visual_asset_path"])
            if not vp.exists() or vp.stat().st_size == 0:
                raise RuntimeError(f"Visual asset for Scene {i+1} is missing or zero bytes: {vp}")

            hasher = hashlib.sha256()
            with vp.open("rb") as f:
                while chunk := f.read(65536):
                    hasher.update(chunk)
            file_sha = hasher.hexdigest()

            asset_manifest.append({
                "scene_index": i,
                "scene_title": s.get("scene_title", f"Scene {i+1}"),
                "visual_asset_path": str(vp),
                "sha256_checksum": file_sha,
                "visual_source_type": s.get("visual_source_type", "UNKNOWN"),
                "duration_seconds": float(s.get("duration_seconds", 5.0)),
                "asset_provenance_id": s.get("asset_provenance_id")
            })

        contains_placeholders = any(a["visual_source_type"] == "EXPLICIT_FALLBACK" for a in asset_manifest)

        # Compose with FFmpeg (Ken Burns motion + subtitles + mixed audio)
        render_id = str(uuid.uuid4())
        out_mp4 = project_dir / "renders" / f"render_{render_id[:8]}.mp4"

        composer = FFmpegComposer(width=width, height=height, fps=fps)
        comp_result = composer.render(
            scenes=scenes,
            output_path=out_mp4,
            subtitles_path=sub_file,
            audio_path=final_audio_path,
            enable_motion=enable_motion,
            enable_transitions=enable_transitions,
            transition_duration=transition_duration
        )

        render_checksum = comp_result["render_checksum"]

        # 6. Technical Quality Assurance (QA)
        qa_result = TechnicalQA.inspect_and_verify(
            video_path=out_mp4,
            expected_width=width,
            expected_height=height,
            expected_duration=total_duration,
            audio_expected=audio_expected
        )

        if not qa_result["passed"]:
            fail_reasons = "; ".join(qa_result["failure_reasons"])
            create_render(
                render_id=render_id,
                checksum=render_checksum,
                recipe_json=json.dumps({
                    "scenes": len(scenes),
                    "width": width,
                    "height": height,
                    "asset_manifest": asset_manifest,
                    "contains_placeholders": contains_placeholders
                }),
                project_id=project_id,
                file_path=str(out_mp4),
                qa_status="FAILED",
                db_path=self.db_path
            )
            raise RuntimeError(f"Render QA failed: {fail_reasons}")

        # 7. Save successful render record first (satisfies foreign key in editorial_reviews)
        create_render(
            render_id=render_id,
            checksum=render_checksum,
            recipe_json=json.dumps({
                "scenes_count": len(scenes),
                "resolution": f"{width}x{height}",
                "duration": total_duration,
                "narration_mode": narration_mode,
                "enable_motion": enable_motion,
                "enable_video_ingest": enable_video_ingest,
                "enable_transitions": enable_transitions,
                "audio_mode": mix_metadata.get("mode"),
                "integrated_lufs": mix_metadata.get("integrated_lufs"),
                "asset_manifest": asset_manifest,
                "contains_placeholders": contains_placeholders
            }),
            project_id=project_id,
            file_path=str(out_mp4),
            qa_status="PASSED",
            db_path=self.db_path
        )

        # 8. Editorial Quality Assurance (QA)
        asset_provenances = get_asset_provenances(project_id, self.db_path)
        editorial_eval = EditorialQA.evaluate(project, scenes, asset_provenances)
        save_editorial_review(
            review_id=editorial_eval["review_id"],
            project_id=project_id,
            overall_status=editorial_eval["overall_status"],
            score=editorial_eval["score"],
            hook_evaluation=editorial_eval["hook_evaluation"],
            pacing_evaluation=editorial_eval["pacing_evaluation"],
            relevance_evaluation=editorial_eval["relevance_evaluation"],
            audio_evaluation=editorial_eval["audio_evaluation"],
            warnings=editorial_eval["warnings"],
            render_id=render_id,
            db_path=self.db_path
        )

        set_project_render(project_id, render_id, status="AWAITING_APPROVAL", db_path=self.db_path)

        return {
            "status": "SUCCESS",
            "qa_status": "PASSED",
            "render_id": render_id,
            "render_checksum": render_checksum,
            "file_path": str(out_mp4),
            "qa_details": qa_result["details"],
            "editorial_review": editorial_eval,
            "audio_mix": mix_metadata
        }

    def process_job_stage(self, stage: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatches work based on stage."""
        if stage == "RENDER_PROJECT":
            return self.process_render_project(payload)

        elif stage == "RESEARCH_TOPIC":
            from backend.app.research.agent import ResearchAgent
            from backend.app.domain.models import ResearchRequest
            req = ResearchRequest(
                topic=payload.get("topic", "Scientific Breakthroughs"),
                target_audience=payload.get("target_audience", "General"),
                narrative_archetype=payload.get("narrative_archetype", "CURIOSITY_GAP"),
                project_id=payload.get("project_id"),
                max_sources=payload.get("max_sources", 3)
            )
            agent = ResearchAgent(db_path=self.db_path)
            res = agent.run_research(req)
            return {"status": "SUCCESS", "research": res.model_dump()}

        elif stage == "MOCK_SCRIPT":
            topic = payload.get("topic", "Automated Video Production")
            proposal = self.llm.generate_script_proposal(topic)
            return {"status": "SUCCESS", "proposal": proposal.model_dump()}
        
        elif stage == "MOCK_AUDIO":
            text = payload.get("text", "Welcome to this short explainer video.")
            audio_info = self.tts.synthesize(text, language=payload.get("language", "en"))
            return {"status": "SUCCESS", "audio": audio_info}
            
        elif stage == "MOCK_STILLS":
            scenes = payload.get("scenes", ["Scene 1", "Scene 2"])
            stills = [self.stills.generate_still(s, i) for i, s in enumerate(scenes)]
            return {"status": "SUCCESS", "stills": stills}
            
        elif stage == "MOCK_RENDER":
            return {
                "status": "SUCCESS",
                "simulated_render": True,
                "duration": payload.get("duration", 30.0)
            }
            
        else:
            return {"status": "SUCCESS", "stage": stage}

    def run_one_cycle(self) -> Optional[Dict[str, Any]]:
        if is_global_paused(self.db_path):
            return None

        if not self.check_guardrails():
            return None

        # Lease next job
        job = lease_next_job(self.worker_id, lease_duration_seconds=60, db_path=self.db_path)
        if not job:
            return None

        job_id = job["id"]
        stage = job["stage"]
        payload = job["payload"]

        try:
            # Send heartbeat
            heartbeat_job(job_id, self.worker_id, extension_seconds=60, db_path=self.db_path)

            # Process the stage
            result = self.process_job_stage(stage, payload)

            # Mark complete
            complete_job(job_id, self.worker_id, db_path=self.db_path)
            return {"job_id": job_id, "stage": stage, "result": result, "status": "COMPLETED"}

        except Exception as e:
            logger.exception(f"Job {job_id} failed during stage {stage}: {e}")
            fail_job(job_id, self.worker_id, error_msg=str(e), retryable=False, db_path=self.db_path)
            return {"job_id": job_id, "stage": stage, "error": str(e), "status": "FAILED"}

    def run_forever(self, poll_interval: float = 1.0):
        self._running = True
        logger.info(f"Worker {self.worker_id} started. Enforcing 1 GPU slot.")
        try:
            while self._running:
                job_result = self.run_one_cycle()
                if not job_result:
                    time.sleep(poll_interval)
        except KeyboardInterrupt:
            logger.info("Worker interrupted by user.")
        finally:
            self._running = False
