# Implementation Report: Google Flow Handoff and Ingestion (Track 1)

**Document Version:** 1.0.0  
**Date:** October 25, 2026  
**Status:** Verification & Testing Complete — Ready for Review  
**Git Branch:** `stage-5-hybrid-video` (Preserved intact; zero commits or pushes)  
**Deliverable Type:** Core System Architecture & Ingestion Subsystem  

---

## 1. Executive Summary & Core Objective

The purpose of Track 1 is to bridge our automated AI video orchestration platform with **Google AI Pro benefits obtained through Jio** without violating Google Terms of Service, introducing fragile reverse-engineered web-scraping bots, or incurring commercial cloud API costs.

Because consumer Google AI Pro entitlements provide access exclusively through Google Flow's web interface (`labs.google/flow`) and do not grant programmatic Vertex AI service accounts, we built a robust, deterministic **Flow Handoff and Ingestion Pipeline**:
1. **Agent Handoff:** Generates per-scene 9:16 prompt packages with narrative intent, exact prompts, duration, camera motion verbs, continuity rules, and negative constraints.
2. **Durable Export:** Exports durable machine-readable JSON manifests and one-click copyable text files.
3. **Rigorous Ingestion Gate:** An automated inbox watcher and explicit file importer that decodes, audits, samples frames, detects corrupt/blank/frozen media, validates aspect ratio, computes SHA-256 hashes, logs provenance, and creates review previews.
4. **Approval Safety Invariant:** Enforces explicit user confirmation (never matching by loose filename alone) and automatically supersedes any existing render approvals whenever a scene visual is imported.

---

## 2. Modified & Created Files

| File | Type | Purpose |
| :--- | :--- | :--- |
| [`backend/app/media/flow_handoff.py`](file:///home/naveenr/Documents/AI_video_agent/backend/app/media/flow_handoff.py) | Created | Generates per-scene `FlowPromptPackage` and durable `FlowManifest` export. |
| [`backend/app/media/flow_ingestion.py`](file:///home/naveenr/Documents/AI_video_agent/backend/app/media/flow_ingestion.py) | Created | Multi-stage technical validation, frame sampling (blank/frozen/corrupt detection), SHA-256 hashing, immutable storage, preview generation, and scene binding. |
| [`backend/app/api/main.py`](file:///home/naveenr/Documents/AI_video_agent/backend/app/api/main.py) | Modified | Added `/projects/{id}/flow-prompts`, `/inbox/files`, `/projects/{id}/scenes/{scene_id}/bind-inbox-file`, and direct binary upload route `/projects/{id}/scenes/{scene_id}/import-flow-video`. |
| [`frontend/src/app/page.tsx`](file:///home/naveenr/Documents/AI_video_agent/frontend/src/app/page.tsx) | Modified | Added interactive Google Flow Prompts modal, one-click prompt copying, and per-scene "Import Flow Video" controls. |
| [`backend/tests/test_flow_handoff.py`](file:///home/naveenr/Documents/AI_video_agent/backend/tests/test_flow_handoff.py) | Created | 9 comprehensive automated tests verifying prompt export, validation rules, blank/frozen detection, horizontal video warnings, approval invalidation, and inbox API routes. |
| [`data/run_flow_handoff_sample.py`](file:///home/naveenr/Documents/AI_video_agent/data/run_flow_handoff_sample.py) | Created | Automated benchmark generator testing full end-to-end Flow video import, validation, audio mixing, and 1080x1920 video rendering. |

---

## 3. Technical Implementation Details

### A. Prompt Package Architecture ([`flow_handoff.py`](file:///home/naveenr/Documents/AI_video_agent/backend/app/media/flow_handoff.py))
Each scene generates a `FlowPromptPackage` containing:
- `scene_id` & `scene_index`: Deterministic scene coordinates.
- `narrative_intent`: Contextual goal derived from the narrative archetype (e.g. *Hook*, *Mechanism*, *Climax*, *Resolution*).
- `exact_prompt`: Highly descriptive visual descriptor adhering to Veo guidelines:
  - Explicit vertical framing: `Vertical 9:16 cinematic video. ...`
  - Atmospheric lighting and physical texture directives (`volumetric atmospheric lighting`, `photorealistic 8k`, `detailed physical textures`).
  - Active camera motion verbs (`Dynamic slow push-in`, `smooth lateral tracking shot`).
- `aspect_ratio`: "9:16" (Shorts/Reels standard).
- `requested_duration`: "4s" or "8s" (matching native Google Flow web UI presets).
- `motion_camera_direction`: Dedicated motion guidance for the user.
- `continuity_constraints`: Color grading and visual tone alignment.
- `forbidden_artifacts`: Strict negative prompt (`no text, no subtitles, no watermarks, no logos, no 16:9 letterbox, no 2D cartoon, no blur`).
- `technical_notes`: Clear disclosure stating that Flow web interface controls must be toggled manually by the user.

### B. Multi-Stage Validation & Frame Sampling ([`flow_ingestion.py`](file:///home/naveenr/Documents/AI_video_agent/backend/app/media/flow_ingestion.py))
Before any user-provided MP4 is bound to a scene, it passes through 8 strict validation gates:
1. **Decodability Gate:** `ffprobe` extracts streams, container format, bit rate, codecs, and durations.
2. **Decode Integrity Gate:** Full decoding test pass (`ffmpeg -v error -i ... -f null -`) to catch corrupt packets or bitstream truncation.
3. **Usable Duration Gate:** Minimum 1.0s duration; flags `REVIEW_REQUIRED` if shorter than target scene duration.
4. **Frame Activity Sampling:** Samples 5 frames across the timeline (10%, 30%, 50%, 70%, 90% timestamps) into raw grayscale pixel buffers:
   - **Blank Media Detection:** Checks if mean luminosity is pure black (<2.5) or pure white (>252.5) with standard deviation <2.0.
   - **Frozen Frame Detection:** Calculates mean absolute difference between adjacent sampled frames. If difference is <0.2 across all pairs, video is flagged as frozen/stuck generator output and `REJECTED`.
   - **Test Pattern Detection:** Flags low-entropy frames (standard deviation <1.5).
5. **Aspect Ratio & Resolution Audit:** Measures exact source width and height. If aspect ratio is not vertical 9:16 (0.52 to 0.60), marks status as `REVIEW_REQUIRED` and warns the user that post-processing will reframe/crop.
6. **Honest Source Attribution:** Explicitly distinguishes source properties (e.g., `Measured source: 720x1280 @ 24fps (h264)`) from post-processing targets (`1080x1920 @ 30fps`).
7. **SHA-256 Hashing & Immutable Copy:** Copies the asset to `data/media/projects/{project_id}/flow_imports/flow_{sha[:16]}_{clean_name}.mp4`.
8. **Thumbnail Generation:** Extracts preview thumbnail at the 50% timestamp to `previews/preview_scene_{idx}_{sha[:12]}.jpg`.

### C. Approval Invalidation & Governance
In strict accordance with ADR-02 and ADR-04:
- When `import_and_bind_flow_video` completes, any existing render approval for the project is immediately marked `superseded_at = CURRENT_TIMESTAMP`.
- The project status reverts from `APPROVED` or `FAILED` to `STORYBOARD`.
- `current_render_id` is set to `NULL`, forcing a full re-render and re-approval before publishing can occur.

---

## 4. Test Evidence & Verification Results

All 9 dedicated tests in [`backend/tests/test_flow_handoff.py`](file:///home/naveenr/Documents/AI_video_agent/backend/tests/test_flow_handoff.py) passed:

```
backend/tests/test_flow_handoff.py::test_flow_prompt_generation_and_export PASSED
backend/tests/test_flow_handoff.py::test_validate_flow_video_valid_9_16 PASSED
backend/tests/test_flow_handoff.py::test_validate_flow_video_detects_blank_media PASSED
backend/tests/test_flow_handoff.py::test_validate_flow_video_detects_frozen_frames PASSED
backend/tests/test_flow_handoff.py::test_validate_flow_video_flags_non_9_16_horizontal PASSED
backend/tests/test_flow_handoff.py::test_validate_flow_video_rejects_too_short PASSED
backend/tests/test_flow_handoff.py::test_import_and_bind_flow_video_enforces_user_confirmation PASSED
backend/tests/test_flow_handoff.py::test_import_and_bind_flow_video_invalidates_prior_approvals PASSED
backend/tests/test_flow_handoff.py::test_inbox_api_endpoints PASSED
```

---

## 5. Actual Sample Output & Benchmark Measurements

Generated using [`data/run_flow_handoff_sample.py`](file:///home/naveenr/Documents/AI_video_agent/data/run_flow_handoff_sample.py):
- **Project Topic:** "What Really Happens Inside a Black Hole?"
- **Project ID:** `85b17fdf-259f-4345-b854-cfa1424e2dde`
- **Flow Prompt Manifest:** [`data/media/projects/85b17fdf-259f-4345-b854-cfa1424e2dde/flow_prompts/flow_manifest.json`](file:///home/naveenr/Documents/AI_video_agent/data/media/projects/85b17fdf-259f-4345-b854-cfa1424e2dde/flow_prompts/flow_manifest.json)
- **Imported Flow Fixture:** [`data/media/projects/85b17fdf-259f-4345-b854-cfa1424e2dde/flow_imports/flow_dac7c9ae1aa4658c_flow_black_hole_event_horizon.mp4`](file:///home/naveenr/Documents/AI_video_agent/data/media/projects/85b17fdf-259f-4345-b854-cfa1424e2dde/flow_imports/flow_dac7c9ae1aa4658c_flow_black_hole_event_horizon.mp4)
- **Render Output:** [`data/media/projects/85b17fdf-259f-4345-b854-cfa1424e2dde/final_render_flow_handoff.mp4`](file:///home/naveenr/Documents/AI_video_agent/data/media/projects/85b17fdf-259f-4345-b854-cfa1424e2dde/final_render_flow_handoff.mp4)
- **Render Checksum (SHA-256):** `42c52638d653e51c255c830743d139c4fdbbeef3eea3f0f564bd7147cade9bec`
- **Output File Size:** 7,697,042 bytes (7.34 MB)
- **Measured Duration:** 17.967s (Target: 18.0s)
- **Resolution & Frame Rate:** 1080x1920 @ 30fps vertical MP4
- **Audio Loudness:** -15.4 LUFS (EBU R128 compliant), True Peak: -0.6 dBTP

---

## 6. Honest Identification of the Live Handoff Step

To generate video using your Jio entitlement today:
1. Open the project in the web dashboard and click **"✨ Google Flow Prompts"**.
2. Click **"Copy Prompt"** on Scene 1 (or any scene).
3. In your web browser, navigate to **Google Flow** (`labs.google/flow`) logged in with your Jio-provided Google AI Pro account.
4. Paste the prompt, set Aspect Ratio to **9:16**, set duration to **4s** or **8s**, and click Generate.
5. Download the resulting `.mp4` from Google Flow.
6. Either:
   - Drag & drop or upload the file on the Scene Card via **"📥 Import Flow Video (.mp4)"**, OR
   - Move the file to `data/inbox/` and select it from the inbox file dropdown.
7. The system automatically audits the video, computes the SHA-256 hash, generates a preview, binds it to the scene, and resets the approval gate so you can render your Short.

---

## 7. Rollback Instructions

If rollback is needed:
1. Delete `backend/app/media/flow_handoff.py` and `backend/app/media/flow_ingestion.py`.
2. Remove the Flow routes in `backend/app/api/main.py`.
3. In `frontend/src/app/page.tsx`, revert the Flow Prompts modal and button changes.
4. Delete test file `backend/tests/test_flow_handoff.py`.
5. Run `.venv/bin/pytest backend/tests/` to confirm baseline test suite passes.
