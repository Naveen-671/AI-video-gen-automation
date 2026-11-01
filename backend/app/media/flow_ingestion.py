"""Google Flow Video Ingestion: Validates, audits, and binds user-generated Flow MP4s into project scenes."""

import os
import re
import json
import uuid
import hashlib
import logging
import shutil
import subprocess
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from backend.app.config import MEDIA_DIR, DB_PATH
from backend.app.db.repository import (
    get_connection,
    get_project,
    record_audit,
    save_asset_provenance
)

logger = logging.getLogger("flow_ingestion")

INBOX_DIR = MEDIA_DIR.parent / "inbox"
INBOX_DIR.mkdir(parents=True, exist_ok=True)


class ValidationStatus(str, Enum):
    VALIDATED = "VALIDATED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    REJECTED = "REJECTED"


class FlowVideoValidationResult(BaseModel):
    """Detailed technical and visual validation report for an imported Flow video."""
    status: ValidationStatus
    sha256_checksum: str
    file_size_bytes: int
    source_width: int
    source_height: int
    source_aspect_ratio: str
    source_duration_seconds: float
    source_fps: float
    source_video_codec: str
    audio_streams_count: int
    has_audio: bool
    is_blank: bool = False
    is_frozen: bool = False
    is_test_pattern: bool = False
    is_corrupt: bool = False
    post_processing_note: str
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    preview_image_path: Optional[str] = None


class FlowValidationError(Exception):
    """Raised when an imported Flow video fails critical technical validation."""
    pass


def probe_video_metadata(video_path: Path) -> Dict[str, Any]:
    """Uses ffprobe to extract stream, codec, resolution, duration, and container info."""
    if not video_path.exists():
        raise FlowValidationError(f"File not found: {video_path}")

    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration,size,bit_rate:stream=index,codec_type,codec_name,width,height,r_frame_rate,duration,nb_frames",
        "-of", "json",
        str(video_path)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise FlowValidationError(f"ffprobe failed to read file: {res.stderr.strip()}")

    try:
        return json.loads(res.stdout)
    except json.JSONDecodeError as exc:
        raise FlowValidationError(f"Failed to parse ffprobe JSON output: {exc}") from exc


def verify_decode_integrity(video_path: Path) -> Tuple[bool, Optional[str]]:
    """Runs a full decode pass through FFmpeg to detect corrupt frames or bitstream errors."""
    cmd = [
        "ffmpeg", "-v", "error",
        "-i", str(video_path),
        "-f", "null", "-"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        return False, res.stderr.strip()
    return True, None


def sample_frames_and_analyze(video_path: Path, duration: float) -> Dict[str, Any]:
    """
    Samples 5 frames across the timeline (10%, 30%, 50%, 70%, 90%) using FFmpeg.
    Analyzes pixel luminosity, inter-frame differences (frozen frame check), and solid color patterns.
    """
    if duration <= 0.1:
        return {"is_blank": True, "is_frozen": True, "is_test_pattern": True, "error": "Zero duration"}

    sample_ratios = [0.10, 0.30, 0.50, 0.70, 0.90]
    sample_timestamps = [round(duration * r, 3) for r in sample_ratios]

    frame_means = []
    frame_stds = []
    frame_diffs = []
    prev_pixels = None

    for ts in sample_timestamps:
        # Extract a tiny 64x64 grayscale raw frame at timestamp ts
        cmd = [
            "ffmpeg", "-ss", str(ts),
            "-i", str(video_path),
            "-vframes", "1",
            "-vf", "scale=64:64,format=gray",
            "-f", "rawvideo",
            "-pix_fmt", "gray",
            "-"
        ]
        res = subprocess.run(cmd, capture_output=True)
        if res.returncode != 0 or not res.stdout:
            continue

        raw = res.stdout
        if len(raw) < 4096:
            continue

        # Compute simple mean and standard deviation
        pixel_vals = list(raw)
        n = len(pixel_vals)
        mean_val = sum(pixel_vals) / n
        variance = sum((p - mean_val) ** 2 for p in pixel_vals) / n
        std_val = variance ** 0.5

        frame_means.append(mean_val)
        frame_stds.append(std_val)

        if prev_pixels is not None:
            # Mean absolute pixel difference between consecutive samples
            diff = sum(abs(a - b) for a, b in zip(pixel_vals, prev_pixels)) / n
            frame_diffs.append(diff)
        prev_pixels = pixel_vals

    if not frame_means:
        return {"is_blank": True, "is_frozen": True, "is_test_pattern": True, "error": "Could not sample frames"}

    avg_mean = sum(frame_means) / len(frame_means)
    avg_std = sum(frame_stds) / len(frame_stds)

    # Blank media: average pixel value is pure black (< 2.0) or pure white (> 253.0) with very low std
    is_blank = (avg_mean < 2.5 and avg_std < 2.0) or (avg_mean > 252.5 and avg_std < 2.0)

    # Test pattern / solid color: all sampled frames have near zero spatial variation (< 1.5)
    is_test_pattern = avg_std < 1.5

    # Frozen frames: inter-frame difference is virtually zero (< 0.2) across all sample pairs
    is_frozen = bool(frame_diffs and all(d < 0.2 for d in frame_diffs))

    return {
        "is_blank": is_blank,
        "is_frozen": is_frozen,
        "is_test_pattern": is_test_pattern,
        "avg_mean": round(avg_mean, 2),
        "avg_std": round(avg_std, 2),
        "max_diff": round(max(frame_diffs), 2) if frame_diffs else 0.0
    }


def generate_thumbnail_preview(video_path: Path, output_image_path: Path, timestamp: float = 1.0) -> Optional[Path]:
    """Generates a high-quality JPEG thumbnail preview for scene review."""
    output_image_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(timestamp),
        "-i", str(video_path),
        "-vframes", "1",
        "-vf", "scale=360:640:force_original_aspect_ratio=increase,crop=360:640",
        "-q:v", "3",
        str(output_image_path)
    ]
    res = subprocess.run(cmd, capture_output=True)
    if res.returncode == 0 and output_image_path.exists() and output_image_path.stat().st_size > 0:
        return output_image_path
    return None


def validate_flow_video(
    video_path: Path,
    target_scene_duration: Optional[float] = None
) -> FlowVideoValidationResult:
    """
    Exhaustively validates decodability, duration, frame activity, resolution, and corruption.
    Enforces honest metadata recording: distinguishes native Flow source properties from post-processing.
    """
    if not video_path.exists():
        raise FlowValidationError(f"Target video does not exist: {video_path}")

    # 1. Compute SHA-256 Checksum and file size
    hasher = hashlib.sha256()
    file_size = video_path.stat().st_size
    with video_path.open("rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    sha256 = hasher.hexdigest()

    warnings: List[str] = []
    errors: List[str] = []

    # 2. File size boundary check (> 10 KB, < 500 MB)
    if file_size < 10 * 1024:
        errors.append(f"File size ({file_size} bytes) is suspiciously small for a valid video.")
    if file_size > 500 * 1024 * 1024:
        warnings.append(f"File size ({file_size // (1024*1024)} MB) is unusually large.")

    # 3. ffprobe metadata extraction
    probe_data = probe_video_metadata(video_path)
    streams = probe_data.get("streams", [])
    format_info = probe_data.get("format", {})

    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]

    if not video_streams:
        errors.append("File contains no decodable video stream.")
        return FlowVideoValidationResult(
            status=ValidationStatus.REJECTED,
            sha256_checksum=sha256,
            file_size_bytes=file_size,
            source_width=0,
            source_height=0,
            source_aspect_ratio="unknown",
            source_duration_seconds=0.0,
            source_fps=0.0,
            source_video_codec="none",
            audio_streams_count=0,
            has_audio=False,
            is_corrupt=True,
            post_processing_note="Rejected: Missing video stream.",
            errors=errors
        )

    v_stream = video_streams[0]
    w = int(v_stream.get("width", 0))
    h = int(v_stream.get("height", 0))
    codec = str(v_stream.get("codec_name", "unknown"))

    # Parse framerate
    r_fps = v_stream.get("r_frame_rate", "30/1")
    try:
        num, den = map(int, r_fps.split("/"))
        fps = round(num / den, 2) if den != 0 else 30.0
    except Exception:
        fps = 30.0

    # Parse duration
    dur_str = v_stream.get("duration") or format_info.get("duration", "0.0")
    try:
        duration = float(dur_str)
    except ValueError:
        duration = 0.0

    # 4. Decode integrity verification
    is_valid_decode, decode_err = verify_decode_integrity(video_path)
    if not is_valid_decode:
        errors.append(f"FFmpeg decode verification failed: {decode_err}")

    # 5. Check usable duration
    if duration < 1.0:
        errors.append(f"Measured video duration ({duration:.2f}s) is too short (minimum 1.0s required).")

    if target_scene_duration and duration < (target_scene_duration - 0.5):
        warnings.append(
            f"Video duration ({duration:.2f}s) is shorter than target scene duration ({target_scene_duration:.2f}s). "
            "Clip will loop or freeze-frame to cover remaining scene duration."
        )

    # 6. Check aspect ratio and dimensions
    aspect_ratio_str = f"{w}:{h}"
    is_vertical_9_16 = False
    if w > 0 and h > 0:
        ratio = w / h
        # 9/16 = 0.5625 (tolerance 0.52 to 0.60)
        if 0.52 <= ratio <= 0.60:
            is_vertical_9_16 = True
            aspect_ratio_str = "9:16"
        else:
            aspect_ratio_str = f"{w}:{h}"
            warnings.append(
                f"Source resolution is {w}x{h} ({aspect_ratio_str}), not native 9:16 vertical Shorts format. "
                "Post-processing will crop/pad to 1080x1920."
            )

    # Note distinguishing native source from post-processing
    if w == 1080 and h == 1920 and abs(fps - 30.0) < 0.1:
        post_proc_note = "Native 1080x1920 @ 30fps vertical source video."
    else:
        post_proc_note = (
            f"Measured source: {w}x{h} @ {fps}fps ({codec}). "
            "Post-processing pipeline will reframe, scale, and normalize to 1080x1920 @ 30fps."
        )

    # 7. Sample frames for blank, frozen, and test pattern detection
    frame_analysis = sample_frames_and_analyze(video_path, duration)
    is_blank = frame_analysis.get("is_blank", False)
    is_frozen = frame_analysis.get("is_frozen", False)
    is_test_pattern = frame_analysis.get("is_test_pattern", False)

    if is_blank:
        errors.append("Detected blank media (pure black or pure white frames across timeline).")
    if is_frozen:
        errors.append("Detected frozen frames (identical static frame content across timeline).")
    if is_test_pattern and not is_blank:
        warnings.append("Detected low visual variance / potential synthetic test pattern.")

    # 8. Determine final status
    if errors:
        status = ValidationStatus.REJECTED
    elif warnings or not is_vertical_9_16:
        status = ValidationStatus.REVIEW_REQUIRED
    else:
        status = ValidationStatus.VALIDATED

    return FlowVideoValidationResult(
        status=status,
        sha256_checksum=sha256,
        file_size_bytes=file_size,
        source_width=w,
        source_height=h,
        source_aspect_ratio=aspect_ratio_str,
        source_duration_seconds=round(duration, 3),
        source_fps=fps,
        source_video_codec=codec,
        audio_streams_count=len(audio_streams),
        has_audio=bool(audio_streams),
        is_blank=is_blank,
        is_frozen=is_frozen,
        is_test_pattern=is_test_pattern,
        is_corrupt=not is_valid_decode,
        post_processing_note=post_proc_note,
        warnings=warnings,
        errors=errors
    )


def list_inbox_files(inbox_dir: Path = INBOX_DIR) -> List[Dict[str, Any]]:
    """Lists eligible video files found in data/inbox/ for explicit user binding."""
    if not inbox_dir.exists():
        return []

    eligible_exts = {".mp4", ".webm", ".mov", ".mkv", ".m4v"}
    files = []
    for f in inbox_dir.iterdir():
        if f.is_file() and f.suffix.lower() in eligible_exts:
            stat = f.stat()
            files.append({
                "filename": f.name,
                "path": str(f.resolve()),
                "size_bytes": stat.st_size,
                "modified_at": stat.st_mtime
            })
    files.sort(key=lambda x: x["modified_at"], reverse=True)
    return files


def import_and_bind_flow_video(
    project_id: str,
    scene_id: str,
    source_file_path: Path,
    confirmed_by_user: bool,
    db_path: Path = DB_PATH,
    media_dir: Path = MEDIA_DIR
) -> Dict[str, Any]:
    """
    Exhaustively validates, hashes, moves to immutable storage, and binds a Flow video to a project scene.
    Enforces that user must explicitly confirm binding (matching by loose filename alone is rejected).
    Invalidates any previous approvals for the project (ADR-02 / ADR-04).
    """
    if not confirmed_by_user:
        raise FlowValidationError(
            "User confirmation is required to bind an imported video to a scene. "
            "Automated heuristic binding by filename alone is prohibited."
        )

    project = get_project(project_id, db_path=db_path)
    if not project:
        raise FlowValidationError(f"Project not found: {project_id}")

    target_scene = None
    target_scene_idx = 0
    for s in project.get("scenes", []):
        if str(s.get("id")) == str(scene_id):
            target_scene = s
            target_scene_idx = s.get("scene_index", 0)
            break

    if not target_scene:
        raise FlowValidationError(f"Scene with ID '{scene_id}' not found in project '{project_id}'.")

    target_dur = float(target_scene.get("duration_seconds", 4.0))

    # 1. Run technical and visual validation
    val_result = validate_flow_video(source_file_path, target_scene_duration=target_dur)

    if val_result.status == ValidationStatus.REJECTED:
        raise FlowValidationError(
            f"Import rejected due to validation failures: {'; '.join(val_result.errors)}"
        )

    # 2. Immutable storage destination
    sha = val_result.sha256_checksum
    clean_stem = re.sub(r"[^\w\-]", "_", source_file_path.stem)[:32]
    immutable_filename = f"flow_{sha[:16]}_{clean_stem}.mp4"
    dest_dir = media_dir / "projects" / project_id / "flow_imports"
    dest_dir.mkdir(parents=True, exist_ok=True)
    immutable_path = dest_dir / immutable_filename

    # Copy to immutable path
    shutil.copy2(source_file_path, immutable_path)

    # 3. Generate review preview thumbnail
    preview_dir = media_dir / "projects" / project_id / "previews"
    preview_path = preview_dir / f"preview_scene_{target_scene_idx + 1}_{sha[:12]}.jpg"
    ts = max(0.5, val_result.source_duration_seconds / 2.0)
    preview_file = generate_thumbnail_preview(immutable_path, preview_path, timestamp=ts)
    val_result.preview_image_path = str(preview_file) if preview_file else None

    # 4. Save asset provenance
    provenance_id = str(uuid.uuid4())
    rights_status = "VERIFIED_FREE" if val_result.status == ValidationStatus.VALIDATED else "REVIEW_REQUIRED"
    save_asset_provenance(
        provenance_id=provenance_id,
        project_id=project_id,
        scene_index=target_scene_idx,
        asset_type="FLOW_GENERATED",
        source_url="https://labs.google/flow",
        author="User via Google Flow / Veo (Jio AI Pro)",
        license="User Generated / Google Flow Terms",
        attribution_text="Generated with Google Flow via user-directed prompt package.",
        local_path=str(immutable_path),
        sha256_checksum=sha,
        media_type="video",
        original_width=val_result.source_width,
        original_height=val_result.source_height,
        original_duration=val_result.source_duration_seconds,
        file_size_bytes=val_result.file_size_bytes,
        rights_status=rights_status,
        selection_reason=val_result.post_processing_note,
        db_path=db_path
    )

    # 5. Update scene and invalidate existing render approvals
    conn = get_connection(db_path)
    try:
        with conn:
            # Supersede any active approvals for this project's render
            if project.get("current_render_id"):
                conn.execute(
                    """
                    UPDATE approvals
                    SET superseded_at = CURRENT_TIMESTAMP
                    WHERE render_id = ? AND superseded_at IS NULL
                    """,
                    (project["current_render_id"],)
                )

            # Update scene visual asset
            conn.execute(
                """
                UPDATE project_scenes
                SET visual_asset_path = ?, motion_preset = 'static', visual_source_type = 'FLOW_GENERATED', asset_provenance_id = ?
                WHERE id = ?
                """,
                (str(immutable_path), provenance_id, scene_id)
            )

            # Revert project status to STORYBOARD so it requires re-render and re-approval
            conn.execute(
                """
                UPDATE projects
                SET status = 'STORYBOARD', current_render_id = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (project_id,)
            )
    finally:
        conn.close()

    # 6. Audit logging
    record_audit(
        "FLOW_VIDEO_IMPORTED",
        project_id,
        {
            "scene_id": scene_id,
            "scene_index": target_scene_idx,
            "sha256": sha,
            "status": val_result.status.value,
            "warnings": val_result.warnings
        },
        db_path=db_path
    )

    logger.info(
        f"Successfully bound Flow video {immutable_filename} to Scene {target_scene_idx + 1} "
        f"in project {project_id} (Status: {val_result.status.value})."
    )

    return {
        "success": True,
        "project_id": project_id,
        "scene_id": scene_id,
        "scene_index": target_scene_idx,
        "bound_path": str(immutable_path),
        "preview_path": str(preview_file) if preview_file else None,
        "provenance_id": provenance_id,
        "validation": val_result.model_dump()
    }
