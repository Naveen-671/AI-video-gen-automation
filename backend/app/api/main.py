"""FastAPI application providing health, pause, jobs, and serving static frontend."""

from fastapi import FastAPI, HTTPException, status
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from pathlib import Path
import os

from backend.app.config import (
    DB_PATH,
    FRONTEND_OUT_DIR,
    ALLOWED_COST_CLASSES,
    check_system_resources
)
from backend.app.db.connection import init_db, get_connection
from backend.app.db.repository import (
    is_global_paused,
    set_global_pause,
    create_job,
    list_jobs
)
from backend.app.domain.models import (
    HealthResponse,
    PauseRequest,
    PauseResponse,
    JobCreate,
    JobResponse,
    SystemResources
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure database tables and triggers exist
    init_db(DB_PATH)
    yield

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

@app.get("/jobs", response_model=list[JobResponse])
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

# Static Frontend Mount (if built)
if FRONTEND_OUT_DIR.exists() and (FRONTEND_OUT_DIR / "index.html").exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_OUT_DIR), html=True), name="static_frontend")
