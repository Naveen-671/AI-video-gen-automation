"""FastAPI application providing health, pause, jobs, projects, renders, and static frontend."""

from fastapi import FastAPI, HTTPException, status, Request, Query
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, List, Dict, Any
import os
import uuid
import logging

logger = logging.getLogger("api")

from backend.app.config import (
    DB_PATH,
    MEDIA_DIR,
    FRONTEND_OUT_DIR,
    ALLOWED_COST_CLASSES,
    check_system_resources
)
from backend.app.db.connection import init_db, get_connection
from backend.app.db.repository import (
    is_global_paused,
    set_global_pause,
    create_job,
    list_jobs,
    create_project,
    get_project,
    list_projects,
    update_project_storyboard,
    update_scene_visual,
    update_project_audio,
    update_project_narration,
    set_project_status,
    get_render,
    create_approval,
    supersede_approval_for_render,
    get_fact_sources,
    get_fact_claims,
    get_editorial_review,
    get_asset_provenances,
    get_publish_attempts_for_project
)
from backend.app.publishing.secrets import save_client_secret
from backend.app.publishing.youtube_oauth import YouTubeOAuthManager
from backend.app.publishing.youtube_uploader import YouTubeUploader, YouTubeUploadError
from backend.app.media.narration import LocalTTSAdapter
from backend.app.research.agent import ResearchAgent
from backend.app.domain.models import (
    HealthResponse,
    PauseRequest,
    PauseResponse,
    JobCreate,
    JobResponse,
    SystemResources,
    ProjectCreate,
    ProjectResponse,
    ProjectDetailResponse,
    ProjectUpdateStoryboard,
    ProjectUpdateNarration,
    ApprovalAction,
    SceneModel,
    ResearchRequest,
    ResearchResponse,
    FactSourceModel,
    FactClaimModel
)
from backend.app.media.assets import save_uploaded_asset, AssetValidationError

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure database tables and triggers exist
    init_db(DB_PATH)
    yield

# Ensure database tables exist at import time for test clients
init_db(DB_PATH)

app = FastAPI(
    title="AI Shorts & Reels Factory API",
    version="1.0.0",
    lifespan=lifespan
)

# Enforce localhost origin safety
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

# --- System & Health Endpoints ---

@app.get("/health", response_model=HealthResponse)
def get_health():
    """System health endpoint reporting resource headroom, DB connectivity, and pause state."""
    db_connected = False
    active_count = 0
    try:
        conn = get_connection(DB_PATH)
        row = conn.execute("SELECT COUNT(*) as cnt FROM jobs WHERE status IN ('QUEUED', 'LEASED', 'RUNNING')").fetchone()
        active_count = row["cnt"] if row else 0
        db_connected = True
        conn.close()
    except Exception:
        db_connected = False

    res = check_system_resources()
    paused = is_global_paused(DB_PATH)

    return HealthResponse(
        status="HEALTHY" if (db_connected and res["can_process_jobs"]) else "DEGRADED",
        db_connected=db_connected,
        global_pause=paused,
        resources=SystemResources(**res),
        enabled_cost_classes=sorted(list(ALLOWED_COST_CLASSES)),
        active_jobs_count=active_count
    )

@app.post("/pause", response_model=PauseResponse)
def toggle_pause(req: PauseRequest):
    """Toggles global system pause. Pauses worker job leasing without killing in-flight tasks."""
    updated = set_global_pause(req.paused, DB_PATH)
    msg = "System paused. No new jobs will be leased." if updated else "System unpaused. Job leasing resumed."
    return PauseResponse(global_pause=updated, message=msg)

@app.get("/jobs", response_model=List[JobResponse])
def get_jobs(limit: int = 50):
    """Lists queued, active, and completed jobs."""
    jobs = list_jobs(limit=limit, db_path=DB_PATH)
    return [
        JobResponse(
            id=j["id"],
            stage=j["stage"],
            status=j["status"],
            attempts=j["attempts"],
            max_attempts=j["max_attempts"],
            idempotency_key=j["idempotency_key"],
            lease_expires_at=j["lease_expires_at"],
            created_at=str(j["created_at"]),
            updated_at=str(j["updated_at"])
        )
        for j in jobs
    ]

@app.post("/jobs", status_code=status.HTTP_201_CREATED)
def submit_job(job: JobCreate):
    """Enqueues a job into the SQLite worker queue."""
    job_id = create_job(
        stage=job.stage,
        payload=job.payload,
        idempotency_key=job.idempotency_key,
        max_attempts=job.max_attempts,
        db_path=DB_PATH
    )
    return {"job_id": job_id, "status": "QUEUED"}

# --- Video Projects Endpoints ---

@app.post("/projects", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
def create_video_project(req: ProjectCreate):
    """Creates a new video project with a validated initial storyboard."""
    scenes_data = []
    if req.scenes:
        scenes_data = [s.model_dump() for s in req.scenes]
    else:
        # Deterministic 3-scene proposal template
        dur = max(9.0, min(60.0, req.target_duration))
        s1_dur = round(dur * 0.3, 1)
        s2_dur = round(dur * 0.4, 1)
        s3_dur = round(dur - s1_dur - s2_dur, 1)

        scenes_data = [
            {
                "scene_index": 0,
                "scene_title": "The Hook",
                "narration_text": f"Did you know the secret behind {req.topic}?",
                "caption_text": f"The Secret of {req.topic}",
                "duration_seconds": s1_dur
            },
            {
                "scene_index": 1,
                "scene_title": "The Core Insight",
                "narration_text": f"Here is how {req.topic} actually operates under the hood.",
                "caption_text": f"How {req.topic} Works",
                "duration_seconds": s2_dur
            },
            {
                "scene_index": 2,
                "scene_title": "The Takeaway",
                "narration_text": f"That is why {req.topic} matters today. Follow for more!",
                "caption_text": "Follow for More Insights!",
                "duration_seconds": s3_dur
            }
        ]

    project_id = create_project(
        topic=req.topic,
        title=req.title,
        target_audience=req.target_audience,
        language=req.language,
        target_duration=req.target_duration,
        content_format=req.content_format,
        narrative_archetype=req.narrative_archetype or "CURIOSITY_GAP",
        narration_mode=req.narration_mode,
        narration_voice=req.narration_voice or "af_bella",
        scenes=scenes_data,
        db_path=DB_PATH
    )

    return {"project_id": project_id, "status": "STORYBOARD", "scenes_count": len(scenes_data)}

@app.get("/tts/voices")
def get_tts_voices():
    """Lists available local TTS voices from Kokoro."""
    try:
        adapter = LocalTTSAdapter()
        return {"voices": adapter.get_available_voices()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/research/discover", response_model=ResearchResponse)
def discover_research(req: ResearchRequest):
    """Executes topic intelligence, candidate discovery, FactLedger extraction, and archetype proposal."""
    try:
        agent = ResearchAgent(db_path=DB_PATH)
        return agent.run_research(req)
    except Exception as e:
        logger.exception("Research discovery failed for topic '%s'", req.topic)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/projects/{project_id}/facts")
def get_project_facts(project_id: str):
    """Retrieves FactLedger sources and claims for a project."""
    project = get_project(project_id, db_path=DB_PATH)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    sources = get_fact_sources(project_id, db_path=DB_PATH)
    claims = get_fact_claims(project_id, db_path=DB_PATH)
    return {"project_id": project_id, "sources": sources, "claims": claims}

@app.post("/projects/{project_id}/research", response_model=ResearchResponse)
def run_project_research(project_id: str, archetype: Optional[str] = None):
    """Runs research for an existing project and binds claims directly to its storyboard."""
    project = get_project(project_id, db_path=DB_PATH)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    
    req = ResearchRequest(
        topic=project["topic"],
        target_audience=project["target_audience"],
        narrative_archetype=archetype or project.get("narrative_archetype", "CURIOSITY_GAP"),
        project_id=project_id,
        max_sources=3
    )
    agent = ResearchAgent(db_path=DB_PATH)
    res = agent.run_research(req)

    # Automatically update project's storyboard scenes with proposed beats
    proposed_scenes = [s.model_dump() for s in res.proposal.scenes]
    update_project_storyboard(project_id, proposed_scenes, db_path=DB_PATH)

    return res

@app.get("/projects", response_model=List[ProjectResponse])
def get_projects(limit: int = 50):
    """Lists video projects."""
    projects = list_projects(limit=limit, db_path=DB_PATH)
    return [
        ProjectResponse(
            id=p["id"],
            title=p["title"],
            topic=p["topic"],
            target_audience=p["target_audience"],
            language=p["language"],
            target_duration=p["target_duration"],
            content_format=p["content_format"],
            narrative_archetype=p.get("narrative_archetype", "CURIOSITY_GAP"),
            narration_mode=p["narration_mode"],
            narration_voice=p.get("narration_voice", "af_bella"),
            status=p["status"],
            current_render_id=p["current_render_id"],
            render_checksum=p.get("render_checksum"),
            approval_status=p.get("approval_status"),
            created_at=str(p["created_at"])
        )
        for p in projects
    ]

@app.get("/projects/{project_id}", response_model=ProjectDetailResponse)
def get_project_details(project_id: str):
    """Retrieves full project details, storyboard scenes, and render artifacts."""
    project = get_project(project_id, db_path=DB_PATH)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    
    scenes = [SceneModel(**s) for s in project.get("scenes", [])]
    return ProjectDetailResponse(
        id=project["id"],
        title=project["title"],
        topic=project["topic"],
        target_audience=project["target_audience"],
        language=project["language"],
        target_duration=project["target_duration"],
        content_format=project["content_format"],
        narrative_archetype=project.get("narrative_archetype", "CURIOSITY_GAP"),
        narration_mode=project["narration_mode"],
        narration_voice=project.get("narration_voice", "af_bella"),
        narration_audio_path=project.get("narration_audio_path"),
        status=project["status"],
        current_render_id=project.get("current_render_id"),
        render_checksum=project.get("current_render", {}).get("render_checksum") if project.get("current_render") else None,
        approval_status=project.get("active_approval", {}).get("status") if project.get("active_approval") else None,
        scenes=scenes,
        current_render=project.get("current_render"),
        active_approval=project.get("active_approval"),
        fact_sources=project.get("fact_sources", []),
        fact_claims=project.get("fact_claims", []),
        created_at=str(project["created_at"])
    )

@app.put("/projects/{project_id}/storyboard")
def update_storyboard(project_id: str, req: ProjectUpdateStoryboard):
    """Updates scenes for a project. If project has an approved render, approval is automatically invalidated."""
    scenes_data = [s.model_dump() for s in req.scenes]
    success = update_project_storyboard(project_id, scenes_data, db_path=DB_PATH)
    if not success:
        raise HTTPException(status_code=404, detail="Project not found.")
    return {"project_id": project_id, "status": "STORYBOARD", "message": "Storyboard updated. Prior approvals superseded."}

@app.put("/projects/{project_id}/narration")
def set_project_narration(project_id: str, req: ProjectUpdateNarration):
    """Updates narration settings (mode, voice). If project has an approved render, approval is automatically invalidated."""
    success = update_project_narration(
        project_id=project_id,
        narration_mode=req.narration_mode,
        narration_voice=req.narration_voice or "af_bella",
        db_path=DB_PATH
    )
    if not success:
        raise HTTPException(status_code=404, detail="Project not found.")
    return {"project_id": project_id, "status": "STORYBOARD", "message": "Narration settings updated. Prior approvals superseded."}

@app.post("/projects/{project_id}/assets")
async def upload_asset(
    project_id: str,
    request: Request,
    filename: str = Query(..., description="Original filename with extension (e.g. scene.png, voice.wav)"),
    scene_id: Optional[str] = Query(None, description="Optional scene ID to link this visual asset to"),
    asset_type: str = Query("image", description="'image' or 'audio'")
):
    """Uploads an image or narration audio file for the project via binary request body."""
    project = get_project(project_id, db_path=DB_PATH)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")

    file_bytes = await request.body()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file body cannot be empty.")

    try:
        dest_path, sha256 = save_uploaded_asset(project_id, file_bytes, filename)
    except AssetValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if asset_type == "audio":
        update_project_audio(project_id, str(dest_path), narration_mode="manual_audio", db_path=DB_PATH)
    elif scene_id:
        update_scene_visual(scene_id, str(dest_path), db_path=DB_PATH)

    return {
        "status": "UPLOADED",
        "sha256": sha256,
        "filename": os.path.basename(str(dest_path)),
        "asset_type": asset_type
    }

@app.post("/projects/{project_id}/render")
def trigger_render(
    project_id: str,
    width: int = 720,
    height: int = 1280,
    fps: int = 30,
    enable_motion: bool = True,
    enable_bg_music: bool = True,
    enable_video_ingest: bool = True,
    enable_transitions: bool = True,
    transition_duration: float = 0.5,
    allow_placeholder_fallback: bool = Query(False, description="When False, rejects render if required footage is missing. When True, allows procedural fallback.")
):
    """Enqueues an immutable render job for the project with hybrid visual engine options."""
    project = get_project(project_id, db_path=DB_PATH)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")

    # Pre-flight check: if any scene is FLOW_REQUIRED and has no existing visual_asset_path, block render
    if not allow_placeholder_fallback:
        missing_scenes = []
        for i, s in enumerate(project.get("scenes", [])):
            st = s.get("visual_source_type", "DEFAULT_BACKGROUND")
            vp = s.get("visual_asset_path")
            if st in ("FLOW_REQUIRED", "USER_UPLOAD") and (not vp or not Path(vp).exists() or Path(vp).stat().st_size == 0):
                missing_scenes.append(f"Scene {i + 1} ('{s.get('scene_title', f'Scene {i+1}')}')")

        if missing_scenes:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Cannot queue render: Required footage missing for {', '.join(missing_scenes)}. "
                    "Import real video via Google Flow handoff ('data/inbox/') or explicitly enable 'allow_placeholder_fallback=true'."
                )
            )

    set_project_status(project_id, "GENERATING", db_path=DB_PATH)
    
    idempotency_key = f"render_{project_id}_{uuid.uuid4().hex[:8]}"
    job_id = create_job(
        stage="RENDER_PROJECT",
        payload={
            "project_id": project_id,
            "width": width,
            "height": height,
            "fps": fps,
            "enable_motion": enable_motion,
            "enable_bg_music": enable_bg_music,
            "enable_video_ingest": enable_video_ingest,
            "enable_transitions": enable_transitions,
            "transition_duration": transition_duration,
            "allow_placeholder_fallback": allow_placeholder_fallback
        },
        idempotency_key=idempotency_key,
        max_attempts=1,
        db_path=DB_PATH
    )

    return {"project_id": project_id, "job_id": job_id, "status": "QUEUED"}

@app.get("/projects/{project_id}/editorial")
def get_project_editorial_review(project_id: str):
    """Retrieves the latest editorial review for the project."""
    review = get_editorial_review(project_id, db_path=DB_PATH)
    if not review:
        raise HTTPException(status_code=404, detail="No editorial review found for this project.")
    return review

@app.get("/projects/{project_id}/provenance")
def get_project_provenance(project_id: str):
    """Retrieves visual asset provenance records for the project."""
    return get_asset_provenances(project_id, db_path=DB_PATH)

# --- Render & Approval Endpoints ---

@app.get("/renders/{render_id}/file")
def get_render_file(render_id: str):
    """Streams or downloads the rendered MP4 artifact."""
    render = get_render(render_id, db_path=DB_PATH)
    if not render:
        raise HTTPException(status_code=404, detail="Render not found.")

    file_path = Path(render["file_path"])
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Render file missing on disk.")

    return FileResponse(
        str(file_path),
        media_type="video/mp4",
        filename=file_path.name
    )

@app.post("/renders/{render_id}/approve")
def approve_render(render_id: str, action: ApprovalAction):
    """Approves a render tied to its exact SHA-256 checksum."""
    render = get_render(render_id, db_path=DB_PATH)
    if not render:
        raise HTTPException(status_code=404, detail="Render not found.")

    if render.get("qa_status") != "PASSED":
        raise HTTPException(status_code=400, detail="Cannot approve render that failed technical QA.")

    approval_id = str(uuid.uuid4())
    create_approval(
        approval_id=approval_id,
        render_id=render_id,
        checksum=render["render_checksum"],
        reviewer=action.reviewer,
        status="APPROVED",
        notes=action.notes,
        db_path=DB_PATH
    )

    if render.get("project_id"):
        set_project_status(render["project_id"], "APPROVED", db_path=DB_PATH)

    return {
        "approval_id": approval_id,
        "render_id": render_id,
        "render_checksum": render["render_checksum"],
        "status": "APPROVED"
    }

@app.post("/renders/{render_id}/reject")
def reject_render(render_id: str, action: ApprovalAction):
    """Rejects a render with operator feedback."""
    render = get_render(render_id, db_path=DB_PATH)
    if not render:
        raise HTTPException(status_code=404, detail="Render not found.")

    approval_id = str(uuid.uuid4())
    create_approval(
        approval_id=approval_id,
        render_id=render_id,
        checksum=render["render_checksum"],
        reviewer=action.reviewer,
        status="REJECTED",
        notes=action.notes,
        db_path=DB_PATH
    )

    if render.get("project_id"):
        set_project_status(render["project_id"], "REJECTED", db_path=DB_PATH)

    return {
        "approval_id": approval_id,
        "render_id": render_id,
        "status": "REJECTED",
        "notes": action.notes
    }

# ==============================================================================
# STAGE 6: YOUTUBE OAUTH & GUARDED PRIVATE PUBLISHING ENDPOINTS
# ==============================================================================

class ConfigureYouTubeClientRequest(BaseModel):
    client_id: str
    client_secret: str
    project_id: Optional[str] = "ai-shorts-factory"
    redirect_uri: Optional[str] = None

class YouTubeUploadRequest(BaseModel):
    project_id: str
    render_id: str
    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    category_id: str = "28"
    privacy_status: str = "private"

@app.get("/api/v1/auth/youtube/status")
def get_youtube_auth_status():
    """Returns safe YouTube OAuth connection status without exposing secrets."""
    manager = YouTubeOAuthManager(db_path=DB_PATH)
    return manager.get_status()

@app.post("/api/v1/auth/youtube/configure")
def configure_youtube_client(req: ConfigureYouTubeClientRequest):
    """Saves Google OAuth client ID and client secret to a 0600 permission-restricted file."""
    if not req.client_id.strip() or not req.client_secret.strip():
        raise HTTPException(status_code=400, detail="client_id and client_secret cannot be empty.")
    redirect_uris = [req.redirect_uri.strip()] if req.redirect_uri else None
    save_client_secret(
        client_id=req.client_id,
        client_secret=req.client_secret,
        project_id=req.project_id or "ai-shorts-factory",
        redirect_uris=redirect_uris
    )
    return {
        "status": "SUCCESS",
        "message": "Google OAuth client credentials saved with mode 0600 permissions."
    }

@app.get("/api/v1/auth/youtube/authorize")
def get_youtube_authorization_url(redirect_uri: Optional[str] = None):
    """Generates an OAuth authorization URL with CSRF state protection."""
    manager = YouTubeOAuthManager(db_path=DB_PATH)
    try:
        auth_url, state = manager.get_authorization_url(redirect_uri=redirect_uri)
        return {"authorization_url": auth_url, "state": state}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/v1/auth/youtube/callback", response_class=HTMLResponse)
def handle_youtube_oauth_callback(code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None):
    """Handles redirect from Google OAuth consent screen."""
    if error:
        return HTMLResponse(
            content=f"<html><body style='font-family:sans-serif;padding:2rem;'><h2>Authentication Cancelled</h2><p>{error}</p><a href='/'>Return to Dashboard</a></body></html>",
            status_code=400
        )
    if not code or not state:
        return HTMLResponse(
            content="<html><body style='font-family:sans-serif;padding:2rem;'><h2>OAuth Error</h2><p>Missing code or state.</p><a href='/'>Return to Dashboard</a></body></html>",
            status_code=400
        )

    manager = YouTubeOAuthManager(db_path=DB_PATH)
    try:
        res = manager.handle_oauth_callback(code=code, state=state)
        channel_name = res.get("channel_title", "Authorized Channel")
        return HTMLResponse(
            content=f"""
            <html>
            <head><title>YouTube Connected</title></head>
            <body style='font-family:system-ui,-apple-system,sans-serif;background:#0f172a;color:#f8fafc;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;'>
              <div style='background:#1e293b;padding:2.5rem;border-radius:12px;box-shadow:0 10px 25px rgba(0,0,0,0.5);text-align:center;max-width:440px;'>
                <div style='font-size:3rem;margin-bottom:1rem;'>🎉</div>
                <h2 style='color:#38bdf8;margin:0 0 0.75rem 0;'>YouTube Connected!</h2>
                <p style='color:#94a3b8;margin-bottom:1.5rem;'>Authorized channel: <strong style='color:#f8fafc;'>{channel_name}</strong></p>
                <a href='/' style='background:#0284c7;color:#fff;padding:0.75rem 1.5rem;text-decoration:none;border-radius:6px;font-weight:600;'>Return to Dashboard</a>
              </div>
            </body>
            </html>
            """
        )
    except Exception as e:
        logger.error(f"OAuth callback failed: {e}")
        return HTMLResponse(
            content=f"<html><body style='font-family:sans-serif;padding:2rem;'><h2>Authentication Failed</h2><p>{e}</p><a href='/'>Return to Dashboard</a></body></html>",
            status_code=400
        )

@app.post("/api/v1/auth/youtube/disconnect")
def disconnect_youtube():
    """Disconnects YouTube and securely removes stored credentials."""
    manager = YouTubeOAuthManager(db_path=DB_PATH)
    manager.disconnect()
    return {"status": "DISCONNECTED", "message": "YouTube credentials removed."}

@app.post("/api/v1/publishing/youtube/upload")
def upload_to_youtube(req: YouTubeUploadRequest):
    """
    Guarded YouTube Private Upload Endpoint.
    Enforces render checksum, active non-superseded approval, and strict privacyStatus='private'.
    """
    uploader = YouTubeUploader(db_path=DB_PATH)
    try:
        res = uploader.upload_private_video(
            project_id=req.project_id,
            render_id=req.render_id,
            title=req.title,
            description=req.description,
            tags=req.tags,
            category_id=req.category_id,
            privacy_status=req.privacy_status
        )
        return res
    except YouTubeUploadError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected upload failure: {e}")
        raise HTTPException(status_code=500, detail=f"Internal upload error: {e}")

@app.get("/api/v1/publishing/attempts/{project_id}")
def get_project_publish_attempts(project_id: str):
    """Retrieves all publish attempts for a project."""
    return get_publish_attempts_for_project(project_id, db_path=DB_PATH)

# ==============================================================================
# Google Flow Handoff & Ingestion Endpoints (Track 1)
# ==============================================================================
from backend.app.media.flow_handoff import (
    generate_flow_manifest,
    export_flow_manifest
)
from backend.app.media.flow_ingestion import (
    validate_flow_video,
    list_inbox_files,
    import_and_bind_flow_video,
    FlowValidationError,
    INBOX_DIR
)


class BindInboxFileRequest(BaseModel):
    filename: str
    confirmed_by_user: bool = True


@app.get("/projects/{project_id}/flow-prompts")
def get_project_flow_prompts(project_id: str):
    """
    Generates structured, copy-friendly prompt packages per scene for Google Flow / Veo.
    Exports a durable machine-readable JSON manifest and individual scene prompt text files.
    """
    project = get_project(project_id, db_path=DB_PATH)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")

    export_result = export_flow_manifest(project, base_media_dir=MEDIA_DIR)
    return export_result


@app.get("/inbox/files")
def get_inbox_files():
    """Lists video files available in data/inbox/ for explicit user binding."""
    return {"inbox_dir": str(INBOX_DIR), "files": list_inbox_files(INBOX_DIR)}


@app.post("/projects/{project_id}/scenes/{scene_id}/bind-inbox-file")
def bind_inbox_file_to_scene(project_id: str, scene_id: str, req: BindInboxFileRequest):
    """
    Binds an MP4 video from data/inbox/ to a project scene.
    Requires explicit user confirmation (never binds by filename heuristic alone).
    Runs decodability, duration, frame activity, and corruption checks.
    Computes SHA-256, copies to immutable storage, logs provenance, and invalidates old approvals.
    """
    clean_name = os.path.basename(req.filename)
    source_path = INBOX_DIR / clean_name
    if not source_path.exists():
        raise HTTPException(status_code=404, detail=f"File '{clean_name}' not found in data/inbox/.")

    try:
        res = import_and_bind_flow_video(
            project_id=project_id,
            scene_id=scene_id,
            source_file_path=source_path,
            confirmed_by_user=req.confirmed_by_user,
            db_path=DB_PATH,
            media_dir=MEDIA_DIR
        )
        return res
    except FlowValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed binding inbox file to scene: {e}")
        raise HTTPException(status_code=500, detail=f"Internal binding error: {e}")


@app.post("/projects/{project_id}/scenes/{scene_id}/import-flow-video")
async def upload_and_bind_flow_video(
    project_id: str,
    scene_id: str,
    request: Request,
    filename: str = Query("flow_video.mp4", description="Original filename (e.g. scene_01_flow.mp4)")
):
    """
    Uploads a Flow-generated MP4 video directly via binary body and binds it to a project scene.
    Validates technical integrity, computes SHA-256, generates preview, and invalidates old approvals.
    """
    if not filename.lower().endswith((".mp4", ".mov", ".webm", ".mkv")):
        raise HTTPException(status_code=400, detail="Only video formats (.mp4, .mov, .webm, .mkv) are allowed.")

    content = await request.body()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded video body cannot be empty.")

    # Save to a temporary staging file in inbox
    temp_name = f"upload_staging_{uuid.uuid4().hex[:8]}_{os.path.basename(filename)}"
    staging_path = INBOX_DIR / temp_name

    try:
        with open(staging_path, "wb") as f:
            f.write(content)

        res = import_and_bind_flow_video(
            project_id=project_id,
            scene_id=scene_id,
            source_file_path=staging_path,
            confirmed_by_user=True,
            db_path=DB_PATH,
            media_dir=MEDIA_DIR
        )
        return res
    except FlowValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed uploading and binding Flow video: {e}")
        raise HTTPException(status_code=500, detail=f"Internal import error: {e}")
    finally:
        if staging_path.exists():
            try:
                staging_path.unlink()
            except Exception:
                pass

# Static Frontend Mount (if built)
if FRONTEND_OUT_DIR.exists() and (FRONTEND_OUT_DIR / "index.html").exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_OUT_DIR), html=True), name="static_frontend")
