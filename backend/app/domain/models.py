"""Domain and API Pydantic schemas for projects, renders, approvals, and jobs."""

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

# Scenes & Projects

class SceneModel(BaseModel):
    id: Optional[str] = None
    scene_index: int = 0
    scene_title: str = "Scene"
    narration_text: str = ""
    caption_text: str = ""
    duration_seconds: float = 5.0
    visual_asset_path: Optional[str] = None
    motion_preset: str = "zoom_in"  # "zoom_in", "zoom_out", "pan_left", "pan_right", "tilt_up", "tilt_down", "static"
    visual_source_type: str = "FLOW_REQUIRED"  # "FLOW_REQUIRED", "USER_UPLOAD", "CURATED_STOCK", "EXPLICIT_FALLBACK"
    asset_provenance_id: Optional[str] = None
    supporting_claim_ids: List[str] = Field(default_factory=list)

class ProjectCreate(BaseModel):
    topic: str
    title: Optional[str] = None
    target_audience: str = "General"
    language: str = "en"
    target_duration: float = 15.0
    content_format: str = "explainer"
    narrative_archetype: str = "CURIOSITY_GAP"
    narration_mode: str = "silent"  # "silent", "manual_audio", or "local_tts"
    narration_voice: Optional[str] = "af_bella"
    supplied_script: Optional[str] = None
    scenes: Optional[List[SceneModel]] = None

class ProjectUpdateStoryboard(BaseModel):
    scenes: List[SceneModel]

class ProjectUpdateNarration(BaseModel):
    narration_mode: str = Field(..., description="'silent', 'manual_audio', or 'local_tts'")
    narration_voice: Optional[str] = "af_bella"

class ProjectResponse(BaseModel):
    id: str
    title: str
    topic: str
    target_audience: str
    language: str
    target_duration: float
    content_format: str
    narrative_archetype: str = "CURIOSITY_GAP"
    narration_mode: str
    narration_voice: Optional[str] = "af_bella"
    status: str
    current_render_id: Optional[str] = None
    render_checksum: Optional[str] = None
    approval_status: Optional[str] = None
    created_at: str

class ProjectDetailResponse(ProjectResponse):
    narration_audio_path: Optional[str] = None
    scenes: List[SceneModel]
    current_render: Optional[Dict[str, Any]] = None
    active_approval: Optional[Dict[str, Any]] = None
    fact_claims: Optional[List[Dict[str, Any]]] = None
    fact_sources: Optional[List[Dict[str, Any]]] = None

# Approvals & Actions

class ApprovalAction(BaseModel):
    status: str = Field(..., description="'APPROVED' or 'REJECTED'")
    notes: Optional[str] = None
    reviewer: str = "human_operator"

# Jobs & Renders

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
    project_id: Optional[str] = None
    localized_variant_id: Optional[str] = None
    render_checksum: str
    recipe_json: str
    file_path: Optional[str] = None

class ApprovalCreate(BaseModel):
    render_id: str
    render_checksum: str
    reviewer: str = "human_operator"
    status: str = "APPROVED"  # "APPROVED" or "REJECTED"
    notes: Optional[str] = None

class PublishAttemptCreate(BaseModel):
    id: str
    approval_id: str
    render_id: str
    platform: str = "youtube"
    target_channel_id: str
    idempotency_key: str

class LLMProposal(BaseModel):
    proposal_type: str = Field(..., description="e.g. SCRIPT_OUTLINE, HOOK_VARIANTS")
    topic: str
    suggested_hook: str
    narrative_points: List[str]
    suggested_visual_prompts: List[str]
    confidence_score: float = 0.0

# FactLedger & Research Models (Stage 2)

class FactSourceModel(BaseModel):
    id: str
    project_id: Optional[str] = None
    url: str
    title: str
    published_date: Optional[str] = None
    retrieved_at: str
    raw_excerpt: Optional[str] = None
    http_status: int = 200

class FactClaimModel(BaseModel):
    id: str
    source_id: Optional[str] = None
    project_id: Optional[str] = None
    claim_text: str
    quote_excerpt: str
    evidence_status: str = "UNVERIFIED"  # "VERIFIED", "UNVERIFIED", "INSUFFICIENT_EVIDENCE"
    uncertainty_rationale: Optional[str] = None
    created_at: str
    source_url: Optional[str] = None
    source_title: Optional[str] = None

class ValidationWarningModel(BaseModel):
    rule: str
    severity: str  # "ERROR", "WARNING"
    message: str
    entity_id: Optional[str] = None

class ValidationReportModel(BaseModel):
    passed: bool
    errors: List[ValidationWarningModel] = Field(default_factory=list)
    warnings: List[ValidationWarningModel] = Field(default_factory=list)
    lexical_density_wps: float = 0.0
    total_spoken_words: int = 0
    total_duration_sec: float = 0.0
    claim_coverage_ratio: float = 0.0

class ScriptProposalModel(BaseModel):
    id: str
    project_id: Optional[str] = None
    topic: str
    target_audience: str
    narrative_archetype: str
    hook_text: str
    scenes: List[SceneModel]
    validation: ValidationReportModel
    created_at: str

class ResearchRequest(BaseModel):
    topic: str
    target_audience: str = "General"
    narrative_archetype: str = "CURIOSITY_GAP"
    project_id: Optional[str] = None
    max_sources: int = 3

class ResearchResponse(BaseModel):
    project_id: Optional[str] = None
    topic: str
    target_audience: str
    narrative_archetype: str
    sources: List[FactSourceModel]
    claims: List[FactClaimModel]
    proposal: ScriptProposalModel
    validation: ValidationReportModel

class AssetProvenanceModel(BaseModel):
    id: str
    project_id: str
    scene_index: int
    asset_type: str  # 'USER_UPLOAD', 'WIKIMEDIA', 'NASA', 'PROCEDURAL', 'FALLBACK'
    source_url: Optional[str] = None
    author: Optional[str] = None
    license: Optional[str] = None
    attribution_text: Optional[str] = None
    local_path: str
    sha256_checksum: str
    associated_claim_id: Optional[str] = None
    source_asset_id: Optional[str] = None
    source_page_url: Optional[str] = None
    license_url: Optional[str] = None
    media_type: str = "image"  # 'image', 'video'
    original_width: Optional[int] = None
    original_height: Optional[int] = None
    original_duration: Optional[float] = None
    file_size_bytes: Optional[int] = None
    rights_status: str = "VERIFIED_FREE"
    crop_transform: Optional[str] = None
    selection_reason: Optional[str] = None
    created_at: Optional[str] = None

class EditorialWarningModel(BaseModel):
    category: str  # 'HOOK', 'PACING', 'RELEVANCE', 'AUDIO', 'RETENTION'
    severity: str  # 'WARNING', 'SUGGESTION'
    message: str
    scene_index: Optional[int] = None

class EditorialReviewModel(BaseModel):
    id: str
    project_id: str
    render_id: Optional[str] = None
    overall_status: str  # 'PASSED', 'WARNING', 'FAILED'
    score: int = 100
    hook_evaluation: Dict[str, Any]
    pacing_evaluation: Dict[str, Any]
    relevance_evaluation: Dict[str, Any]
    audio_evaluation: Dict[str, Any]
    warnings: List[EditorialWarningModel] = Field(default_factory=list)
    created_at: Optional[str] = None
