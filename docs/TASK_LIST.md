# Phased Implementation Task List: AI Shorts & Reels Factory

**Document Status:** Phase 1, Phase 2A, Phase 2B, Stage 2 & Stage 3 Completed · Stage 4 Feasibility Evaluation Completed · Awaiting User Decision  
**Guiding Principle:** Small, testable, verifiable increments. Zero added cost. No model downloads or package installations without explicit user authorization.

---

## Phase 1: Environment Inspection, Architecture & Minimal Skeleton [COMPLETED]

### Step 1.1: Read-Only System & Environment Inspection [COMPLETED]
- [x] Record system OS, kernel, CPU, GPU VRAM, memory, and disk headroom.
- [x] Verify installed versions of Python, Node, npm, git, FFmpeg, and available encoders.
- [x] Verify project directory state and inspect existing Obsidian project memory.
- [x] Generate `docs/ENV_REPORT.md`, `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, `docs/TASK_LIST.md`.
- [x] User review and explicit approval of ADR-01 through ADR-11.

### Step 1.2: Smallest Runnable Skeleton [COMPLETED]
- [x] Initialize local git repository (`git init`) - Commit `b66173e`.
- [x] Create project-local virtual environment (`python3 -m venv .venv`).
- [x] Install base Python dependencies (`fastapi`, `uvicorn`, `pydantic`, `pytest`, `httpx`, `psutil`).
- [x] Initialize SQLite WAL database (`data/factory.db`).
- [x] Define core database schema with hard database trigger `enforce_valid_approval_before_publish`.
- [x] Implement core State Machine module (`backend/app/domain/state_machines.py`).
- [x] Build FastAPI server (`/health`, `/pause`, `/jobs`).
- [x] Build minimal worker daemon with atomic leasing (`BEGIN IMMEDIATE`) and heartbeat.
- [x] Create minimal Next.js frontend compiled to static export served by FastAPI.
- [x] Write and pass 24 automated tests covering state machines, approvals trigger, job recovery, and publisher refusal.

---

## Phase 2A: First End-to-End Short Video Pipeline [COMPLETED]

### Step 2A.1: Open-Source Component Evaluation [COMPLETED]
- [x] Evaluate FFmpeg direct CLI vs MoviePy.
- [x] Evaluate Kokoro-82M ONNX vs Piper vs manual audio ingest.
- [x] Evaluate local image generation vs SVG/gradient backdrops.
- [x] Evaluate SubStation Alpha (ASS) vs SRT subtitle burn-in.
- [x] Document findings in `docs/PHASE_2A_COMPONENT_EVALUATION.md`.

### Step 2A.2: Pipeline Implementation [COMPLETED]
- [x] Database entities: `projects` and `project_scenes` added with relational integrity.
- [x] Deterministic script & storyboard proposal generator (user-editable).
- [x] Dynamic background generation and secure asset upload endpoint (path traversal checks, size limits).
- [x] Narration adapters: `silent` and `manual_audio` modes implemented.
- [x] Declarative FFmpeg composition engine rendering vertical 9:16 H.264/AAC MP4 via safe argument lists.
- [x] SubStation Alpha (ASS) subtitle generator with mobile platform safety margins.
- [x] Rule-based technical QA (`ffprobe`) verifying resolution, aspect ratio, duration, and stream presence.
- [x] In-browser video preview, download MP4 button, and Human Approval / Rejection actions.
- [x] Approval binding to exact SHA-256 checksum; automatic invalidation/superseding upon edit.
- [x] Updated static Next.js dashboard export in `frontend/out`.
- [x] 35 comprehensive automated tests passing with zero failures.

---

## Phase 2B: Local Neural Narration (Kokoro-82M ONNX) & Benchmark [COMPLETED - STAGE 1]

### Step 2B.1: Model & Runtime Evaluation [COMPLETED]
- [x] Inspect official Kokoro ONNX releases and model cards (`model-files-v1.1`).
- [x] Verify exact language support: English (50+ voices) and Hindi (`hf_alpha`, `hf_beta`, `hm_omega`, `hm_psi`) verified; Kannada/Tamil/etc. confirmed via `manual_audio`.
- [x] Verify Python 3.14 wheel availability (`onnxruntime==1.31.0`, `kokoro-onnx==0.4.7`, `soundfile==0.14.0`, `numpy==2.5.4`).
- [x] Confirm CPU-only inference, zero VRAM usage, ~156 MB FP16 ONNX model + ~27 MB voices binary.
- [x] Document findings in `docs/PHASE_2B_TTS_EVALUATION.md`.

### Step 2B.2: Implementation & Benchmarking [COMPLETED - STAGE 1]
- [x] Install pinned dependencies in project `.venv` (`kokoro-onnx`, `onnxruntime`, `soundfile`, `numpy`).
- [x] Download FP16 Kokoro ONNX model and matching voice file from verified upstream release (`models/kokoro/`).
- [x] Verify file sizes and SHA-256 checksums (`f3a290d...` and `bca610b...`). Recorded in `models/kokoro/checksums.sha256`.
- [x] Model weights kept strictly outside Git (`models/` in `.gitignore`).
- [x] Implement `LocalTTSAdapter` in `backend/app/media/narration.py` with runtime speed dtype patch for ONNX.
- [x] Preserve `silent` and `manual_audio` adapters with fail-closed error handling (no cloud fallbacks).
- [x] Integrate `local_tts` mode into `projects` schema, API endpoints (`/tts/voices`, `PUT /projects/{id}/narration`), Next.js UI, and `WorkerRunner` composition pipeline.
- [x] Enforce approval invalidation whenever narration text, mode, or voice changes.
- [x] Benchmark cold start (1.44s), warm inference RTF (0.264 to 0.291 / 3.4× to 3.8× faster than real time), RAM footprint (~508 MB), and audio acoustic levels (-22.6 dB mean).
- [x] Render real Short sample with local narration (`render_9386e90b.mp4`) and verify via `ffprobe` and Technical QA.
- [x] 46 automated tests passing across the entire test suite.
- [x] Produce `docs/PHASE_2B_IMPLEMENTATION_REPORT.md`.
- [ ] **STOP & AWAIT USER REVIEW** before proceeding to Stage 2 (Research Agent & Script Intelligence).

---

## Stage 2: Quality Research Agent & Script Intelligence [COMPLETED]

### Step 2.1: Evaluation & Adapter Architecture [COMPLETED]
- [x] Evaluate DuckDuckGo search library (`ddgs==9.16.0` with `primp==2.0.1` and `lxml==6.1.3`). Python 3.14 verified, MIT license, zero API keys.
- [x] Evaluate Crawl4AI vs lightweight HTTP extraction. Deferred Crawl4AI/Chromium (~400 MB disk, ~800 MB RAM) in favor of lightweight `HTTPTextExtractionAdapter` (<25 MB RAM, 0 VRAM, ~0.4s response).
- [x] Establish invariant: Search snippets are never accepted as verified evidence without full document extraction.
- [x] Enforce explicit claim status: `VERIFIED`, `UNVERIFIED`, `INSUFFICIENT_EVIDENCE`.

### Step 2.2: FactLedger & Narrative Intelligence Implementation [COMPLETED]
- [x] SQLite schema migrations: added `fact_sources`, `fact_claims`, `script_proposals` tables and `supporting_claim_ids` column on `project_scenes`.
- [x] Implement `FactLedgerManager` in `backend/app/research/fact_ledger.py` with provenance verification and duplicate claim detection via word overlap.
- [x] Implement `DeterministicScriptProposalAdapter` in `backend/app/research/narrative_architect.py` supporting 4 archetypes: `CURIOSITY_GAP`, `HISTORICAL_MICRO_EPIC`, `DISCONFIRMATION_JOURNEY`, `SCALE_SHOCK`.
- [x] Implement `DeterministicScriptValidator` in `backend/app/research/validator.py` enforcing evidence references, duplicate prevention, cadence (2.2–2.8 WPS), and hook potency.
- [x] Implement `ResearchAgent` orchestrator in `backend/app/research/agent.py`.
- [x] Integrate `RESEARCH_TOPIC` stage handler into background worker (`backend/app/worker/runner.py`).
- [x] Add REST API endpoints: `POST /research/discover`, `GET /projects/{project_id}/facts`, `POST /projects/{project_id}/research`.
- [x] Add interactive FactLedger review panel, archetype picker, claim badges, and validation warnings to Next.js dashboard.
- [x] Write and pass 11 automated research tests (57 total passing across full suite).
- [x] Rebuild Next.js static production export (`npm run build`).
- [x] Author `docs/STAGE_2_IMPLEMENTATION_REPORT.md`.
- [ ] **STOP & AWAIT USER REVIEW** before proceeding to Stage 3 (Stills + Pan/Zoom Motion & Audio Ducking).

---

## Stage 3: High-Quality Visual Assembly, Motion, and Audio Mix [COMPLETED]

### Step 3.1: Visual Asset Priority Adapters & Provenance [COMPLETED]
- [x] Implement `CompositeVisualResolver` with strict priority: User Uploads -> Wikimedia/NASA APIs -> Procedural Infographics -> Default Fallback.
- [x] Persist asset attribution, license, author, source URL, and claim binding to `asset_provenance` SQLite table.
- [x] Implement `ProceduralGraphicAdapter` using Pillow, producing vector-like 1080x1920 scientific diagrams (zero network, zero API keys, CC0).
- [x] Add download-size limits (15 MB), timeouts (8s), content-type validation, and path traversal guards.

### Step 3.2: Ken Burns Motion Engine & Subtitle Synchronization [COMPLETED]
- [x] Upgrade `FFmpegComposer` with smooth, bounded Ken Burns pan/zoom filtergraph presets (`zoom_in`, `zoom_out`, `pan_left`, `pan_right`, `tilt_up`, `tilt_down`, `static`).
- [x] Bound zoom factors strictly between 1.0 and 1.12x to avoid pixelation or disorienting movement.
- [x] Upgrade `generate_ass_subtitles` with phrase-level rhythmic chunking (2-4 words) and mobile UI safe-zone offsets (bottom margin >= 240px for 1080p).
- [x] Full Unicode support for English and Hindi captions with bold white text, black outline, and active keyword highlight.

### Step 3.3: Audio Hierarchy, Sidechain Ducking & Normalization [COMPLETED]
- [x] Implement `AudioMixer` with procedural ambient drone bed generator (`generate_ambient_bed`) for royalty-free background audio.
- [x] Implement FFmpeg-based sidechain compression ducking background music by ~14 to 18 dB during speech.
- [x] Apply EBU R128 `loudnorm` normalization (integrated -16.0 LUFS, true peak <= -1.5 dBTP) and measure audio compliance.
- [x] Support voice-only rendering without background music.

### Step 3.4: Dual-Tier Quality Assurance (Technical QA & Editorial QA) [COMPLETED]
- [x] Technical QA enhancements: black-frame detection (`blackdetect`), freeze-frame detection (`freezedetect`), audio clipping, and true peak checks.
- [x] Implement `EditorialQA`: evaluates opening hook potency in first 3s, spoken cadence (2.2-2.8 WPS), visual diversity, and philosophical payoff.
- [x] Persist editorial evaluations to `editorial_reviews` table and expose in review dashboard.

### Step 3.5: Benchmark Render & Full Test Suite [COMPLETED]
- [x] Render real 1080x1920 benchmark Short: "Why time moves slightly slower at sea level than at high altitude" (31.83s, 5.76 MB, H.264/AAC, -16.2 LUFS, Editorial Score 95/100).
- [x] Add 9 comprehensive Stage 3 automated tests in `backend/tests/test_stage3_pipeline.py`.
- [x] 66 total automated tests passing across full project with 100% success.
- [x] Rebuild Next.js static production export (`npm run build`).
- [x] Author `docs/STAGE_3_IMPLEMENTATION_REPORT.md`.
- [ ] **STOP & AWAIT USER REVIEW** before proceeding to Stage 4 (Diffusion Video Evaluation / Publishing).

---

## Stage 4: Motion and Video-Generation Feasibility Evaluation [COMPLETED]

- [x] Live hardware inspection: verified 6,144 MiB VRAM (5,765 MiB free), 14 GiB RAM (6.8 GiB available, 3.1 GiB swap used), 44 GB free disk, Python 3.14.6 in `.venv`.
- [x] In-depth candidate evaluation: LTX-Video 2B distilled vs Wan 2.1 1.3B vs NASA/Wikimedia Public Domain Video vs Procedural Vector Animation.
- [x] Hardware feasibility verdict: Local diffusion rejected due to Python 3.14 wheel unavailability, 6 GB VRAM hard ceiling, RAM offload OOM risk, and severe disk exhaustion (15-25 GB).
- [x] Designed standardized 3-track comparative visual benchmark on Gravitational Time Dilation.
- [x] Formulated recommended Hybrid High-Craft Strategy: Programmatic NASA Open Video API / Wikimedia Ingest + FFmpeg `xfade` cross-dissolves + Procedural Infographics.
- [x] Authored `docs/STAGE_4_FEASIBILITY_REPORT.md`.

---

## Stage 5: Hybrid High-Craft Visual Engine [COMPLETED]

### Step 5.1: Database Schema & Provenance Extension [COMPLETED]
- [x] Extend `asset_provenance` table schema with extended columns: `source_asset_id`, `source_page_url`, `license_url`, `media_type`, `original_width`, `original_height`, `original_duration`, `file_size_bytes`, `rights_status`, `crop_transform`, `selection_reason`.
- [x] Add automated SQLite WAL migration checks in `backend/app/db/connection.py`.
- [x] Update domain model `AssetProvenanceModel` in `backend/app/domain/models.py`.
- [x] Update persistence functions in `backend/app/db/repository.py`.

### Step 5.2: Bounded Video Asset Ingestion Adapters [COMPLETED]
- [x] Implement `NASAVideoAdapter` querying `images-api.nasa.gov` with asset collection manifest resolution.
- [x] Implement `WikimediaVideoAdapter` querying `commons.wikimedia.org` API with filetype filtering.
- [x] Enforce strict streaming download guardrails: max 35 MB, 10s connect/read timeouts, on-the-fly SHA-256 calculation.
- [x] Enforce license whitelists (Public Domain, CC0, CC-BY, CC-BY-SA; reject NC, ND, proprietary copyright claims).
- [x] Implement `probe_video_metadata` via `ffprobe` for stream dimensions, codecs, and durations.

### Step 5.3: Vertical 9:16 Video Reframing & Crop Anchors [COMPLETED]
- [x] Implement `VideoReframer` in `backend/app/media/reframing.py`.
- [x] Deterministic 1080x1920 30fps H.264 video conversion with configurable anchors (`center`, `top`, `bottom`).
- [x] Strip original audio tracks (`-an`) and handle loop/trim logic cleanly.

### Step 5.4: Scene-Aware Visual Selector & Fallback Engine [COMPLETED]
- [x] Implement `SceneVisualSelector` in `backend/app/media/visual_selector.py`.
- [x] Classify narrative beats into `VIDEO` (observational/space footage) vs `PROCEDURAL` (formulas, NIST measurements) vs `IMAGE_KEN_BURNS`.
- [x] Fail-closed fallback: video retrieval or reframing failures gracefully degrade to procedural infographics or Ken Burns stills without crashing.

### Step 5.5: FFmpeg Composer Transitions with Duration Preservation [COMPLETED]
- [x] Implement duration-preserving `xfade` cross-dissolves (default 0.5s) in `backend/app/media/ffmpeg_composer.py`.
- [x] Solve video shrinkage via clip handle extensions ($D_i + T$) so video duration exactly equals speech narration and subtitles with zero drift.
- [x] Add safety gate: scenes shorter than $2 \times T$ fall back to clean jump cuts (`concat`) to avoid filtergraph clipping.

### Step 5.6: Worker Integration, Benchmarks & Verification [COMPLETED]
- [x] Integrate `SceneVisualSelector` and `enable_transitions` into `WorkerRunner.process_render_project`.
- [x] Expose `enable_video_ingest` and `enable_transitions` on `/projects/{project_id}/render` API and Next.js frontend.
- [x] Add 9 comprehensive automated tests in `backend/tests/test_stage5_hybrid_engine.py`.
- [x] Run full test suite: **75 tests passing with 0 failures**.
- [x] Execute controlled benchmark comparing Track A (Ken Burns Baseline) vs Track B (Hybrid Video + Infographics + xfade transitions).
- [x] Build static frontend export (`npm run build`).
- [x] Authored `docs/STAGE_5_IMPLEMENTATION_REPORT.md`.

---

## Stage 6: Secure YouTube OAuth and Private Upload [COMPLETED]

### Step 6.1: Security & Restricted Secret Storage [COMPLETED]
- [x] Implement permission-restricted local secret storage (`backend/app/publishing/secrets.py`) with `0600` file permissions and `0700` directory permissions.
- [x] Add `data/secrets/`, `client_secret*.json`, and `*.secret*` to `.gitignore`.
- [x] Enforce secret redaction in all API responses and logs.
- [x] Support environment variable fallbacks (`YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`).

### Step 6.2: Google OAuth 2.0 Web-Server Flow [COMPLETED]
- [x] Implement `YouTubeOAuthManager` in `backend/app/publishing/youtube_oauth.py`.
- [x] Required scope: `https://www.googleapis.com/auth/youtube.upload` (and `readonly` for channel identity).
- [x] Validate OAuth `state` to prevent CSRF with single-use consumption and expiration in `oauth_states` table.
- [x] Request offline access (`access_type="offline"`, `prompt="consent"`) to guarantee refresh token acquisition.
- [x] Automatic token refresh using refresh token when access token expires.
- [x] Token revocation and disconnection handling.

### Step 6.3: Guarded Private Upload Workflow [COMPLETED]
- [x] Implement `YouTubeUploader` in `backend/app/publishing/youtube_uploader.py`.
- [x] Verify render completed with `qa_status == 'PASSED'`.
- [x] Re-calculate on-disk SHA-256 and verify exact match with immutable render record.
- [x] Verify active, non-superseded human approval matching exact checksum.
- [x] Enforce database trigger `enforce_valid_approval_before_publish` on `publish_attempts` table.
- [x] Strict Publishing Boundary: Enforce initial uploads must be strictly **`private`**; non-private requests rejected.
- [x] Automatic source attribution ledger appended to description.
- [x] Resumable chunked upload (`MediaFileUpload` with `resumable=True`) with exponential backoff on 5xx errors.
- [x] Quota error detection (`quotaExceeded` / 403) and expired credential detection with clean database status updates.
- [x] Idempotency: Duplicate upload requests for the same approved render return confirmed video ID without re-uploading.

### Step 6.4: UI & State Management [COMPLETED]
- [x] Add YouTube OAuth Connection Status card in Next.js dashboard.
- [x] Client configuration modal for entering Google Client ID & Secret securely.
- [x] Guarded upload form showing checksum approval badge, metadata fields, and private upload button.
- [x] Success banner linking to private video in YouTube Studio (`https://youtu.be/{videoId}`).
- [x] Build and export static frontend (`npm run build`).

### Step 6.5: Automated Testing & Verification [COMPLETED]
- [x] Add 9 comprehensive mocked automated tests in `backend/tests/test_stage6_youtube_publishing.py`.
- [x] Test OAuth state CSRF validation, secret redaction, approval missing/superseded, checksum mismatch, resumable retry, quota exceeded, idempotency, and private upload enforcement.
- [x] Full test suite passing: **84 passed across all 10 test modules**.
- [x] Authored `docs/STAGE_6_IMPLEMENTATION_REPORT.md`.
- [ ] **STOP & REPORT GOOGLE CLOUD MANUAL SETUP STEPS** before any live channel upload.

---

## Track 1 & Quality Remediation: Real Footage Verification & Zero Silent Fallbacks [COMPLETED]

### Step 7.1: Flow Handoff & Generation Protocol Audit [COMPLETED]
- [x] Audit entire asset path from Google Flow prompt package generation to final FFmpeg render.
- [x] Prove conclusively whether subscription credits (Google AI Pro via Jio) are programmatically consumed (Zero consumed; manual web-interface handoff).
- [x] Detect and expose silent fallback vulnerabilities (synthetic fractals, solid colors, procedural gradients masking missing footage).

### Step 7.2: Fail-Closed Asset Pipeline Hardening [COMPLETED]
- [x] Schema & Domain Migration: Introduce `visual_source_type` (`FLOW_REQUIRED`, `FLOW_GENERATED`, `CURATED_STOCK`, `EXPLICIT_FALLBACK`, `USER_UPLOAD`).
- [x] Enforce Fail-Closed Render Invariant: Missing required footage raises immediate `400 Bad Request` in API pre-flight and `RuntimeError` in worker unless `allow_placeholder_fallback=True` is explicitly passed.
- [x] SHA-256 Provenance & Manifest Ledger: Compute SHA-256 for every single frame-supplying asset on disk before rendering, recording into `renders.recipe_json.asset_manifest`.
- [x] Invalidation on Ingestion: Binding new footage drops project status to `STORYBOARD` and supersedes previous approvals.
- [x] Frontend UI: Add Google Flow prompt package modal, copy buttons, and scene video import picker with manual user confirmation.

### Step 7.3: Automated Testing & Verification [COMPLETED]
- [x] Add 3 exhaustive regression tests in `backend/tests/test_flow_handoff.py` validating fail-closed missing footage, explicit fallback tagging, and real imported footage precedence.
- [x] Fix silent loudnorm crash on pure silence tracks by adding graceful direct audio pass-through.
- [x] Full test suite verification: **102 passed, 1 warning across all 14 test modules**.
- [x] Clean frontend static build verification (`npm run build`).

---

## Phase 5: Social Publishing & Keyring Credentials

- [ ] Store OAuth credentials in OS Keyring (KDE Wallet).
- [ ] YouTube Data API v3 publisher adapter (private test uploads only).
- [ ] Outbox pattern with reconciliation for uncertain network timeouts.
- [ ] Synthetic content disclosure flag enabled by default.
- [ ] Instagram Reels adapter deferred to post-audit.

---

## Phase 6: Analytics, Experiments & Adaptive Planning (Deferred)

- [ ] Metric snapshot collectors (YouTube Analytics API).
- [ ] Controlled experiment runner (single-variable comparison).
- [ ] Statistical significance and shrinkage model (flag datasets < 20 posts as anecdotal).
- [ ] Phase 6 deferred until publishing volume and audience data exist.
