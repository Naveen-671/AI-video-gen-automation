"""Asset management: upload validation, path containment, and default background generation."""

import os
import hashlib
import subprocess
from pathlib import Path
from typing import Tuple

from backend.app.config import MEDIA_DIR

ALLOWED_IMAGE_EXTS = {".png", ".jpg", ".jpeg"}
ALLOWED_AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aac"}
MAX_IMAGE_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB
MAX_AUDIO_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB

# Color schemes for default scene backgrounds
DEFAULT_SCENE_COLORS = [
    ("navy", "darkblue"),
    ("darkgreen", "teal"),
    ("purple", "indigo"),
    ("darkred", "maroon"),
    ("black", "gray")
]

class AssetValidationError(Exception):
    """Raised when an uploaded asset violates size, type, or path boundaries."""
    pass

def sanitize_and_validate_path(target_dir: Path, filename: str) -> Path:
    """Ensures filename has no path traversal and remains strictly within target_dir."""
    clean_name = os.path.basename(filename)
    if not clean_name or clean_name in (".", ".."):
        raise AssetValidationError("Invalid filename.")
    
    target_path = (target_dir / clean_name).resolve()
    base_media_dir = MEDIA_DIR.resolve()

    if not str(target_path).startswith(str(base_media_dir)):
        raise AssetValidationError("Path containment violation: Asset outside media directory.")
    
    return target_path

def save_uploaded_asset(project_id: str, file_bytes: bytes, original_filename: str) -> Tuple[Path, str]:
    """Validates and saves an uploaded asset, returning (file_path, sha256_checksum)."""
    # Strict path traversal check on raw filename
    if ".." in original_filename or "/" in original_filename or "\\" in original_filename:
        raise AssetValidationError("Path traversal detected in filename.")

    ext = os.path.splitext(original_filename)[1].lower()
    
    if ext in ALLOWED_IMAGE_EXTS:
        if len(file_bytes) > MAX_IMAGE_SIZE_BYTES:
            raise AssetValidationError(f"Image exceeds maximum size of 20 MB (actual: {len(file_bytes)} bytes).")
    elif ext in ALLOWED_AUDIO_EXTS:
        if len(file_bytes) > MAX_AUDIO_SIZE_BYTES:
            raise AssetValidationError(f"Audio exceeds maximum size of 50 MB (actual: {len(file_bytes)} bytes).")
    else:
        raise AssetValidationError(f"Unsupported file format '{ext}'. Allowed: {ALLOWED_IMAGE_EXTS | ALLOWED_AUDIO_EXTS}")

    sha256 = hashlib.sha256(file_bytes).hexdigest()
    project_media_dir = MEDIA_DIR / "projects" / project_id
    project_media_dir.mkdir(parents=True, exist_ok=True)

    dest_filename = f"{sha256[:16]}_{os.path.basename(original_filename)}"
    dest_path = sanitize_and_validate_path(project_media_dir, dest_filename)

    with dest_path.open("wb") as f:
        f.write(file_bytes)

    return dest_path, sha256

def generate_default_scene_background(
    project_id: str,
    scene_index: int,
    title: str,
    width: int = 720,
    height: int = 1280
) -> Path:
    """
    Generates a stylish, deterministic vertical background image using FFmpeg lavfi filters.
    Zero external dependencies, zero model weights.
    """
    project_media_dir = MEDIA_DIR / "projects" / project_id / "defaults"
    project_media_dir.mkdir(parents=True, exist_ok=True)
    out_file = project_media_dir / f"scene_{scene_index}.png"

    if out_file.exists():
        return out_file

    c1, c2 = DEFAULT_SCENE_COLORS[scene_index % len(DEFAULT_SCENE_COLORS)]
    clean_title = "".join(c for c in title if c.isalnum() or c in (" ", "-", "_"))[:25]

    # Generate image using FFmpeg color filter
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=c={c1}:s={width}x{height}:d=1",
        "-frames:v", "1",
        str(out_file)
    ]
    
    res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg failed to generate default scene background: {res.stderr}")

    return out_file
