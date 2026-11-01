"""
Guarded YouTube Private Uploader for Stage 6.
Enforces multi-layer safety invariants before touching the YouTube API:
1. Validates render exists and QA status is PASSED.
2. Re-computes on-disk SHA-256 and verifies exact match with render record.
3. Verifies active, non-superseded human approval matching exact checksum.
4. Enforces database trigger on publish_attempts table.
5. Strictly enforces initial upload privacyStatus='private'.
6. Executes resumable upload with exponential backoff and quota error handling.
"""

import hashlib
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import googleapiclient.errors
from googleapiclient.http import MediaFileUpload

from backend.app.config import DB_PATH
from backend.app.db.connection import get_connection
from backend.app.db.repository import (
    create_publish_attempt,
    get_active_approval_for_render,
    get_asset_provenances,
    get_project,
    get_publish_attempt,
    get_render,
    update_publish_attempt_status
)
from backend.app.publishing.youtube_oauth import YouTubeOAuthManager

logger = logging.getLogger("publishing.youtube_uploader")


class YouTubeUploadError(Exception):
    """Raised when YouTube upload validation or execution fails."""
    pass


class YouTubeUploader:
    """Orchestrates guarded, checksum-verified private uploads to YouTube."""

    def __init__(self, db_path: Path = DB_PATH, oauth_manager: Optional[YouTubeOAuthManager] = None):
        self.db_path = db_path
        self.oauth_manager = oauth_manager or YouTubeOAuthManager(db_path=db_path)

    @staticmethod
    def compute_sha256(file_path: Path) -> str:
        """Computes deterministic SHA-256 checksum of video file."""
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()

    def build_attributed_description(
        self,
        project_id: str,
        user_description: str,
        topic: str
    ) -> str:
        """
        Appends source-asset attribution ledger to video description for transparency.
        """
        lines = [user_description.strip()] if user_description else [f"Explainer video on {topic}."]
        lines.append("\n---\nCreated with AI Shorts & Reels Factory.")

        provenances = get_asset_provenances(project_id, db_path=self.db_path)
        if provenances:
            lines.append("\nVisual & Audio Attributions:")
            for p in provenances:
                idx = p.get("scene_index", 0) + 1
                attr = p.get("attribution_text") or p.get("author") or "Open Media"
                lic = p.get("license") or "Public Domain"
                lines.append(f"• Scene {idx}: {attr} ({lic})")

        return "\n".join(lines)[:5000]

    def upload_private_video(
        self,
        project_id: str,
        render_id: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
        category_id: str = "28",  # Science & Technology
        privacy_status: str = "private"
    ) -> Dict[str, Any]:
        """
        Executes guarded YouTube upload for an approved render.
        STRICT PUBLISHING BOUNDARY: privacy_status MUST be 'private'.
        """
        # =========================================================================
        # 1. STRICT PUBLISHING BOUNDARY GUARD
        # =========================================================================
        if privacy_status.lower() != "private":
            logger.warning(f"Rejected non-private upload request ('{privacy_status}'). Enforcing 'private'.")
            raise YouTubeUploadError(
                "Strict publishing boundary violation: In Stage 6, initial uploads MUST be 'private'. "
                "Automatic public or unlisted publishing is strictly prohibited."
            )

        # =========================================================================
        # 2. RENDER INTEGRITY & ON-DISK CHECKSUM VERIFICATION
        # =========================================================================
        project = get_project(project_id, db_path=self.db_path)
        if not project:
            raise YouTubeUploadError(f"Project '{project_id}' not found.")

        render = get_render(render_id, db_path=self.db_path)
        if not render:
            raise YouTubeUploadError(f"Render '{render_id}' not found.")

        if render.get("qa_status") != "PASSED":
            raise YouTubeUploadError(
                f"Render '{render_id}' cannot be published: Technical QA status is '{render.get('qa_status')}' (must be 'PASSED')."
            )

        file_path_str = render.get("file_path")
        if not file_path_str:
            raise YouTubeUploadError("Render record does not have a valid file_path.")

        file_path = Path(file_path_str)
        if not file_path.exists() or file_path.stat().st_size == 0:
            raise YouTubeUploadError(f"Render output video file does not exist on disk: {file_path}")

        # Re-compute checksum on disk to guarantee zero tampering
        on_disk_checksum = self.compute_sha256(file_path)
        recorded_checksum = render.get("render_checksum")
        if on_disk_checksum != recorded_checksum:
            raise YouTubeUploadError(
                f"Checksum mismatch! On-disk SHA-256 '{on_disk_checksum}' does not match "
                f"immutable render record '{recorded_checksum}'. Upload aborted."
            )

        # =========================================================================
        # 3. HUMAN APPROVAL VERIFICATION
        # =========================================================================
        approval = get_active_approval_for_render(render_id, db_path=self.db_path)
        if not approval:
            raise YouTubeUploadError(
                f"No active, non-superseded human approval found for render '{render_id}' "
                f"matching checksum '{recorded_checksum}'. Video must be explicitly approved before upload."
            )

        approval_id = approval["id"]

        # =========================================================================
        # 4. OAUTH CREDENTIALS & CHANNEL VERIFICATION
        # =========================================================================
        youtube_service = self.oauth_manager.get_authenticated_service()
        oauth_status = self.oauth_manager.get_status()
        target_channel_id = oauth_status.get("channel_id") or "mine"

        # =========================================================================
        # 5. IDEMPOTENCY CHECK & DATABASE TRIGGER REGISTRATION
        # =========================================================================
        idempotency_key = f"yt_up_{render_id}_{recorded_checksum[:12]}"
        
        # Check if already uploaded
        conn = get_connection(self.db_path)
        try:
            existing = conn.execute(
                "SELECT * FROM publish_attempts WHERE idempotency_key = ?",
                (idempotency_key,)
            ).fetchone()
            if existing and existing["status"] == "UPLOADED" and existing["external_id"]:
                logger.info(f"Render '{render_id}' already uploaded to YouTube (Video ID: {existing['external_id']}).")
                return {
                    "status": "ALREADY_UPLOADED",
                    "attempt_id": existing["id"],
                    "video_id": existing["external_id"],
                    "youtube_url": f"https://youtu.be/{existing['external_id']}",
                    "privacy_status": "private",
                    "render_checksum": recorded_checksum,
                    "message": "Render was already successfully uploaded to YouTube."
                }
        finally:
            conn.close()

        attempt_id = str(uuid.uuid4())
        try:
            # Enforces database trigger: enforce_valid_approval_before_publish
            create_publish_attempt(
                attempt_id=attempt_id,
                approval_id=approval_id,
                render_id=render_id,
                platform="youtube",
                target_channel_id=target_channel_id,
                idempotency_key=idempotency_key,
                db_path=self.db_path
            )
        except Exception as trigger_err:
            logger.error(f"Database trigger rejected publish attempt: {trigger_err}")
            raise YouTubeUploadError(f"Database rejected publish attempt: {trigger_err}")

        # =========================================================================
        # 6. METADATA PREPARATION
        # =========================================================================
        resolved_title = (title or project.get("title") or project.get("topic") or "Untitled Short").strip()[:100]
        resolved_desc = self.build_attributed_description(
            project_id=project_id,
            user_description=description or "",
            topic=project.get("topic", "")
        )
        resolved_tags = tags or ["Shorts", "Science", "Education"]

        snippet = {
            "title": resolved_title,
            "description": resolved_desc,
            "tags": resolved_tags,
            "categoryId": str(category_id)
        }
        status_body = {
            "privacyStatus": "private",
            "selfDeclaredMadeForKids": False
        }
        body = {
            "snippet": snippet,
            "status": status_body
        }

        # =========================================================================
        # 7. RESUMABLE CHUNKED UPLOAD
        # =========================================================================
        logger.info(
            f"Beginning resumable private upload to YouTube for render '{render_id}' "
            f"({file_path.stat().st_size / (1024*1024):.2f} MB)"
        )
        update_publish_attempt_status(attempt_id, "UPLOADING", db_path=self.db_path)

        media = MediaFileUpload(
            str(file_path),
            mimetype="video/mp4",
            chunksize=1024 * 1024,  # 1 MB chunk
            resumable=True
        )

        try:
            request = youtube_service.videos().insert(
                part="snippet,status",
                body=body,
                media_body=media
            )

            response = None
            retries = 0
            max_retries = 5

            while response is None:
                try:
                    upload_status, response = request.next_chunk()
                    if upload_status:
                        progress = int(upload_status.progress() * 100)
                        logger.info(f"YouTube upload progress: {progress}%")
                except googleapiclient.errors.HttpError as http_err:
                    if http_err.resp.status in [500, 502, 503, 504]:
                        retries += 1
                        if retries > max_retries:
                            raise
                        sleep_s = 2 ** retries
                        logger.warning(f"Transient 5xx error from YouTube API. Retrying in {sleep_s}s...")
                        time.sleep(sleep_s)
                    elif http_err.resp.status == 403 and "quotaExceeded" in str(http_err):
                        error_msg = "YouTube API upload quota exceeded for today. Upload aborted safely."
                        update_publish_attempt_status(attempt_id, "FAILED", error_message=error_msg, db_path=self.db_path)
                        raise YouTubeUploadError(error_msg)
                    elif http_err.resp.status == 401 or "invalid_grant" in str(http_err):
                        error_msg = "YouTube OAuth credentials expired or revoked. Re-authentication required."
                        update_publish_attempt_status(attempt_id, "FAILED", error_message=error_msg, db_path=self.db_path)
                        raise YouTubeUploadError(error_msg)
                    else:
                        raise

            video_id = response.get("id")
            if not video_id:
                raise YouTubeUploadError(f"Upload completed but response did not contain a video ID: {response}")

            # Verify confirmed upload status
            update_publish_attempt_status(
                attempt_id=attempt_id,
                status="UPLOADED",
                external_id=video_id,
                db_path=self.db_path
            )

            logger.info(f"YouTube private upload confirmed! Video ID: {video_id}")
            return {
                "status": "SUCCESS",
                "attempt_id": attempt_id,
                "video_id": video_id,
                "youtube_url": f"https://youtu.be/{video_id}",
                "privacy_status": "private",
                "render_checksum": recorded_checksum,
                "title": resolved_title,
                "message": "Video successfully uploaded as PRIVATE to YouTube."
            }

        except Exception as e:
            logger.error(f"YouTube upload failed: {e}")
            update_publish_attempt_status(
                attempt_id=attempt_id,
                status="FAILED",
                error_message=str(e)[:500],
                db_path=self.db_path
            )
            if not isinstance(e, YouTubeUploadError):
                raise YouTubeUploadError(f"YouTube upload error: {e}")
            raise
