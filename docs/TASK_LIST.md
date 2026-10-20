# Phased Implementation Task List: AI Shorts & Reels Factory

**Document Status:** Pending User Review & Approval  
**Guiding Principle:** Small, testable, verifiable increments. Zero added cost. No model downloads or package installations without explicit user authorization.

---

## Phase 1: Environment Inspection, Architecture & Minimal Skeleton

### Step 1.1: Read-Only System & Environment Inspection [COMPLETED]
- [x] Record system OS, kernel, CPU, GPU VRAM, memory, and disk headroom.
- [x] Verify installed versions of Python, Node, npm, git, FFmpeg, and available encoders.
- [x] Verify project directory state and inspect existing Obsidian project memory.
- [x] Generate `docs/ENV_REPORT.md`.
- [x] Generate `docs/ARCHITECTURE.md`.
- [x] Generate `docs/DECISIONS.md`.
- [x] Generate `docs/TASK_LIST.md`.
- [ ] **STOP & AWAIT USER APPROVAL** on Environment Report and Decision Register.

### Step 1.2: Smallest Runnable Skeleton (Pending User Approval)
- [ ] Initialize local git repository (`git init`).
- [ ] Create project-local virtual environment (`python3 -m venv .venv`).
- [ ] Install base Python dependencies (`fastapi`, `uvicorn`, `pydantic`, `alembic`, `pytest`).
- [ ] Initialize Alembic with SQLite WAL database (`data/factory.db`).
- [ ] Define core database schema: `channels`, `jobs`, `renders`, `approvals`, `publish_attempts`, `settings`.
- [ ] Implement database trigger `enforce_valid_approval_before_publish`.
- [ ] Implement core State Machine module (`backend/app/domain/state_machines.py`):
  - Video transition validation.
  - Job lifecycle with atomic leasing and heartbeat.
  - Approval invalidation logic on input edit.
- [ ] Build FastAPI server (`backend/app/api`):
  - `GET /health`: Reports DB connection, worker status, disk/RAM headroom, and cost classes.
  - `POST /pause`: Toggles global system pause.
  - `GET /jobs`: Lists active and queued jobs.
- [ ] Build minimal worker daemon (`backend/app/worker`):
  - Polls job queue with `BEGIN IMMEDIATE`.
  - Executes one mock job to completion with heartbeat.
- [ ] Create minimal Next.js frontend (`frontend/`):
  - Displays system health, pause switch, and job queue.
  - Compiles to static export (`npm run build` -> `frontend/out`).
  - FastAPI serves `frontend/out` directly on `http://127.0.0.1:8000`.
- [ ] Write and run automated tests:
  - Unit tests for legal vs. illegal state transitions.
  - Test that modifying approved inputs invalidates approval and marks it superseded.
  - Test that direct DB insert of `publish_attempt` without valid approval raises SQLite trigger exception.
  - Test that mock publisher refuses unapproved render.
- [ ] Present execution commands and raw test output for user verification.

---

## Phase 2: Domain Schema, Provider Registry & Quota Ledger

- [ ] Complete full data model via Alembic migrations:
  - `profiles`, `ideas`, `master_scripts`, `localized_variants`, `storyboards`, `scenes`, `assets`, `quota_ledger`, `audit_log`.
- [ ] Implement Provider Registry (`backend/app/providers`):
  - Cost class enforcement (`free_local`, `free_quota`, `manual`, `metered`).
  - Startup check: Immediately abort if any provider has `cost_class: metered` without authorized override.
- [ ] Implement Quota Ledger (`reserve()`, `commit()`, `release()`):
  - Bounded concurrency and daily quota tracking.
- [ ] Implement Mock Providers:
  - Mock LLM script generator (schema-validated output).
  - Mock TTS audio generator (produces silent WAV with exact duration).
  - Mock Stills generator (produces test image cards with text overlay).
- [ ] Implement Job Recovery & Idempotency:
  - Worker restart recovery: Leases that expire without heartbeat are re-queued.
  - Exponential backoff on retryable failures; permanent failure threshold.

---

## Phase 3: Stills + Ken Burns Motion FFmpeg Composition Pipeline

- [ ] Verify Python wheels / packages for audio & composition.
- [ ] Implement declarative Render Recipe schema (`backend/app/media/recipe.py`):
  - Canonical JSON serialization and SHA-256 checksum computation.
- [ ] Implement Scene-Level Cache:
  - Content-addressed asset storage in `data/media/<sha256>`.
  - Re-use completed scenes when regenerating an edited storyboard.
- [ ] Implement FFmpeg Composition Engine (`backend/app/media/ffmpeg.py`):
  - 1080×1920 9:16 vertical composition filtergraphs.
  - Dynamic Ken Burns pan/zoom on high-res stills.
  - Audio mixing with voiceover ducking against background music.
  - Styled SSA/ASS subtitle burn-in.
- [ ] Integrate Kokoro-82M ONNX local TTS (subject to approval of model download, ~300 MB):
  - English & Hindi narration generation on CPU.
- [ ] Implement Manual Audio Ingest provider:
  - Support user-provided voiceovers for Kannada, Tamil, etc.
- [ ] Implement Rule-Based Technical QA (`backend/app/media/qa.py`):
  - `ffprobe` verification of dimensions (1080×1920), framerate (30 fps), codecs (`h264`, `aac`).
  - EBU R128 loudness check (-14 to -16 LUFS).
  - Black-frame and freeze-frame automated detection.
- [ ] End-to-end synthetic render verification:
  - Render 1 complete vertical Short using synthetic assets.
  - Verify render output manually with user.

---

## Phase 4: Benchmark Harness & Manual-Ingest Inbox

- [ ] Implement Manual-Ingest Inbox (`data/inbox/`):
  - Directory watcher for user-dropped Google Flow / external MP4 clips.
  - Metadata and provenance logger; estimated Flow credit ledger tracking.
- [ ] Develop Benchmark Harness (`scripts/benchmark_runner.py`):
  - Standardized 6-prompt evaluation suite.
  - Automated 1-second polling of `nvidia-smi` peak VRAM, host RAM, swap, and wall-clock execution time.
- [ ] Benchmark Evaluation Gates:
  - Execute harness against mock generator.
  - Review benchmark criteria with user before downloading any local diffusion model weights (e.g. LTX-Video 2B or Wan 1.3B).
  - **No model weights downloaded without explicit written user approval.**

---

## Phase 5: Review UI, Immutable Approvals & YouTube Publisher

- [ ] Review & Approval Web Interface:
  - Side-by-side preview of render, script, audio waveform, and QA report.
  - Review actions: Approve, Reject (with feedback note), Supersede.
  - Cryptographic binding: Approval token tied strictly to render SHA-256 checksum.
- [ ] Security & Keyring Integration:
  - OAuth client credentials and tokens loaded from OS Keyring (KDE Wallet).
  - Zero plain-text credentials in repository or environment files.
- [ ] YouTube Data API v3 Publisher Adapter:
  - Implements Outbox pattern.
  - Uploads restricted to `private` mode on dedicated test channel.
  - Includes synthetic content disclosure metadata flag.
- [ ] Publisher Reconciliation Engine:
  - Handles network timeouts / connection drops.
  - Transitions to `PUBLISH_UNCERTAIN` -> queries YouTube API for title/hash -> reconciles to `PUBLISHED` or `APPROVED` without duplicate re-upload.
- [ ] Instagram Reels Adapter (Deferred sequence):
  - Professional account and Meta Graph API setup.

---

## Phase 6: Analytics, Experiments & Adaptive Planning (Deferred)

- [ ] Metric snapshot collectors (YouTube Analytics API).
- [ ] Controlled experiment runner (single-variable comparison: thumbnail/hook/voice).
- [ ] Statistical significance and shrinkage model (flag datasets < 20 posts as anecdotal).
- [ ] LLM proposal adapter for topic recommendations based on verified historical metrics.
- [ ] *Phase 6 is strictly deferred until publishing volume and audience data exist.*
