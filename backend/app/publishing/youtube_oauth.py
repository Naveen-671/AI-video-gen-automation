"""
YouTube OAuth 2.0 Web Server Flow Manager.
Handles authorization URL generation, CSRF state persistence and validation,
code-for-token exchange, token refresh, and connection status reporting.
Never exposes raw tokens or secrets.
"""

import datetime
import logging
import secrets
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import google.auth.transport.requests
import google.oauth2.credentials
import google_auth_oauthlib.flow
import googleapiclient.discovery

from backend.app.config import DB_PATH, YOUTUBE_OAUTH_SCOPES, YOUTUBE_REDIRECT_URI
from backend.app.db.repository import (
    save_oauth_state,
    validate_and_consume_oauth_state
)
from backend.app.publishing.secrets import (
    delete_youtube_credentials,
    get_client_config,
    get_redacted_status,
    is_client_configured,
    load_youtube_credentials,
    save_youtube_credentials
)

logger = logging.getLogger("publishing.youtube_oauth")

EXTENDED_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly"
]


class YouTubeOAuthManager:
    """Manages secure YouTube OAuth 2.0 web-server flow and credential lifecycle."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path

    def get_authorization_url(self, redirect_uri: Optional[str] = None) -> Tuple[str, str]:
        """
        Generates an OAuth authorization URL with a cryptographically secure CSRF state token.
        Persists state in SQLite with 10-minute expiry.
        Returns: (authorization_url, state)
        """
        client_cfg = get_client_config()
        if not client_cfg or not is_client_configured():
            raise ValueError(
                "Google OAuth client is not configured. Please supply client_id and client_secret first."
            )

        resolved_redirect_uri = redirect_uri or YOUTUBE_REDIRECT_URI
        state = secrets.token_urlsafe(32)

        # Store CSRF token in DB with 600-second (10-minute) expiry
        save_oauth_state(state=state, platform="youtube", expires_in_seconds=600, db_path=self.db_path)

        flow = google_auth_oauthlib.flow.Flow.from_client_config(
            client_config=client_cfg,
            scopes=EXTENDED_SCOPES,
            state=state
        )
        flow.redirect_uri = resolved_redirect_uri

        auth_url, _ = flow.authorization_url(
            access_type="offline",
            prompt="consent",
            include_granted_scopes="true"
        )

        logger.info(f"Generated YouTube OAuth authorization URL with state token (expires in 10m).")
        return auth_url, state

    def handle_oauth_callback(
        self,
        code: str,
        state: str,
        redirect_uri: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Validates CSRF state, exchanges code for access & refresh tokens,
        queries authorized channel identity, and saves credentials with 0600 permissions.
        """
        if not state:
            raise ValueError("Missing OAuth state parameter.")
        if not code:
            raise ValueError("Missing OAuth authorization code parameter.")

        # 1. Atomic CSRF state verification
        is_valid = validate_and_consume_oauth_state(state=state, platform="youtube", db_path=self.db_path)
        if not is_valid:
            logger.warning("Rejected YouTube OAuth callback: State token is invalid, expired, or already used.")
            raise ValueError("Invalid or expired OAuth state token (CSRF verification failed).")

        client_cfg = get_client_config()
        if not client_cfg:
            raise ValueError("Google OAuth client config not found.")

        resolved_redirect_uri = redirect_uri or YOUTUBE_REDIRECT_URI
        flow = google_auth_oauthlib.flow.Flow.from_client_config(
            client_config=client_cfg,
            scopes=EXTENDED_SCOPES,
            state=state
        )
        flow.redirect_uri = resolved_redirect_uri

        # 2. Token exchange
        logger.info("Exchanging authorization code for OAuth tokens.")
        flow.fetch_token(code=code)
        creds = flow.credentials

        if not creds:
            raise RuntimeError("Failed to obtain credentials from OAuth code exchange.")

        # 3. Query channel metadata to verify access
        channel_id = None
        channel_title = "Unknown Channel"
        try:
            yt = googleapiclient.discovery.build("youtube", "v3", credentials=creds)
            channels_resp = yt.channels().list(part="snippet", mine=True).execute()
            items = channels_resp.get("items", [])
            if items:
                channel_id = items[0].get("id")
                channel_title = items[0].get("snippet", {}).get("title", "Authorized Channel")
        except Exception as e:
            logger.warning(f"Could not retrieve channel snippet during OAuth exchange: {e}")

        # 4. Save credentials securely with mode 0600
        creds_data = {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": list(creds.scopes) if creds.scopes else EXTENDED_SCOPES,
            "expiry": creds.expiry.isoformat() if creds.expiry else None,
            "channel_id": channel_id,
            "channel_title": channel_title,
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }
        save_youtube_credentials(creds_data)
        logger.info(f"Successfully authenticated YouTube channel: '{channel_title}' ({channel_id}).")

        return {
            "status": "SUCCESS",
            "channel_id": channel_id,
            "channel_title": channel_title,
            "message": f"Successfully connected YouTube channel '{channel_title}'."
        }

    def get_credentials(self) -> Optional[google.oauth2.credentials.Credentials]:
        """
        Loads stored credentials and automatically refreshes them if expired.
        Returns None if not configured, invalid, or revoked.
        """
        creds_data = load_youtube_credentials()
        if not creds_data or not creds_data.get("token"):
            return None

        expiry = None
        if creds_data.get("expiry"):
            try:
                expiry = datetime.datetime.fromisoformat(creds_data["expiry"])
                # Normalize naive to UTC
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=datetime.timezone.utc)
            except Exception:
                expiry = None

        creds = google.oauth2.credentials.Credentials(
            token=creds_data.get("token"),
            refresh_token=creds_data.get("refresh_token"),
            token_uri=creds_data.get("token_uri") or "https://oauth2.googleapis.com/token",
            client_id=creds_data.get("client_id"),
            client_secret=creds_data.get("client_secret"),
            scopes=creds_data.get("scopes") or EXTENDED_SCOPES,
            expiry=expiry
        )

        # Handle automatic refresh
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        if expiry and expiry <= now_utc:
            if creds.refresh_token:
                try:
                    logger.info("Access token expired. Refreshing using refresh_token.")
                    req = google.auth.transport.requests.Request()
                    creds.refresh(req)
                    # Persist refreshed token
                    creds_data["token"] = creds.token
                    if creds.expiry:
                        creds_data["expiry"] = creds.expiry.isoformat()
                    creds_data["updated_at"] = now_utc.isoformat()
                    save_youtube_credentials(creds_data)
                    logger.info("Successfully refreshed and stored access token.")
                except Exception as refresh_err:
                    logger.error(f"Failed to refresh YouTube access token: {refresh_err}")
                    return None
            else:
                logger.warning("Access token is expired and no refresh token is present.")
                return None

        return creds

    def get_authenticated_service(self) -> Any:
        """
        Builds and returns an authorized YouTube Resource.
        Raises RuntimeError if not connected.
        """
        creds = self.get_credentials()
        if not creds:
            raise RuntimeError(
                "YouTube is not authenticated or credentials have expired. "
                "Please connect your YouTube channel via OAuth."
            )
        return googleapiclient.discovery.build("youtube", "v3", credentials=creds)

    def get_status(self) -> Dict[str, Any]:
        """Returns safe connection status without exposing secrets."""
        redacted = get_redacted_status()
        creds = self.get_credentials()
        is_connected = bool(creds and creds.valid)
        return {
            "connected": is_connected,
            "client_configured": redacted["client_configured"],
            "client_id_redacted": redacted["client_id_redacted"],
            "channel_id": redacted["connected_channel_id"],
            "channel_title": redacted["connected_channel_title"],
            "token_present": redacted["token_present"],
            "refresh_token_present": redacted["refresh_token_present"],
            "token_expiry": redacted["token_expiry"],
            "storage_mode": redacted["storage_mode"],
            "required_scope": "https://www.googleapis.com/auth/youtube.upload"
        }

    def disconnect(self) -> bool:
        """Removes stored OAuth credentials."""
        return delete_youtube_credentials()
