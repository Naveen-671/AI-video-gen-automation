"""
Secure credential and secret storage for YouTube OAuth 2.0.
Enforces permission-restricted local secret storage (mode 0600 on files, 0700 on dirs),
environment variable fallbacks, secret redaction, and zero secret leakage in application logs.
"""

import json
import logging
import os
import stat
from pathlib import Path
from typing import Any, Dict, Optional

from backend.app.config import (
    SECRETS_DIR,
    YOUTUBE_CLIENT_SECRET_FILE,
    YOUTUBE_SECRETS_FILE
)

logger = logging.getLogger("publishing.secrets")


def ensure_secrets_dir() -> Path:
    """Creates the secrets directory if it doesn't exist and enforces 0700 permissions."""
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(SECRETS_DIR, 0o700)
    except Exception as e:
        logger.debug(f"Could not chmod secrets directory: {e}")
    return SECRETS_DIR


def set_restricted_file_permissions(file_path: Path):
    """Enforces 0600 (read/write only by owner) on credential files."""
    try:
        os.chmod(file_path, 0o600)
    except Exception as e:
        logger.debug(f"Could not chmod {file_path}: {e}")


def save_client_secret(
    client_id: str,
    client_secret: str,
    project_id: str = "ai-shorts-factory",
    auth_uri: str = "https://accounts.google.com/o/oauth2/auth",
    token_uri: str = "https://oauth2.googleapis.com/token",
    redirect_uris: Optional[list] = None
) -> Path:
    """
    Saves Google OAuth Web Client configuration to client_secret.json with 0600 permissions.
    """
    ensure_secrets_dir()
    if redirect_uris is None:
        redirect_uris = ["http://localhost:8000/api/v1/auth/youtube/callback"]

    config_data = {
        "web": {
            "client_id": client_id.strip(),
            "project_id": project_id.strip(),
            "auth_uri": auth_uri,
            "token_uri": token_uri,
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_secret": client_secret.strip(),
            "redirect_uris": redirect_uris
        }
    }

    temp_path = YOUTUBE_CLIENT_SECRET_FILE.with_suffix(".tmp")
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2)
    set_restricted_file_permissions(temp_path)
    temp_path.replace(YOUTUBE_CLIENT_SECRET_FILE)
    set_restricted_file_permissions(YOUTUBE_CLIENT_SECRET_FILE)
    logger.info("Google OAuth client configuration saved securely with 0600 permissions.")
    return YOUTUBE_CLIENT_SECRET_FILE


def get_client_config() -> Optional[Dict[str, Any]]:
    """
    Loads OAuth client config from file or environment variables.
    Never exposes raw client secret in logs.
    """
    # 1. Check environment variables first
    env_id = os.getenv("YOUTUBE_CLIENT_ID")
    env_secret = os.getenv("YOUTUBE_CLIENT_SECRET")
    if env_id and env_secret:
        return {
            "web": {
                "client_id": env_id.strip(),
                "project_id": os.getenv("YOUTUBE_PROJECT_ID", "ai-shorts-factory"),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "client_secret": env_secret.strip(),
                "redirect_uris": [os.getenv("YOUTUBE_REDIRECT_URI", "http://localhost:8000/api/v1/auth/youtube/callback")]
            }
        }

    # 2. Check local client_secret.json file
    if YOUTUBE_CLIENT_SECRET_FILE.exists():
        try:
            with open(YOUTUBE_CLIENT_SECRET_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "web" in data or "installed" in data:
                    return data
        except Exception as e:
            logger.error(f"Failed to read client_secret file: {e}")
            return None

    return None


def is_client_configured() -> bool:
    """Returns True if client_id and client_secret are available."""
    config = get_client_config()
    if not config:
        return False
    entry = config.get("web") or config.get("installed") or {}
    return bool(entry.get("client_id") and entry.get("client_secret"))


def save_youtube_credentials(creds_data: Dict[str, Any]) -> Path:
    """
    Persists token credentials (access token, refresh token, expiry) to youtube_credentials.json.
    Enforces mode 0600 permissions.
    """
    ensure_secrets_dir()
    temp_path = YOUTUBE_SECRETS_FILE.with_suffix(".tmp")
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(creds_data, f, indent=2)
    set_restricted_file_permissions(temp_path)
    temp_path.replace(YOUTUBE_SECRETS_FILE)
    set_restricted_file_permissions(YOUTUBE_SECRETS_FILE)
    logger.info("YouTube OAuth credentials saved with 0600 permissions.")
    return YOUTUBE_SECRETS_FILE


def load_youtube_credentials() -> Optional[Dict[str, Any]]:
    """Loads stored token credentials from youtube_credentials.json if available."""
    if not YOUTUBE_SECRETS_FILE.exists():
        return None
    try:
        with open(YOUTUBE_SECRETS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load YouTube credentials: {e}")
        return None


def delete_youtube_credentials() -> bool:
    """Deletes stored token credentials securely."""
    if YOUTUBE_SECRETS_FILE.exists():
        try:
            YOUTUBE_SECRETS_FILE.unlink(missing_ok=True)
            logger.info("YouTube credentials file removed.")
            return True
        except Exception as e:
            logger.error(f"Failed to delete YouTube credentials: {e}")
            return False
    return True


def redact_string(val: Optional[str], unmasked_chars: int = 4) -> str:
    """Redacts sensitive token or secret values for safe reporting."""
    if not val:
        return "Not configured"
    val = str(val).strip()
    if len(val) <= unmasked_chars * 2:
        return "***"
    return f"{val[:unmasked_chars]}...{val[-unmasked_chars:]}"


def get_redacted_status() -> Dict[str, Any]:
    """
    Returns public status information without exposing raw secrets.
    Safe to return in API endpoints and logs.
    """
    client_cfg = get_client_config()
    client_entry = (client_cfg.get("web") or client_cfg.get("installed") or {}) if client_cfg else {}
    client_id = client_entry.get("client_id")

    creds = load_youtube_credentials()
    has_token = bool(creds and creds.get("token"))
    has_refresh_token = bool(creds and creds.get("refresh_token"))

    return {
        "client_configured": bool(client_id),
        "client_id_redacted": redact_string(client_id, unmasked_chars=6) if client_id else None,
        "token_present": has_token,
        "refresh_token_present": has_refresh_token,
        "token_expiry": creds.get("expiry") if creds else None,
        "connected_channel_id": creds.get("channel_id") if creds else None,
        "connected_channel_title": creds.get("channel_title") if creds else None,
        "storage_mode": "local_restricted_file_0600"
    }
