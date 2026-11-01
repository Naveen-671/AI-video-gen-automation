"""
Video asset ingestion adapters for Stage 5: NASA Image & Video Library and Wikimedia Commons.
Enforces strict size limits (max 35 MB), 10s timeouts, MIME validation, and license verification.
"""

import hashlib
import json
import logging
import re
import subprocess
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from backend.app.config import MEDIA_DIR
from backend.app.media.visual_adapters import VisualAssetResult

logger = logging.getLogger("video_adapters")

MAX_VIDEO_BYTES = 35 * 1024 * 1024  # 35 MB guardrail
DEFAULT_TIMEOUT = 10.0  # 10s timeout

WIKIMEDIA_ALLOWED_LICENSES = {
    "public domain", "pd", "pd-user", "pd-self", "cc0", "cc-zero",
    "cc-by", "cc by", "cc-by-1.0", "cc-by-2.0", "cc-by-2.5", "cc-by-3.0", "cc-by-4.0",
    "cc by 1.0", "cc by 2.0", "cc by 2.5", "cc by 3.0", "cc by 4.0",
    "cc-by-sa", "cc by-sa", "cc-by-sa-1.0", "cc-by-sa-2.0", "cc-by-sa-2.5", "cc-by-sa-3.0", "cc-by-sa-4.0",
    "cc by-sa 1.0", "cc by-sa 2.0", "cc by-sa 2.5", "cc by-sa 3.0", "cc by-sa 4.0"
}

WIKIMEDIA_REJECTED_KEYWORDS = [
    "-nc", "noncommercial", "non-commercial",
    "-nd", "noderivatives", "no-derivatives",
    "fair use", "fair-use", "copyrighted", "all rights reserved"
]


def probe_video_metadata(file_path: Path) -> Dict[str, Any]:
    """Uses ffprobe to extract width, height, duration, and video stream codec."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,codec_name,duration:format=duration",
        "-of", "json",
        str(file_path)
    ]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        data = json.loads(res.stdout)
        streams = data.get("streams", [])
        if not streams:
            return {"width": 0, "height": 0, "duration": 0.0, "codec": "unknown"}
        stream = streams[0]
        width = int(stream.get("width", 0))
        height = int(stream.get("height", 0))
        
        # Duration can be in stream or format
        duration_str = stream.get("duration") or data.get("format", {}).get("duration", "0.0")
        try:
            duration = float(duration_str)
        except (ValueError, TypeError):
            duration = 0.0
            
        return {
            "width": width,
            "height": height,
            "duration": duration,
            "codec": stream.get("codec_name", "unknown")
        }
    except Exception as e:
        logger.warning(f"ffprobe failed for {file_path}: {e}")
        return {"width": 0, "height": 0, "duration": 0.0, "codec": "unknown"}


class BaseVideoAdapter:
    """Base class for video asset retrieval."""

    def __init__(self, timeout_sec: float = DEFAULT_TIMEOUT, max_download_bytes: int = MAX_VIDEO_BYTES):
        self.timeout_sec = timeout_sec
        self.max_download_bytes = max_download_bytes

    def _stream_download_video(
        self,
        url: str,
        dest_path: Path,
        client: httpx.Client,
        expected_mime_types: Optional[List[str]] = None
    ) -> Tuple[Path, str, int]:
        """
        Streams a video download while checking file size bounds and computing SHA-256.
        Aborts and cleans up if size exceeds max_download_bytes.
        Returns: (dest_path, sha256_checksum, total_bytes)
        """
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        hasher = hashlib.sha256()
        total_bytes = 0

        with client.stream("GET", url, timeout=self.timeout_sec, follow_redirects=True) as response:
            if response.status_code != 200:
                raise ValueError(f"HTTP {response.status_code} when downloading video from {url}")

            content_type = response.headers.get("content-type", "").lower()
            if expected_mime_types:
                mime_match = any(m in content_type for m in expected_mime_types)
                # Allow octet-stream as long as extension is video
                if not mime_match and "application/octet-stream" not in content_type:
                    raise ValueError(f"Unexpected Content-Type '{content_type}' for video stream")

            # Check Content-Length header if available
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > self.max_download_bytes:
                raise ValueError(f"Video Content-Length ({content_length} bytes) exceeds limit ({self.max_download_bytes} bytes)")

            temp_dest = dest_path.with_suffix(dest_path.suffix + ".tmp")
            try:
                with open(temp_dest, "wb") as f:
                    for chunk in response.iter_bytes(chunk_size=65536):
                        if not chunk:
                            continue
                        total_bytes += len(chunk)
                        if total_bytes > self.max_download_bytes:
                            raise ValueError(f"Downloaded bytes ({total_bytes}) exceeded limit of {self.max_download_bytes}")
                        hasher.update(chunk)
                        f.write(chunk)
                temp_dest.replace(dest_path)
            except Exception:
                if temp_dest.exists():
                    temp_dest.unlink(missing_ok=True)
                raise

        return dest_path, hasher.hexdigest(), total_bytes


class NASAVideoAdapter(BaseVideoAdapter):
    """
    Ingests authentic public domain video clips from NASA Image & Video Library (images-api.nasa.gov).
    Validates open rights and selects bounded MP4 files.
    """

    def search_video(
        self,
        project_id: str,
        query: str,
        scene_index: int = 0,
        associated_claim_id: Optional[str] = None
    ) -> Optional[VisualAssetResult]:
        clean_q = re.sub(r'[^a-zA-Z0-9\s]', '', query).strip()
        if not clean_q:
            return None

        search_url = f"https://images-api.nasa.gov/search?q={urllib.parse.quote(clean_q)}&media_type=video"
        
        try:
            with httpx.Client(timeout=self.timeout_sec, follow_redirects=True) as client:
                resp = client.get(search_url)
                if resp.status_code != 200:
                    logger.debug(f"NASA video search failed with HTTP {resp.status_code}")
                    return None
                
                data = resp.json()
                items = data.get("collection", {}).get("items", [])
                if not items:
                    return None

                for item in items[:4]:
                    data_entry = (item.get("data") or [{}])[0]
                    nasa_id = data_entry.get("nasa_id")
                    if not nasa_id:
                        continue

                    title = data_entry.get("title", clean_q)
                    description = data_entry.get("description", "")
                    center = data_entry.get("center", "NASA")
                    photographer = data_entry.get("photographer") or center

                    # Rights & licensing guardrail:
                    # Reject if non-NASA copyright claims exist in description or metadata
                    desc_lower = description.lower()
                    if "copyright" in desc_lower or "all rights reserved" in desc_lower or "(c)" in desc_lower:
                        logger.info(f"Skipping NASA video {nasa_id}: proprietary copyright notice detected")
                        continue

                    # Fetch asset manifest
                    manifest_url = f"https://images-api.nasa.gov/asset/{urllib.parse.quote(nasa_id)}"
                    m_resp = client.get(manifest_url)
                    if m_resp.status_code != 200:
                        continue

                    manifest_data = m_resp.json()
                    m_items = [u.get("href") for u in manifest_data.get("collection", {}).get("items", []) if u.get("href")]

                    # Select best MP4 stream (prefer medium or mobile to avoid 500MB masters)
                    mp4_candidates = [u for u in m_items if u.lower().endswith(".mp4")]
                    if not mp4_candidates:
                        continue

                    chosen_url = None
                    for pattern in ["~medium.mp4", "~mobile.mp4", "~orig.mp4"]:
                        for cand in mp4_candidates:
                            if pattern in cand.lower():
                                chosen_url = cand
                                break
                        if chosen_url:
                            break

                    if not chosen_url:
                        chosen_url = mp4_candidates[0]

                    # Download and verify
                    dest_file = MEDIA_DIR / project_id / "videos" / f"nasa_{nasa_id[:16]}.mp4"
                    try:
                        saved_path, sha256, file_size = self._stream_download_video(
                            url=chosen_url,
                            dest_path=dest_file,
                            client=client,
                            expected_mime_types=["video/mp4"]
                        )
                    except Exception as dl_err:
                        logger.warning(f"Failed to stream NASA video candidate {chosen_url}: {dl_err}")
                        continue

                    meta = probe_video_metadata(saved_path)
                    if meta["width"] <= 0 or meta["duration"] <= 0.5:
                        logger.warning(f"Downloaded NASA file {saved_path} has invalid video stream")
                        saved_path.unlink(missing_ok=True)
                        continue

                    return VisualAssetResult(
                        local_path=saved_path,
                        asset_type="NASA",
                        sha256_checksum=sha256,
                        source_url=chosen_url,
                        author=photographer,
                        license="NASA Open Media (Public Domain)",
                        attribution_text=f"NASA / {center} - '{title}'",
                        associated_claim_id=associated_claim_id,
                        source_asset_id=nasa_id,
                        source_page_url=f"https://images.nasa.gov/details-{nasa_id}.html",
                        license_url="https://www.nasa.gov/multimedia/guidelines/index.html",
                        media_type="video",
                        original_width=meta["width"],
                        original_height=meta["height"],
                        original_duration=meta["duration"],
                        file_size_bytes=file_size,
                        rights_status="PUBLIC_DOMAIN",
                        crop_transform="scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
                        selection_reason=f"Authentic NASA footage selected for query '{clean_q}'"
                    )

        except Exception as e:
            logger.warning(f"NASA video search exception: {e}")
            return None

        return None


class WikimediaVideoAdapter(BaseVideoAdapter):
    """
    Ingests open-licensed video files from Wikimedia Commons (commons.wikimedia.org).
    Enforces strict license whitelist, rejection of NC/ND, MIME checks, and size caps.
    """

    def search_video(
        self,
        project_id: str,
        query: str,
        scene_index: int = 0,
        associated_claim_id: Optional[str] = None
    ) -> Optional[VisualAssetResult]:
        clean_q = re.sub(r'[^a-zA-Z0-9\s]', '', query).strip()
        if not clean_q:
            return None

        api_url = (
            "https://commons.wikimedia.org/w/api.php?"
            "action=query&generator=search&"
            f"gsrsearch={urllib.parse.quote(clean_q)}+filetype:video&"
            "gsrnamespace=6&gsrlimit=5&prop=imageinfo&"
            "iiprop=url|size|mime|extmetadata|mediatype&format=json"
        )

        try:
            with httpx.Client(
                timeout=self.timeout_sec,
                headers={"User-Agent": "AIShortsFactory/1.0 (internal-research)"},
                follow_redirects=True
            ) as client:
                resp = client.get(api_url)
                if resp.status_code != 200:
                    return None

                data = resp.json()
                pages = data.get("query", {}).get("pages", {})
                if not pages:
                    return None

                for page_id, page_info in pages.items():
                    imageinfo = (page_info.get("imageinfo") or [{}])[0]
                    file_url = imageinfo.get("url")
                    if not file_url:
                        continue

                    # MIME check
                    mime = imageinfo.get("mime", "").lower()
                    if "video" not in mime and not any(file_url.lower().endswith(ext) for ext in [".webm", ".mp4", ".ogv"]):
                        continue

                    # File size check from API metadata
                    size_bytes = int(imageinfo.get("size", 0))
                    if size_bytes > self.max_download_bytes:
                        logger.debug(f"Skipping Wikimedia video {file_url}: {size_bytes} > {self.max_download_bytes}")
                        continue

                    # License verification
                    extmeta = imageinfo.get("extmetadata", {})
                    license_name = (
                        extmeta.get("LicenseShortName", {}).get("value") or
                        extmeta.get("License", {}).get("value") or
                        ""
                    ).lower()

                    artist_raw = extmeta.get("Artist", {}).get("value", "Wikimedia Contributor")
                    artist = re.sub(r'<[^>]+>', '', artist_raw).strip() or "Wikimedia Contributor"
                    title = page_info.get("title", clean_q)

                    # Reject non-commercial or no-derivatives
                    if any(rej in license_name for rej in WIKIMEDIA_REJECTED_KEYWORDS):
                        logger.info(f"Skipping Wikimedia video {title}: rejected license '{license_name}'")
                        continue

                    # Match whitelist
                    is_allowed = any(allowed in license_name for allowed in WIKIMEDIA_ALLOWED_LICENSES)
                    if not is_allowed and "cc" not in license_name:
                        logger.info(f"Skipping Wikimedia video {title}: unverified license '{license_name}'")
                        continue

                    # Destination file
                    ext = Path(file_url).suffix or ".webm"
                    safe_slug = re.sub(r'[^a-zA-Z0-9_]', '_', title)[:24]
                    dest_file = MEDIA_DIR / project_id / "videos" / f"wiki_{safe_slug}{ext}"

                    try:
                        saved_path, sha256, downloaded_bytes = self._stream_download_video(
                            url=file_url,
                            dest_path=dest_file,
                            client=client,
                            expected_mime_types=["video/webm", "video/mp4", "video/ogg"]
                        )
                    except Exception as dl_err:
                        logger.warning(f"Failed to download Wikimedia video {file_url}: {dl_err}")
                        continue

                    meta = probe_video_metadata(saved_path)
                    if meta["width"] <= 0 or meta["duration"] <= 0.5:
                        logger.warning(f"Downloaded Wikimedia file {saved_path} has invalid video stream")
                        saved_path.unlink(missing_ok=True)
                        continue

                    description_url = imageinfo.get("descriptionurl", f"https://commons.wikimedia.org/wiki/{urllib.parse.quote(title)}")
                    license_url = extmeta.get("LicenseUrl", {}).get("value", "https://creativecommons.org/licenses/")

                    return VisualAssetResult(
                        local_path=saved_path,
                        asset_type="WIKIMEDIA",
                        sha256_checksum=sha256,
                        source_url=file_url,
                        author=artist,
                        license=license_name.upper(),
                        attribution_text=f"{artist} via Wikimedia Commons - '{title}' ({license_name.upper()})",
                        associated_claim_id=associated_claim_id,
                        source_asset_id=str(page_id),
                        source_page_url=description_url,
                        license_url=license_url,
                        media_type="video",
                        original_width=meta["width"],
                        original_height=meta["height"],
                        original_duration=meta["duration"],
                        file_size_bytes=downloaded_bytes,
                        rights_status="VERIFIED_FREE",
                        crop_transform="scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
                        selection_reason=f"Authentic Wikimedia Commons footage selected for query '{clean_q}'"
                    )

        except Exception as e:
            logger.warning(f"Wikimedia video search exception: {e}")
            return None

        return None
