"""Single-worker runner enforcing 1 GPU slot, job leasing, and resource checks."""

import time
import logging
import uuid
from typing import Optional, Dict, Any
from pathlib import Path

from backend.app.config import (
    DB_PATH,
    check_system_resources
)
from backend.app.db.repository import (
    is_global_paused,
    lease_next_job,
    heartbeat_job,
    complete_job,
    fail_job
)
from backend.app.providers.mock_providers import (
    MockLLMProvider,
    MockStillsProvider,
    MockTTSProvider
)

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

    def process_job_stage(self, stage: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatches work based on stage."""
        if stage == "MOCK_SCRIPT":
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
            # Simulate composition
            return {
                "status": "SUCCESS",
                "simulated_render": True,
                "duration": payload.get("duration", 30.0)
            }
            
        else:
            # Generic fallback mock
            return {"status": "SUCCESS", "stage": stage}

    def run_one_cycle(self) -> Optional[Dict[str, Any]]:
        """
        Executes one lease-process-complete cycle.
        Returns job details if processed, None if no job or paused.
        """
        if is_global_paused(self.db_path):
            return None

        if not self.check_guardrails():
            return None

        # Lease next job
        job = lease_next_job(self.worker_id, lease_duration_seconds=30, db_path=self.db_path)
        if not job:
            return None

        job_id = job["id"]
        stage = job["stage"]
        payload = job["payload"]

        try:
            # Send heartbeat
            heartbeat_job(job_id, self.worker_id, extension_seconds=45, db_path=self.db_path)

            # Process the stage
            result = self.process_job_stage(stage, payload)

            # Mark complete
            complete_job(job_id, self.worker_id, db_path=self.db_path)
            return {"job_id": job_id, "stage": stage, "result": result, "status": "COMPLETED"}

        except Exception as e:
            logger.exception(f"Job {job_id} failed during stage {stage}: {e}")
            fail_job(job_id, self.worker_id, error_msg=str(e), retryable=True, db_path=self.db_path)
            return {"job_id": job_id, "stage": stage, "error": str(e), "status": "FAILED"}

    def run_forever(self, poll_interval: float = 1.0):
        """Continuous execution loop."""
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
