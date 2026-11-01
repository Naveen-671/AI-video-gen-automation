"""Google Flow Handoff: Generates structured, copy-friendly prompt packages per scene."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from backend.app.config import MEDIA_DIR

logger = logging.getLogger("flow_handoff")


class FlowPromptPackage(BaseModel):
    """Structured generation package for a single scene in Google Flow / Veo."""
    scene_id: str
    scene_index: int
    scene_title: str
    narrative_intent: str
    exact_prompt: str
    aspect_ratio: str = Field(default="9:16", description="Target vertical video aspect ratio")
    requested_duration: str = Field(default="4s", description="Target generation duration (4s or 8s)")
    motion_camera_direction: str
    continuity_constraints: str
    forbidden_artifacts: str
    supporting_claims: List[str] = Field(default_factory=list)
    technical_notes: str = Field(
        default=(
            "Note: Google Flow web interface controls (aspect ratio, duration, camera motion) "
            "must be selected manually in the Flow UI. They are not programmatically controllable "
            "under consumer Google AI Pro entitlements."
        )
    )


class FlowManifest(BaseModel):
    """Durable manifest of Flow prompt packages for an entire project."""
    project_id: str
    project_topic: str
    narrative_archetype: str
    created_at: str
    total_scenes: int
    scenes: List[FlowPromptPackage]
    instructions_for_user: str


def build_flow_prompt_for_scene(
    scene: Dict[str, Any],
    project_topic: str,
    archetype: str,
    supporting_claims: Optional[List[str]] = None
) -> FlowPromptPackage:
    """
    Constructs an optimized, cinematic 9:16 prompt package for Google Flow.
    Adheres to Veo best practices: high-craft visual descriptors, physical lighting,
    camera motion verbs, and negative constraints.
    """
    scene_id = str(scene.get("id", f"scene_{scene.get('scene_index', 0)}"))
    scene_idx = int(scene.get("scene_index", 0))
    title = scene.get("scene_title", f"Scene {scene_idx + 1}")
    narration = scene.get("narration_text", "")
    caption = scene.get("caption_text", title)
    dur_sec = float(scene.get("duration_seconds", 4.0))

    # Duration mapping: Flow web UI supports 4s or 8s intervals
    flow_dur = "8s" if dur_sec >= 6.0 else "4s"

    # Narrative intent based on archetype and scene position
    if scene_idx == 0:
        intent = f"Hook ({archetype}): Immediately arrest attention and challenge intuition regarding '{project_topic}'"
        camera_motion = "Dynamic slow push-in, centered subject, dramatic depth of field"
    elif scene_idx == 1:
        intent = "Development: Deepen scientific context, reveal underlying mechanisms"
        camera_motion = "Smooth lateral tracking shot or gentle orbital pan, steady 24fps cinematic motion"
    elif scene_idx == 2:
        intent = "Climax / Evidence: Visually demonstrate the surprising core truth"
        camera_motion = "Expansive slow pull-out or high-angle tilt, revealing macro scale and environment"
    else:
        intent = "Conclusion / Takeaway: Resonant visual payoff and memorable final impression"
        camera_motion = "Subtle lingering push-in with gentle vertical drift, clean framing"

    # Construct exact prompt tailored for 9:16 vertical generative video
    # Rich, descriptive, free of text-overlay requests
    base_subject = caption or narration or project_topic
    exact_prompt = (
        f"Vertical 9:16 cinematic video. {base_subject}. "
        f"Photorealistic 8k, volumetric atmospheric lighting, cinematic color grading, "
        f"highly detailed physical textures, natural physics. "
        f"Camera direction: {camera_motion}. Sharp focal plane, no motion blur."
    )

    forbidden = (
        "no text, no subtitles, no captions, no watermarks, no logos, "
        "no 16:9 horizontal letterboxing or pillarboxing, no low-resolution blur, "
        "no cartoon or illustrative 2D rendering, no unnatural morphing or glitching."
    )

    continuity = (
        f"Maintain consistent visual tone matching '{project_topic}' in the '{archetype}' style. "
        "Preserve unified lighting temperature and palette across adjacent scene cuts."
    )

    return FlowPromptPackage(
        scene_id=scene_id,
        scene_index=scene_idx,
        scene_title=title,
        narrative_intent=intent,
        exact_prompt=exact_prompt,
        aspect_ratio="9:16",
        requested_duration=flow_dur,
        motion_camera_direction=camera_motion,
        continuity_constraints=continuity,
        forbidden_artifacts=forbidden,
        supporting_claims=supporting_claims or []
    )


def generate_flow_manifest(project: Dict[str, Any]) -> FlowManifest:
    """Generates the full Flow prompt manifest for all scenes in a project."""
    project_id = project.get("id", "unknown_project")
    topic = project.get("topic", "General Topic")
    archetype = project.get("narrative_archetype", "Counter-Intuitive")
    raw_scenes = project.get("scenes", [])

    prompt_packages: List[FlowPromptPackage] = []
    for s in raw_scenes:
        claims = s.get("supporting_claim_ids", [])
        if isinstance(claims, str):
            try:
                claims = json.loads(claims)
            except Exception:
                claims = []
        pkg = build_flow_prompt_for_scene(s, topic, archetype, claims)
        prompt_packages.append(pkg)

    instructions = (
        "Instructions for Google Flow (labs.google/flow):\n"
        "1. Open Google Flow in your web browser (logged in with your Jio Google AI Pro account).\n"
        "2. For each scene, copy the 'exact_prompt' text.\n"
        "3. In Google Flow UI, set Aspect Ratio to '9:16' (Portrait / Vertical).\n"
        "4. Set generation duration to the 'requested_duration' (4s or 8s).\n"
        "5. Generate video and download the resulting .mp4 file.\n"
        "6. Move or save the downloaded file to 'data/inbox/' or use the 'Import Flow Video' button in the dashboard.\n"
        "7. Note: UI-only Flow controls must be selected manually in the web browser."
    )

    return FlowManifest(
        project_id=project_id,
        project_topic=topic,
        narrative_archetype=archetype,
        created_at=datetime.now(timezone.utc).isoformat(),
        total_scenes=len(prompt_packages),
        scenes=prompt_packages,
        instructions_for_user=instructions
    )


def export_flow_manifest(project: Dict[str, Any], base_media_dir: Path = MEDIA_DIR) -> Dict[str, Any]:
    """
    Exports durable machine-readable JSON manifest and individual scene prompt files.
    Returns dictionary with file paths and manifest data.
    """
    manifest = generate_flow_manifest(project)
    project_id = manifest.project_id

    out_dir = base_media_dir / "projects" / project_id / "flow_prompts"
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = out_dir / "flow_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest.model_dump(), f, indent=2)

    # Also export individual copy-friendly text files per scene
    scene_files = []
    for pkg in manifest.scenes:
        s_file = out_dir / f"scene_{pkg.scene_index + 1}_prompt.txt"
        with open(s_file, "w", encoding="utf-8") as f:
            f.write(f"=== SCENE {pkg.scene_index + 1}: {pkg.scene_title} ===\n")
            f.write(f"Aspect Ratio: {pkg.aspect_ratio}\n")
            f.write(f"Duration: {pkg.requested_duration}\n")
            f.write(f"Camera Motion: {pkg.motion_camera_direction}\n\n")
            f.write(f"--- PROMPT (COPY BELOW) ---\n")
            f.write(f"{pkg.exact_prompt}\n\n")
            f.write(f"--- FORBIDDEN (NEGATIVE) ---\n")
            f.write(f"{pkg.forbidden_artifacts}\n")
        scene_files.append(str(s_file))

    # Mark scenes as FLOW_REQUIRED in database if not already FLOW_GENERATED
    try:
        from backend.app.db.repository import get_connection, DB_PATH
        conn = get_connection(DB_PATH)
        with conn:
            conn.execute(
                """
                UPDATE project_scenes
                SET visual_source_type = 'FLOW_REQUIRED'
                WHERE project_id = ? AND visual_source_type != 'FLOW_GENERATED'
                """,
                (project_id,)
            )
        conn.close()
    except Exception as e:
        logger.warning(f"Could not update visual_source_type in database: {e}")

    logger.info(f"Exported Flow prompt manifest to {manifest_path} with {len(manifest.scenes)} scenes.")
    return {
        "manifest_path": str(manifest_path),
        "scene_prompt_files": scene_files,
        "manifest": manifest.model_dump()
    }
