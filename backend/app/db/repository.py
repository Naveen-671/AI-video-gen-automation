"""Database repository operations for projects, scenes, jobs, renders, approvals, and settings."""

import json
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from pathlib import Path

from backend.app.config import DB_PATH
from backend.app.db.connection import get_connection, db_transaction
from backend.app.domain.state_machines import JobState, VideoState

def is_global_paused(db_path: Path = DB_PATH) -> bool:
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT value FROM settings WHERE key = 'global_pause'").fetchone()
        return (row["value"].lower() == "true") if row else False
    finally:
        conn.close()

def set_global_pause(paused: bool, db_path: Path = DB_PATH) -> bool:
    conn = get_connection(db_path)
    try:
        val = "true" if paused else "false"
        conn.execute(
            """
            INSERT INTO settings (key, value, updated_at) 
            VALUES ('global_pause', ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
            """,
            (val,)
        )
        record_audit("GLOBAL_PAUSE_TOGGLED", "system", {"paused": paused}, db_path=db_path)
        return paused
    finally:
        conn.close()

# Project & Scene Management

def create_project(
    topic: str,
    title: Optional[str] = None,
    target_audience: str = "General",
    language: str = "en",
    target_duration: float = 15.0,
    content_format: str = "explainer",
    narrative_archetype: str = "CURIOSITY_GAP",
    narration_mode: str = "silent",
    narration_voice: str = "af_bella",
    scenes: Optional[List[Dict[str, Any]]] = None,
    db_path: Path = DB_PATH
) -> str:
    """Creates a new video project with associated scenes."""
    project_id = str(uuid.uuid4())
    resolved_title = title or f"Short: {topic[:30]}"
    
    if scenes is None:
        dur = max(9.0, min(60.0, target_duration))
        s1_dur = round(dur * 0.3, 1)
        s2_dur = round(dur * 0.4, 1)
        s3_dur = round(dur - s1_dur - s2_dur, 1)
        scenes = [
            {"scene_index": 0, "scene_title": "The Hook", "narration_text": f"Did you know the secret behind {topic}?", "caption_text": f"The Secret of {topic}", "duration_seconds": s1_dur, "supporting_claim_ids": []},
            {"scene_index": 1, "scene_title": "The Core Insight", "narration_text": f"Here is how {topic} actually operates under the hood.", "caption_text": f"How {topic} Works", "duration_seconds": s2_dur, "supporting_claim_ids": []},
            {"scene_index": 2, "scene_title": "The Takeaway", "narration_text": f"That is why {topic} matters today. Follow for more!", "caption_text": "Follow for More Insights!", "duration_seconds": s3_dur, "supporting_claim_ids": []}
        ]
    
    with db_transaction(db_path) as conn:
        conn.execute(
            """
            INSERT INTO projects (
                id, title, topic, target_audience, language, target_duration, content_format, narrative_archetype, narration_mode, narration_voice, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                resolved_title,
                topic,
                target_audience,
                language,
                target_duration,
                content_format,
                narrative_archetype,
                narration_mode,
                narration_voice,
                VideoState.STORYBOARD.value
            )
        )

        if scenes:
            for s in scenes:
                scene_id = str(uuid.uuid4())
                claims_val = s.get("supporting_claim_ids", [])
                claims_json = json.dumps(claims_val if isinstance(claims_val, list) else [])
                conn.execute(
                    """
                    INSERT INTO project_scenes (
                        id, project_id, scene_index, scene_title, narration_text, caption_text, duration_seconds, visual_asset_path, motion_preset, visual_source_type, asset_provenance_id, supporting_claim_ids
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        scene_id,
                        project_id,
                        s.get("scene_index", 0),
                        s.get("scene_title", f"Scene {s.get('scene_index', 0) + 1}"),
                        s.get("narration_text", ""),
                        s.get("caption_text", ""),
                        float(s.get("duration_seconds", 5.0)),
                        s.get("visual_asset_path"),
                        s.get("motion_preset", "zoom_in"),
                        s.get("visual_source_type", "DEFAULT_BACKGROUND"),
                        s.get("asset_provenance_id"),
                        claims_json
                    )
                )

    record_audit("PROJECT_CREATED", project_id, {"topic": topic, "format": content_format}, db_path=db_path)
    return project_id

def get_project(project_id: str, db_path: Path = DB_PATH) -> Optional[Dict[str, Any]]:
    conn = get_connection(db_path)
    try:
        p_row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not p_row:
            return None
        project = dict(p_row)

        s_rows = conn.execute(
            "SELECT * FROM project_scenes WHERE project_id = ? ORDER BY scene_index ASC",
            (project_id,)
        ).fetchall()
        scenes_list = []
        for s in s_rows:
            sd = dict(s)
            val = sd.get("supporting_claim_ids")
            if isinstance(val, str):
                try:
                    sd["supporting_claim_ids"] = json.loads(val)
                except Exception:
                    sd["supporting_claim_ids"] = []
            elif val is None:
                sd["supporting_claim_ids"] = []
            scenes_list.append(sd)
        project["scenes"] = scenes_list

        # Attach fact sources and claims
        try:
            src_rows = conn.execute(
                "SELECT * FROM fact_sources WHERE project_id = ? ORDER BY retrieved_at ASC",
                (project_id,)
            ).fetchall()
            project["fact_sources"] = [dict(src) for src in src_rows]

            claim_rows = conn.execute(
                """
                SELECT c.*, s.url as source_url, s.title as source_title
                FROM fact_claims c
                LEFT JOIN fact_sources s ON c.source_id = s.id
                WHERE c.project_id = ?
                ORDER BY c.created_at ASC
                """,
                (project_id,)
            ).fetchall()
            project["fact_claims"] = [dict(c) for c in claim_rows]
        except sqlite3.OperationalError:
            project["fact_sources"] = []
            project["fact_claims"] = []

        # Attach current render if any
        if project.get("current_render_id"):
            r_row = conn.execute("SELECT * FROM renders WHERE id = ?", (project["current_render_id"],)).fetchone()
            if r_row:
                project["current_render"] = dict(r_row)
                # Check for active approval
                app_row = conn.execute(
                    "SELECT * FROM approvals WHERE render_id = ? AND superseded_at IS NULL",
                    (project["current_render_id"],)
                ).fetchone()
                project["active_approval"] = dict(app_row) if app_row else None
            else:
                project["current_render"] = None
                project["active_approval"] = None
        else:
            project["current_render"] = None
            project["active_approval"] = None

        # Attach asset provenances and editorial review
        try:
            ap_rows = conn.execute(
                "SELECT * FROM asset_provenance WHERE project_id = ? ORDER BY scene_index ASC",
                (project_id,)
            ).fetchall()
            project["asset_provenances"] = [dict(r) for r in ap_rows]
        except Exception:
            project["asset_provenances"] = []

        try:
            er_row = conn.execute(
                "SELECT * FROM editorial_reviews WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
                (project_id,)
            ).fetchone()
            if er_row:
                erd = dict(er_row)
                erd["hook_evaluation"] = json.loads(erd.get("hook_evaluation_json", "{}"))
                erd["pacing_evaluation"] = json.loads(erd.get("pacing_evaluation_json", "{}"))
                erd["relevance_evaluation"] = json.loads(erd.get("relevance_evaluation_json", "{}"))
                erd["audio_evaluation"] = json.loads(erd.get("audio_evaluation_json", "{}"))
                erd["warnings"] = json.loads(erd.get("warnings_json", "[]"))
                project["editorial_review"] = erd
            else:
                project["editorial_review"] = None
        except Exception:
            project["editorial_review"] = None

        return project
    finally:
        conn.close()

def list_projects(limit: int = 50, db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT p.*, r.render_checksum, r.file_path as render_file_path, a.status as approval_status
            FROM projects p
            LEFT JOIN renders r ON p.current_render_id = r.id
            LEFT JOIN approvals a ON r.id = a.render_id AND a.superseded_at IS NULL
            ORDER BY p.created_at DESC
            LIMIT ?
            """,
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def update_project_storyboard(project_id: str, scenes: List[Dict[str, Any]], db_path: Path = DB_PATH) -> bool:
    """Updates scenes for a project. If project has an approved render, invalidates approval (ADR-02 / ADR-04)."""
    with db_transaction(db_path) as conn:
        project = conn.execute("SELECT current_render_id, status FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not project:
            return False

        # If project had an approved render, supersede its approval
        if project["current_render_id"]:
            conn.execute(
                """
                UPDATE approvals
                SET superseded_at = CURRENT_TIMESTAMP
                WHERE render_id = ? AND superseded_at IS NULL
                """,
                (project["current_render_id"],)
            )

        # Clear existing scenes
        conn.execute("DELETE FROM project_scenes WHERE project_id = ?", (project_id,))

        # Insert updated scenes
        for s in scenes:
            scene_id = str(uuid.uuid4())
            claims_val = s.get("supporting_claim_ids", [])
            claims_json = json.dumps(claims_val if isinstance(claims_val, list) else [])
            conn.execute(
                """
                INSERT INTO project_scenes (
                    id, project_id, scene_index, scene_title, narration_text, caption_text, duration_seconds, visual_asset_path, motion_preset, visual_source_type, asset_provenance_id, supporting_claim_ids
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scene_id,
                    project_id,
                    s.get("scene_index", 0),
                    s.get("scene_title", f"Scene {s.get('scene_index', 0) + 1}"),
                    s.get("narration_text", ""),
                    s.get("caption_text", ""),
                    float(s.get("duration_seconds", 5.0)),
                    s.get("visual_asset_path"),
                    s.get("motion_preset", "zoom_in"),
                    s.get("visual_source_type", "DEFAULT_BACKGROUND"),
                    s.get("asset_provenance_id"),
                    claims_json
                )
            )

        # Drop project status back to STORYBOARD / AWAITING_APPROVAL
        conn.execute(
            """
            UPDATE projects
            SET status = 'STORYBOARD', current_render_id = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (project_id,)
        )

    record_audit("PROJECT_STORYBOARD_UPDATED", project_id, {"scenes_count": len(scenes)}, db_path=db_path)
    return True

def update_scene_visual(scene_id: str, visual_asset_path: str, db_path: Path = DB_PATH) -> bool:
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            "UPDATE project_scenes SET visual_asset_path = ? WHERE id = ?",
            (visual_asset_path, scene_id)
        )
        return cursor.rowcount > 0
    finally:
        conn.close()

def update_project_audio(project_id: str, audio_path: str, narration_mode: str = "manual_audio", db_path: Path = DB_PATH) -> bool:
    """Updates narration audio for a project. If project has an approved render, invalidates approval (ADR-02 / ADR-04)."""
    with db_transaction(db_path) as conn:
        project = conn.execute("SELECT current_render_id FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not project:
            return False

        if project["current_render_id"]:
            conn.execute(
                """
                UPDATE approvals
                SET superseded_at = CURRENT_TIMESTAMP
                WHERE render_id = ? AND superseded_at IS NULL
                """,
                (project["current_render_id"],)
            )
            conn.execute(
                "UPDATE projects SET current_render_id = NULL, status = 'STORYBOARD' WHERE id = ?",
                (project_id,)
            )

        cursor = conn.execute(
            "UPDATE projects SET narration_audio_path = ?, narration_mode = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (audio_path, narration_mode, project_id)
        )
        return cursor.rowcount > 0

def update_project_narration(
    project_id: str,
    narration_mode: str,
    narration_voice: str = "af_bella",
    audio_path: Optional[str] = None,
    db_path: Path = DB_PATH
) -> bool:
    """Updates narration settings (mode, voice, audio path) and invalidates approval if active render exists."""
    with db_transaction(db_path) as conn:
        project = conn.execute("SELECT current_render_id FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not project:
            return False

        if project["current_render_id"]:
            conn.execute(
                """
                UPDATE approvals
                SET superseded_at = CURRENT_TIMESTAMP
                WHERE render_id = ? AND superseded_at IS NULL
                """,
                (project["current_render_id"],)
            )
            conn.execute(
                "UPDATE projects SET current_render_id = NULL, status = 'STORYBOARD' WHERE id = ?",
                (project_id,)
            )

        cursor = conn.execute(
            "UPDATE projects SET narration_mode = ?, narration_voice = ?, narration_audio_path = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (narration_mode, narration_voice, audio_path, project_id)
        )
        return cursor.rowcount > 0

def set_project_render(project_id: str, render_id: str, status: str = "AWAITING_APPROVAL", db_path: Path = DB_PATH) -> bool:
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            "UPDATE projects SET current_render_id = ?, status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (render_id, status, project_id)
        )
        return cursor.rowcount > 0
    finally:
        conn.close()

def set_project_status(project_id: str, status: str, db_path: Path = DB_PATH) -> bool:
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            "UPDATE projects SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, project_id)
        )
        return cursor.rowcount > 0
    finally:
        conn.close()

# Job Operations

def create_job(stage: str, payload: dict, idempotency_key: str, max_attempts: int = 3, db_path: Path = DB_PATH) -> str:
    """Inserts a new job or returns existing ID if idempotency key matches."""
    job_id = str(uuid.uuid4())
    conn = get_connection(db_path)
    try:
        existing = conn.execute("SELECT id FROM jobs WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
        if existing:
            return existing["id"]
        
        conn.execute(
            """
            INSERT INTO jobs (id, stage, payload_json, idempotency_key, status, max_attempts)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (job_id, stage, json.dumps(payload), idempotency_key, JobState.QUEUED.value, max_attempts)
        )
        record_audit("JOB_CREATED", job_id, {"stage": stage, "idempotency_key": idempotency_key}, db_path=db_path)
        return job_id
    finally:
        conn.close()

def lease_next_job(worker_token: str, lease_duration_seconds: int = 60, db_path: Path = DB_PATH) -> Optional[Dict[str, Any]]:
    """Atomically leases the next available job using BEGIN IMMEDIATE."""
    if is_global_paused(db_path):
        return None

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=lease_duration_seconds)
    now_iso = now.isoformat()
    expires_iso = expires_at.isoformat()

    with db_transaction(db_path) as conn:
        # Reclaim any expired leases first
        conn.execute(
            """
            UPDATE jobs 
            SET status = 'QUEUED', lease_token = NULL, lease_expires_at = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE status = 'LEASED' AND lease_expires_at < ?
            """,
            (now_iso,)
        )

        # Select the oldest queued job
        job = conn.execute(
            """
            SELECT id, stage, payload_json, attempts, max_attempts, idempotency_key
            FROM jobs
            WHERE status = 'QUEUED'
            ORDER BY created_at ASC
            LIMIT 1
            """
        ).fetchone()

        if not job:
            return None

        job_id = job["id"]
        new_attempts = job["attempts"] + 1

        # Atomically lease
        conn.execute(
            """
            UPDATE jobs
            SET status = 'LEASED', lease_token = ?, lease_expires_at = ?, attempts = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'QUEUED'
            """,
            (worker_token, expires_iso, new_attempts, job_id)
        )

        return {
            "id": job_id,
            "stage": job["stage"],
            "payload": json.loads(job["payload_json"]),
            "attempts": new_attempts,
            "max_attempts": job["max_attempts"],
            "idempotency_key": job["idempotency_key"],
            "lease_token": worker_token,
            "lease_expires_at": expires_iso
        }

def heartbeat_job(job_id: str, worker_token: str, extension_seconds: int = 60, db_path: Path = DB_PATH) -> bool:
    """Extends the lease duration for an actively leased job."""
    new_expires_iso = (datetime.now(timezone.utc) + timedelta(seconds=extension_seconds)).isoformat()
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            """
            UPDATE jobs
            SET lease_expires_at = ?, status = 'RUNNING', updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND lease_token = ? AND status IN ('LEASED', 'RUNNING')
            """,
            (new_expires_iso, job_id, worker_token)
        )
        return cursor.rowcount > 0
    finally:
        conn.close()

def complete_job(job_id: str, worker_token: str, db_path: Path = DB_PATH) -> bool:
    """Marks a leased job as SUCCEEDED and clears the lease token."""
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            """
            UPDATE jobs
            SET status = 'SUCCEEDED', lease_token = NULL, lease_expires_at = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND lease_token = ?
            """,
            (job_id, worker_token)
        )
        if cursor.rowcount > 0:
            record_audit("JOB_SUCCEEDED", job_id, {}, db_path=db_path)
            return True
        return False
    finally:
        conn.close()

def fail_job(job_id: str, worker_token: str, error_msg: str, retryable: bool = True, db_path: Path = DB_PATH) -> bool:
    """Handles job failure: either re-queues if attempts < max_attempts or marks permanent failure."""
    conn = get_connection(db_path)
    try:
        job = conn.execute("SELECT attempts, max_attempts FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not job:
            return False

        if retryable and job["attempts"] < job["max_attempts"]:
            new_status = JobState.QUEUED.value
        else:
            new_status = JobState.FAILED_PERMANENT.value

        cursor = conn.execute(
            """
            UPDATE jobs
            SET status = ?, lease_token = NULL, lease_expires_at = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND lease_token = ?
            """,
            (new_status, job_id, worker_token)
        )
        record_audit("JOB_FAILED", job_id, {"error": error_msg, "status": new_status}, db_path=db_path)
        return cursor.rowcount > 0
    finally:
        conn.close()

def list_jobs(limit: int = 50, db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT id, stage, status, attempts, max_attempts, idempotency_key, lease_expires_at, created_at, updated_at
            FROM jobs
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,)
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()

# Renders & Approvals

def create_render(
    render_id: str,
    checksum: str,
    recipe_json: str,
    project_id: Optional[str] = None,
    variant_id: Optional[str] = None,
    file_path: Optional[str] = None,
    qa_status: str = "PASSED",
    db_path: Path = DB_PATH
) -> str:
    conn = get_connection(db_path)
    try:
        conn.execute(
            """
            INSERT INTO renders (id, project_id, localized_variant_id, render_checksum, recipe_json, file_path, qa_status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (render_id, project_id, variant_id, checksum, recipe_json, file_path, qa_status)
        )
        record_audit("RENDER_CREATED", render_id, {"checksum": checksum, "project_id": project_id}, db_path=db_path)
        return render_id
    finally:
        conn.close()

def get_render(render_id: str, db_path: Path = DB_PATH) -> Optional[Dict[str, Any]]:
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT * FROM renders WHERE id = ?", (render_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def create_approval(
    approval_id: str,
    render_id: str,
    checksum: str,
    reviewer: str = "human_operator",
    status: str = "APPROVED",
    notes: Optional[str] = None,
    db_path: Path = DB_PATH
) -> str:
    conn = get_connection(db_path)
    try:
        conn.execute(
            """
            INSERT INTO approvals (id, render_id, render_checksum, reviewer, status, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (approval_id, render_id, checksum, reviewer, status, notes)
        )
        record_audit("APPROVAL_RECORDED", approval_id, {"render_id": render_id, "status": status, "checksum": checksum}, db_path=db_path)
        return approval_id
    finally:
        conn.close()

def supersede_approval_for_render(render_id: str, db_path: Path = DB_PATH) -> int:
    """Invalidates existing approvals for a render when an edit occurs."""
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            """
            UPDATE approvals
            SET superseded_at = CURRENT_TIMESTAMP
            WHERE render_id = ? AND superseded_at IS NULL
            """,
            (render_id,)
        )
        count = cursor.rowcount
        if count > 0:
            record_audit("APPROVAL_SUPERSEDED", render_id, {"superseded_count": count}, db_path=db_path)
        return count
    finally:
        conn.close()

def record_audit(event_type: str, entity_id: str, details: dict, db_path: Path = DB_PATH):
    conn = get_connection(db_path)
    try:
        conn.execute(
            "INSERT INTO audit_log (event_type, entity_id, details_json) VALUES (?, ?, ?)",
            (event_type, entity_id, json.dumps(details))
        )
    finally:
        conn.close()

# FactLedger & Script Proposal Persistence (Stage 2)

def create_fact_source(
    source_id: str,
    url: str,
    title: str,
    project_id: Optional[str] = None,
    published_date: Optional[str] = None,
    raw_excerpt: Optional[str] = None,
    http_status: int = 200,
    db_path: Path = DB_PATH
) -> str:
    with db_transaction(db_path) as conn:
        conn.execute(
            """
            INSERT INTO fact_sources (
                id, project_id, url, title, published_date, raw_excerpt, http_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (source_id, project_id, url, title, published_date, raw_excerpt, http_status)
        )
    return source_id

def create_fact_claim(
    claim_id: str,
    claim_text: str,
    quote_excerpt: str,
    source_id: Optional[str] = None,
    project_id: Optional[str] = None,
    evidence_status: str = "UNVERIFIED",
    uncertainty_rationale: Optional[str] = None,
    db_path: Path = DB_PATH
) -> str:
    with db_transaction(db_path) as conn:
        conn.execute(
            """
            INSERT INTO fact_claims (
                id, source_id, project_id, claim_text, quote_excerpt, evidence_status, uncertainty_rationale
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (claim_id, source_id, project_id, claim_text, quote_excerpt, evidence_status, uncertainty_rationale)
        )
    return claim_id

def get_fact_sources(project_id: str, db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM fact_sources WHERE project_id = ? ORDER BY retrieved_at ASC",
            (project_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def get_fact_claims(project_id: str, db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT c.*, s.url as source_url, s.title as source_title
            FROM fact_claims c
            LEFT JOIN fact_sources s ON c.source_id = s.id
            WHERE c.project_id = ?
            ORDER BY c.created_at ASC
            """,
            (project_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def save_script_proposal(
    proposal_id: str,
    topic: str,
    target_audience: str,
    narrative_archetype: str,
    hook_text: str,
    scenes: List[Dict[str, Any]],
    validation: Dict[str, Any],
    project_id: Optional[str] = None,
    db_path: Path = DB_PATH
) -> str:
    with db_transaction(db_path) as conn:
        conn.execute(
            """
            INSERT INTO script_proposals (
                id, project_id, topic, target_audience, narrative_archetype, hook_text, scenes_json, validation_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                proposal_id,
                project_id,
                topic,
                target_audience,
                narrative_archetype,
                hook_text,
                json.dumps(scenes),
                json.dumps(validation)
            )
        )
    return proposal_id

def get_script_proposal(proposal_id: str, db_path: Path = DB_PATH) -> Optional[Dict[str, Any]]:
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM script_proposals WHERE id = ?",
            (proposal_id,)
        ).fetchone()
        if not row:
            return None
        res = dict(row)
        res["scenes"] = json.loads(res.get("scenes_json", "[]"))
        res["validation"] = json.loads(res.get("validation_json", "{}"))
        return res
    finally:
        conn.close()

def update_scene_visual_and_motion(
    scene_id: str,
    visual_asset_path: str,
    motion_preset: str = "zoom_in",
    visual_source_type: str = "FLOW_REQUIRED",
    asset_provenance_id: Optional[str] = None,
    db_path: Path = DB_PATH
) -> bool:
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            """
            UPDATE project_scenes 
            SET visual_asset_path = ?, motion_preset = ?, visual_source_type = ?, asset_provenance_id = ?
            WHERE id = ?
            """,
            (visual_asset_path, motion_preset, visual_source_type, asset_provenance_id, scene_id)
        )
        return cursor.rowcount > 0
    finally:
        conn.close()

def save_asset_provenance(
    provenance_id: str,
    project_id: str,
    scene_index: int,
    asset_type: str,
    local_path: str,
    sha256_checksum: str,
    source_url: Optional[str] = None,
    author: Optional[str] = None,
    license: Optional[str] = None,
    attribution_text: Optional[str] = None,
    associated_claim_id: Optional[str] = None,
    source_asset_id: Optional[str] = None,
    source_page_url: Optional[str] = None,
    license_url: Optional[str] = None,
    media_type: str = "image",
    original_width: Optional[int] = None,
    original_height: Optional[int] = None,
    original_duration: Optional[float] = None,
    file_size_bytes: Optional[int] = None,
    rights_status: str = "VERIFIED_FREE",
    crop_transform: Optional[str] = None,
    selection_reason: Optional[str] = None,
    db_path: Path = DB_PATH
) -> str:
    with db_transaction(db_path) as conn:
        conn.execute(
            """
            INSERT INTO asset_provenance (
                id, project_id, scene_index, asset_type, source_url, author, license, attribution_text,
                local_path, sha256_checksum, associated_claim_id, source_asset_id, source_page_url,
                license_url, media_type, original_width, original_height, original_duration,
                file_size_bytes, rights_status, crop_transform, selection_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                provenance_id,
                project_id,
                scene_index,
                asset_type,
                source_url,
                author,
                license,
                attribution_text,
                local_path,
                sha256_checksum,
                associated_claim_id,
                source_asset_id,
                source_page_url,
                license_url,
                media_type,
                original_width,
                original_height,
                original_duration,
                file_size_bytes,
                rights_status,
                crop_transform,
                selection_reason
            )
        )
    return provenance_id

def get_asset_provenances(project_id: str, db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM asset_provenance WHERE project_id = ? ORDER BY scene_index ASC",
            (project_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def save_editorial_review(
    review_id: str,
    project_id: str,
    overall_status: str,
    score: int,
    hook_evaluation: Dict[str, Any],
    pacing_evaluation: Dict[str, Any],
    relevance_evaluation: Dict[str, Any],
    audio_evaluation: Dict[str, Any],
    warnings: List[Dict[str, Any]],
    render_id: Optional[str] = None,
    db_path: Path = DB_PATH
) -> str:
    with db_transaction(db_path) as conn:
        conn.execute(
            """
            INSERT INTO editorial_reviews (
                id, project_id, render_id, overall_status, score,
                hook_evaluation_json, pacing_evaluation_json, relevance_evaluation_json, audio_evaluation_json, warnings_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                review_id,
                project_id,
                render_id,
                overall_status,
                score,
                json.dumps(hook_evaluation),
                json.dumps(pacing_evaluation),
                json.dumps(relevance_evaluation),
                json.dumps(audio_evaluation),
                json.dumps(warnings)
            )
        )
    return review_id

def get_editorial_review(project_id: str, render_id: Optional[str] = None, db_path: Path = DB_PATH) -> Optional[Dict[str, Any]]:
    conn = get_connection(db_path)
    try:
        if render_id:
            row = conn.execute(
                "SELECT * FROM editorial_reviews WHERE project_id = ? AND render_id = ? ORDER BY created_at DESC LIMIT 1",
                (project_id, render_id)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM editorial_reviews WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
                (project_id,)
            ).fetchone()
        if not row:
            return None
        res = dict(row)
        res["hook_evaluation"] = json.loads(res.get("hook_evaluation_json", "{}"))
        res["pacing_evaluation"] = json.loads(res.get("pacing_evaluation_json", "{}"))
        res["relevance_evaluation"] = json.loads(res.get("relevance_evaluation_json", "{}"))
        res["audio_evaluation"] = json.loads(res.get("audio_evaluation_json", "{}"))
        res["warnings"] = json.loads(res.get("warnings_json", "[]"))
        return res
    finally:
        conn.close()

# ==============================================================================
# STAGE 6: OAUTH STATE & PUBLISHING ATTEMPTS REPOSITORY
# ==============================================================================

def save_oauth_state(state: str, platform: str, expires_in_seconds: int = 600, db_path: Path = DB_PATH) -> str:
    """Persists an OAuth CSRF state token with an absolute expiration timestamp."""
    with db_transaction(db_path) as conn:
        conn.execute(
            """
            INSERT INTO oauth_states (state, platform, expires_at)
            VALUES (?, ?, datetime(CURRENT_TIMESTAMP, '+' || ? || ' seconds'))
            """,
            (state, platform, int(expires_in_seconds))
        )
    return state

def validate_and_consume_oauth_state(state: str, platform: str = "youtube", db_path: Path = DB_PATH) -> bool:
    """
    Validates that state exists, is for the expected platform, has not expired,
    and has not been previously consumed. Marks it used atomically.
    """
    with db_transaction(db_path) as conn:
        row = conn.execute(
            """
            SELECT state FROM oauth_states
            WHERE state = ?
              AND platform = ?
              AND used_at IS NULL
              AND expires_at > CURRENT_TIMESTAMP
            """,
            (state, platform)
        ).fetchone()
        if not row:
            return False
        conn.execute(
            "UPDATE oauth_states SET used_at = CURRENT_TIMESTAMP WHERE state = ?",
            (state,)
        )
        return True

def get_active_approval_for_render(render_id: str, db_path: Path = DB_PATH) -> Optional[Dict[str, Any]]:
    """Retrieves the active, non-superseded APPROVED record for a render matching its exact checksum."""
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            """
            SELECT a.* FROM approvals a
            JOIN renders r ON a.render_id = r.id
            WHERE a.render_id = ?
              AND a.render_checksum = r.render_checksum
              AND a.status = 'APPROVED'
              AND a.superseded_at IS NULL
            ORDER BY a.created_at DESC LIMIT 1
            """,
            (render_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def create_publish_attempt(
    attempt_id: str,
    approval_id: str,
    render_id: str,
    platform: str,
    target_channel_id: str,
    idempotency_key: str,
    db_path: Path = DB_PATH
) -> str:
    """
    Records a publish attempt.
    CRITICAL: Subject to enforce_valid_approval_before_publish database trigger.
    Will raise sqlite3.IntegrityError if approval is invalid, missing, or superseded.
    """
    with db_transaction(db_path) as conn:
        conn.execute(
            """
            INSERT INTO publish_attempts (
                id, approval_id, render_id, platform, target_channel_id, status, idempotency_key
            ) VALUES (?, ?, ?, ?, ?, 'PENDING', ?)
            """,
            (attempt_id, approval_id, render_id, platform, target_channel_id, idempotency_key)
        )
    return attempt_id

def update_publish_attempt_status(
    attempt_id: str,
    status: str,
    external_id: Optional[str] = None,
    error_message: Optional[str] = None,
    db_path: Path = DB_PATH
) -> bool:
    """Updates the status and external ID (e.g. YouTube video ID) of a publish attempt."""
    with db_transaction(db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE publish_attempts
            SET status = ?, external_id = COALESCE(?, external_id), error_message = ?
            WHERE id = ?
            """,
            (status, external_id, error_message, attempt_id)
        )
        return cursor.rowcount > 0

def get_publish_attempt(attempt_id: str, db_path: Path = DB_PATH) -> Optional[Dict[str, Any]]:
    """Retrieves a publish attempt by its ID."""
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM publish_attempts WHERE id = ?",
            (attempt_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def get_publish_attempts_for_render(render_id: str, db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    """Retrieves all publish attempts for a render ordered by created_at DESC."""
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM publish_attempts WHERE render_id = ? ORDER BY created_at DESC",
            (render_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def get_publish_attempts_for_project(project_id: str, db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    """Retrieves all publish attempts for all renders of a project."""
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT pa.*, r.render_checksum, r.file_path
            FROM publish_attempts pa
            JOIN renders r ON pa.render_id = r.id
            WHERE r.project_id = ?
            ORDER BY pa.created_at DESC
            """,
            (project_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

