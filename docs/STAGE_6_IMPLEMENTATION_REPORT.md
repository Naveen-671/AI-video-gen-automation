# Stage 6 Implementation Report — Secure YouTube OAuth and Private Upload

## 1. Executive Summary

Stage 6 of the **AI Shorts & Reels Factory** implements secure, official Google OAuth 2.0 authentication and a guarded private video upload workflow via the YouTube Data API v3 (`videos.insert` with resumable upload protocol).

In accordance with strict safety invariants:
1. **Initial uploads are strictly private:** Any upload request with `privacy_status` set to `public` or `unlisted` is blocked before touching the YouTube API.
2. **Cryptographic approval bound:** Upload is rejected unless an active, non-superseded human approval matching the exact on-disk SHA-256 checksum of the render exists in the database.
3. **Database trigger protection:** Direct database trigger `enforce_valid_approval_before_publish` prevents any publishing attempt without an approved, checksum-verified render.
4. **Secret redaction & zero leakage:** Client secrets, authorization codes, access tokens, and refresh tokens are stored with `0600` permissions outside Git in `data/secrets/`, with zero secret exposure in API responses or logs.
5. **Resumable uploads & exponential backoff:** Chunked transfer (1 MB chunks) handles network interruptions, transient 5xx errors, rate limits, and quota exhaustion safely.
6. **Zero live uploads in tests:** 9 comprehensive automated tests use mocked Google APIs; no test video was uploaded to a live channel. Full test suite achieves **84 passing tests with 0 failures**.

---

## 2. Files Modified & Added

| File | Status | Purpose |
|---|---|---|
| `.gitignore` | Modified | Added `data/secrets/`, `client_secret*.json`, and `*.secret*` |
| `backend/app/config.py` | Modified | Defined `SECRETS_DIR`, `YOUTUBE_SECRETS_FILE`, `YOUTUBE_CLIENT_SECRET_FILE`, and redirect URI |
| `backend/app/db/schema.sql` | Modified | Added `oauth_states` table for CSRF protection |
| `backend/app/db/connection.py` | Modified | Added migration check to create `oauth_states` table |
| `backend/app/db/repository.py` | Modified | Added state persistence, `publish_attempts` helpers, and active approval lookup |
| `backend/app/publishing/secrets.py` | **New** | File permission enforcement (`0600`/`0700`), secret loading, and status redaction |
| `backend/app/publishing/youtube_oauth.py` | **New** | OAuth 2.0 Web Server flow, CSRF verification, token exchange, and refresh handling |
| `backend/app/publishing/youtube_uploader.py` | **New** | Guarded resumable upload workflow with checksum re-verification and privacy boundary |
| `backend/app/api/main.py` | Modified | Added OAuth and publishing endpoints |
| `backend/tests/test_stage6_youtube_publishing.py` | **New** | 9 comprehensive mocked automated tests for OAuth and upload workflows |
| `frontend/src/app/page.tsx` | Modified | Added YouTube OAuth status, client configuration modal, and private upload UI card |
| `docs/ARCHITECTURE.md` | Modified | Added Section 8 detailing YouTube OAuth and private publishing architecture |
| `docs/TASK_LIST.md` | Modified | Marked Stage 6 tasks complete |
| `docs/STAGE_6_IMPLEMENTATION_REPORT.md` | **New** | Authoritative report, manual setup steps, and rollback instructions |

---

## 3. Architecture & Security Design

### 3.1 OAuth Flow & Secret-Storage Design
```
User Click "Connect YouTube"
        │
        ▼
GET /api/v1/auth/youtube/authorize
  ├── Generates cryptographically secure CSRF token: secrets.token_urlsafe(32)
  ├── Stores state in SQLite `oauth_states` with 10-minute expiry
  └── Redirects user to Google OAuth Consent Screen:
        • Scope: https://www.googleapis.com/auth/youtube.upload
        • access_type=offline (guarantees refresh_token)
        • prompt=consent
        │
        ▼
Google Consent Screen -> User Authorizes
        │
        ▼
GET /api/v1/auth/youtube/callback?code={code}&state={state}
  ├── Validates state against `oauth_states` (checks existence, expiry, and single-use)
  ├── Atomically marks state used (used_at = CURRENT_TIMESTAMP)
  ├── Exchanges code for access & refresh tokens via flow.fetch_token()
  ├── Verifies channel identity via channels().list(part="snippet", mine=True)
  └── Stores credentials in `data/secrets/youtube_credentials.json` with mode 0600
```

### 3.2 Permission-Restricted Storage (`backend/app/publishing/secrets.py`)
- Credential files are created with mode `0o600` (`-rw-------`), readable and writable only by the host user account.
- The `data/secrets/` directory is enforced at mode `0o700` (`drwx------`).
- The directory and secret file patterns are ignored in `.gitignore`.
- Fallback to environment variables (`YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`) is supported for headless environments.
- API status endpoint `/api/v1/auth/youtube/status` returns redacted client IDs (`123456...`) and connection health without printing client secrets or access tokens.

### 3.3 Guarded Upload Workflow (`backend/app/publishing/youtube_uploader.py`)
Before any byte is uploaded to Google:
1. **Render Record Check:** Verifies render exists and technical QA status is `PASSED`.
2. **On-Disk Checksum Re-verification:** Calculates SHA-256 of the MP4 file on disk. If it differs from `render.render_checksum` by even 1 bit, upload aborts immediately.
3. **Active Approval Check:** Checks SQLite `approvals` table for an approval matching the exact render checksum, `status == 'APPROVED'`, and `superseded_at IS NULL`.
4. **Strict Boundary Check:** Verifies `privacy_status == 'private'`. Non-private requests raise `YouTubeUploadError`.
5. **Database Trigger:** Inserts a record into `publish_attempts`. The SQLite trigger `enforce_valid_approval_before_publish` executes in the database engine, aborting the transaction if approval invariants are breached.
6. **Resumable Chunk Transfer:** Uploads in 1 MB chunks using `MediaFileUpload(resumable=True)`. Exponential backoff (`2 ** retry`) handles transient 5xx server errors up to 5 retries.
7. **Idempotency Deduplication:** Generates key `yt_up_{render_id}_{checksum[:12]}`. If already uploaded, returns confirmed video ID without duplicate uploads.

---

## 4. Test Suite & Validation Results

9 new automated tests were added in `backend/tests/test_stage6_youtube_publishing.py`:

| Test Name | Focus Area | Status |
|---|---|:---:|
| `test_secret_redaction_and_file_permissions` | 0600 POSIX permissions and secret masking in API responses | **PASSED** |
| `test_oauth_state_persistence_and_single_use` | CSRF token expiration, database lookup, and single-use consumption | **PASSED** |
| `test_oauth_flow_authorization_url_and_callback` | Mocked code-for-token exchange and channel snippet retrieval | **PASSED** |
| `test_upload_rejects_non_private_requests` | Strict publishing boundary rejecting `public` and `unlisted` | **PASSED** |
| `test_upload_rejects_missing_or_superseded_approval` | Fail-closed refusal when approval is missing or superseded | **PASSED** |
| `test_upload_rejects_on_disk_checksum_mismatch` | Tamper detection re-hashing on disk before upload | **PASSED** |
| `test_upload_resumable_success_and_idempotency` | Resumable chunked upload, DB recording, and duplicate avoidance | **PASSED** |
| `test_upload_quota_exceeded_error_handling` | Clean handling of HTTP 403 `quotaExceeded` with DB status updates | **PASSED** |
| `test_api_youtube_endpoints_and_redaction` | FastAPI endpoints status, configuration, and disconnect | **PASSED** |

### Complete Test Suite Status
```
=============================== test summary ===============================
84 passed, 1 warning in 94.64s (0:01:34)
100% PASS RATE ACROSS ALL 10 TEST MODULES
```

---

## 5. UI Dashboard Integration

The Next.js dashboard was updated with a dedicated **🔴 YouTube Publishing & OAuth** panel:
- **Connection Badge:** Displays connection status (`Connected: {Channel Name}` vs `Disconnected`).
- **Configuration Modal:** Allows entering Google OAuth Client ID and Secret, saved securely with mode `0600` permissions.
- **Approval Status:** Confirms human approval is active and bound to the render's exact SHA-256 checksum.
- **Upload Form:** Pre-populates title and description with automatic FactLedger attributions.
- **Privacy Lock:** Permanently locked to **Private** with visible indicator: `🔒 Initial uploads are strictly PRIVATE (Stage 6 Invariant)`.
- **Confirmed Video Link:** Upon confirmed upload, displays the YouTube Video ID and direct link to YouTube Studio.
- **Static Export:** Compiled and verified cleanly via `npm run build` to `frontend/out/`.

---

## 6. Manual Setup Guide (Google Cloud Console)

To enable live YouTube uploads, the operator must complete the following one-time configuration in Google Cloud:

### Step 1: Create or Select Google Cloud Project
1. Navigate to [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project named `AI-Shorts-Factory` (or select an existing project).

### Step 2: Enable the YouTube Data API v3
1. In the Google Cloud Console, go to **APIs & Services** > **Library**.
2. Search for `YouTube Data API v3` and click **Enable**.

### Step 3: Configure the OAuth Consent Screen
1. Go to **APIs & Services** > **OAuth consent screen**.
2. Select User Type: **External** (or Internal if using Google Workspace).
3. Fill in:
   - App Name: `AI Shorts Factory`
   - User Support Email: your email address
   - Developer Contact Email: your email address
4. Click **Save and Continue**.
5. Under **Scopes**, click **Add or Remove Scopes**, and select:
   - `https://www.googleapis.com/auth/youtube.upload`
   - `https://www.googleapis.com/auth/youtube.readonly`
6. Under **Test Users**, add your YouTube channel's Google account email address. (While the app is in "Testing" mode, only registered test users can authenticate).

### Step 4: Create OAuth 2.0 Web Client Credentials
1. Go to **APIs & Services** > **Credentials**.
2. Click **Create Credentials** > **OAuth client ID**.
3. Application Type: **Web application**.
4. Name: `AI Shorts Factory Web Client`.
5. Under **Authorized redirect URIs**, click **Add URI** and enter:
   ```
   http://localhost:8000/api/v1/auth/youtube/callback
   ```
6. Click **Create**.
7. Copy the **Client ID** and **Client Secret**.

### Step 5: Save Credentials in AI Shorts Factory
Choose one of two methods:
- **Option A (Dashboard UI):** Open the Mission Control dashboard at `http://localhost:8000`, click **⚙️ Configure Google Client** in the YouTube panel, paste your Client ID and Client Secret, and click **Save Credentials**.
- **Option B (Environment Variables):** Set in `.env`:
  ```bash
  YOUTUBE_CLIENT_ID="your_client_id.apps.googleusercontent.com"
  YOUTUBE_CLIENT_SECRET="your_client_secret"
  ```
- **Option C (Local File):** Save as `data/secrets/client_secret.json` with permissions `0600`.

### Step 6: Authenticate Channel
1. In the dashboard, click **🔑 Connect YouTube**.
2. Sign in with the registered Google account and grant upload permissions.
3. Upon redirect, the dashboard will confirm `Connected: {Your Channel Name}`.

---

## 7. Quota & Operational Considerations

- **Default YouTube Data API Quota:** 10,000 units per day.
- **Upload Cost:** Each `videos.insert` operation consumes **1,600 units**.
- **Maximum Daily Uploads on Free Quota:** $\approx 6$ videos per 24-hour cycle.
- **Quota Exceeded Behavior:** The uploader detects HTTP 403 `quotaExceeded`, aborts gracefully, records `FAILED` status in `publish_attempts`, and displays a clear message without corrupting project state.
- **Private Video Review:** Once uploaded as private, the video appears in YouTube Studio. The human operator can preview the video, inspect captions, and change visibility to Unlisted or Public manually when ready.

---

## 8. Rollback Instructions

If a rollback of Stage 6 is required:
1. Revoke and delete credentials:
   ```bash
   rm -rf data/secrets/
   ```
2. Revert Git working tree on branch `stage-5-hybrid-video`:
   ```bash
   git checkout HEAD -- backend/app/publishing/ backend/tests/test_stage6_youtube_publishing.py
   ```
3. The database migration for `oauth_states` does not affect existing render or approval operations.
