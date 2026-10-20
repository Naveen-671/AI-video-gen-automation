"""Domain and API Pydantic schemas."""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime

class SystemResources(BaseModel):
    available_ram_gib: float
    free_disk_gb: float
    min_ram_threshold_gib: float
    min_disk_threshold_gb: float
    ram_ok: bool
    disk_ok: bool
    can_process_jobs: bool

class HealthResponse(BaseModel):
    status: str
    db_connected: bool
    global_pause: bool
    resources: SystemResources
    enabled_cost_classes: List[str]
    active_jobs_count: int

class PauseRequest(BaseModel):
    paused: bool

class PauseResponse(BaseModel):
    global_pause: bool
    message: str

class JobCreate(BaseModel):
    stage: str
    payload: Dict[str, Any]
    idempotency_key: str
    max_attempts: int = 3

class JobResponse(BaseModel):
    id: str
    stage: str
    status: str
    attempts: int
    max_attempts: int
    idempotency_key: str
    lease_expires_at: Optional[str] = None
    created_at: str
    updated_at: str

class RenderCreate(BaseModel):
    id: str
    localized_variant_id: Optional[str] = None
    render_checksum: str
    recipe_json: str
    file_path: Optional[str] = None

class ApprovalCreate(BaseModel):
    render_id: str
    render_checksum: str
    reviewer: str = "human_operator"
    status: str = "APPROVED" # "APPROVED" or "REJECTED"
    notes: Optional[str] = None

class PublishAttemptCreate(BaseModel):
    id: str
    approval_id: str
    render_id: str
    platform: str = "youtube"
    target_channel_id: str
    idempotency_key: str

class LLMProposal(BaseModel):
    """Strict schema for LLM proposals (never directly executable)."""
    proposal_type: str = Field(..., description="e.g. SCRIPT_OUTLINE, HOOK_VARIANTS")
    topic: str
    suggested_hook: str
    narrative_points: List[str]
    suggested_visual_prompts: List[str]
    confidence_score: float = 0.0
