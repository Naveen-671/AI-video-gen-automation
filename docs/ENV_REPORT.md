# Environment Inspection Report: AI Shorts & Reels Factory

**Inspection Timestamp:** 2026-10-20T19:31:31+05:30  
**Host Machine:** Fedora Linux 44 (KDE Plasma Desktop Edition)  
**Kernel:** `7.1.8-200.fc44.x86_64`  
**Working Directory:** `/home/naveenr/Documents/AI_video_agent`

---

## 1. Hardware Inspection

| Resource | Detected Specification | Operating Headroom | Status & Feasibility |
| :--- | :--- | :--- | :--- |
| **CPU** | AMD Ryzen 5 8645HS w/ Radeon 760M Graphics (6 physical cores, 12 threads, boost up to 5.0 GHz, AVX-512) | 12 threads available | **Optimal**: Excellent CPU performance for ONNX CPU audio synthesis, rule-based QA, and FFmpeg filtergraphs. |
| **GPU / VRAM** | NVIDIA GeForce RTX 3050 Laptop GPU (6144 MiB / 6.0 GiB VRAM), Driver: `610.57.04`, CUDA UMD: `13.3` | Current VRAM usage: **39 MiB** (KWin Wayland: 6 MiB). Free: ~6.1 GiB | **Tight for Heavy Video**: 6 GB VRAM confirms the spec verdict that local diffusion video models (e.g. Wan 1.3B/5B, LTX-Video) are high-risk. Enforces **strict 1 GPU job at a time** and confirms FFmpeg stills+motion as primary baseline. |
| **System RAM** | **14 GiB Total**<br>Used: 8.4 GiB, Free: 945 MiB, Buff/Cache: 6.0 GiB, **Available: 6.4 GiB**<br>Swap: 8.0 GiB (1.5 GiB used, 6.5 GiB free) | Available: ~6.4 GiB | **Manageable with Caution**: Avoid running unnecessary background daemons. Validates the decision to serve the Next.js UI as a **static export** from FastAPI to avoid a persistent Node.js runtime (~1–1.5 GiB RAM saved). |
| **Storage / Disk** | NVMe partition `/dev/nvme0n1p6` mounted on `/` and `/home`<br>Total: 111 GB, Used: 65 GB (60%), **Available: 45 GB** | Free: **45 GB** | **Sufficient under Strict Budget**: Fits the projected disk budget: App + venv (3–5 GB), Media cache (capped at 15 GB), Models (capped at 12 GB if approved later), System safety buffer (≥10 GB). |

---

## 2. Tooling & Runtimes

| Tool | Detected Version | Path | Assessment |
| :--- | :--- | :--- | :--- |
| **Python** | `Python 3.14.6` | `/usr/bin/python3` | System Python 3.14 is present. `python3 -m venv` is available. We will create a local `.venv` inside the project to strictly isolate dependencies. |
| **uv** | *Not installed* | N/A | We will use standard `python3 -m venv` and `pip` inside the project-local `.venv`. No need to modify system packages. |
| **Node.js** | `v22.23.1` | `/usr/bin/node` | Node LTS available for building Next.js static exports (`npm run build`). |
| **npm** | `10.9.8` | `/usr/bin/npm` | Modern package manager available for frontend dependencies. |
| **Git** | `git version 2.55.0` | `/usr/bin/git` | Available. Workspace is not yet initialized as a git repository. |
| **FFmpeg** | `ffmpeg version 8.1.2` (built with gcc 16, RPM Fusion full build) | `/usr/bin/ffmpeg` | **EXCELLENT FINDING**: Native hardware NVENC (`h264_nvenc`, `hevc_nvenc`, `av1_nvenc`) AND software encoders (`libx264`, `libx264rgb`, `aac`, `libfdk_aac`, `libass`, `libplacebo`, `libfreetype`, `libvmaf`) are **already installed and enabled**. |
| **ffprobe** | `ffprobe version 8.1.2` | `/usr/bin/ffprobe` | Available for technical QA validation (resolution, audio channels, duration, bitrates). |

---

## 3. Codec & FFmpeg Capabilities Analysis

Initial spec concerns noted that Fedora's standard `ffmpeg-free` build often lacks H.264/AAC.  
Our inspection reveals that this system has **FFmpeg 8.1.2** with full RPM Fusion configuration:
- `libx264`: Available (H.264 CPU software encoding)
- `h264_nvenc`: Available (NVIDIA hardware-accelerated H.264 encoding for fast draft renders)
- `hevc_nvenc` & `av1_nvenc`: Available (hardware H.265 and AV1 encoding)
- `aac` & `libfdk_aac`: Available (high quality stereo AAC audio encoding)
- `libass` & `libfreetype`: Available (caption styling and SSA/ASS subtitle rendering)

**Verdict:** **No static FFmpeg binary or system dnf changes are required.** The existing system FFmpeg meets 100% of the production requirements for 1080×1920 9:16 Shorts/Reels composition.

---

## 4. Workspace & Filesystem State

- **Current Path:** `/home/naveenr/Documents/AI_video_agent`
- **Existing Files:** Only `.directory` (KDE Plasma file-manager state).
- **Git State:** Clean directory, not yet initialized (`git init` pending approval).
- **Obsidian Memory Check:** Existing note `AutoShorts-Engine.md` in `/home/naveenr/Documents/Obsidian Vault/Claude-AntiGravity/Projects/` confirms a prior TypeScript/Express prototype from earlier in 2026. The new architecture is a clean Python/FastAPI + Next.js static export implementation built to the provided spec.

---

## 5. Resource Safety & Operational Guardrails

1. **VRAM Guardrail:**
   - RTX 3050 has 6144 MiB VRAM.
   - Strict concurrency limit: **Maximum 1 GPU-bound task at any time**.
   - Model downloads are completely deferred until Phase 4 benchmark harness.
2. **RAM Guardrail:**
   - 14 GiB total, ~6.4 GiB available.
   - Worker will poll system memory before executing memory-intensive jobs: **Pause/defer job execution if available RAM drops below 3.0 GiB**.
   - Next.js UI is built to static export (`next export` / `output: 'export'`) and served directly by FastAPI via static mount, eliminating a persistent Node.js server process.
3. **Disk Guardrail:**
   - Available space: 45 GB.
   - Storage cap on `data/media/`: **15 GB** (with LRU retention/cleanup policy).
   - Reserve threshold: Worker halts if available disk drops below **10.0 GB**.
4. **Zero-Cost & Non-destructive Operations:**
   - Zero root/sudo commands.
   - Zero system Python modifications (project-local `.venv` only).
   - Zero paid API endpoints or metered fallbacks.
   - Publisher tokens isolated in OS keyring.

---

## 6. Knowns, Unknowns & Dependencies

### Verified Knowns [V]
- FFmpeg 8.1.2 has full encoder support (`libx264`, `h264_nvenc`, `aac`).
- Python 3.14.6 and Node 22 are available natively.
- Machine has 45 GB free disk space and 6.4 GiB available RAM.
- GPU is an RTX 3050 6 GB VRAM with CUDA 13.3 driver.

### Unknowns & Verification Gates [U]
1. **Python 3.14 Binary Wheels:** Python 3.14 is very recent. We need to verify which dependencies (e.g. `fastapi`, `pydantic`, `alembic`, `aiosqlite`, and later `onnxruntime` or `faster-whisper`) have pre-compiled binary wheels for Python 3.14 on Linux x86_64 or build cleanly without requiring C compiler toolchains.
2. **Google AI Pro / Jio Activation Expiry:** Jio 18-month window validity date and exact remaining Flow credit quota need confirmation from user when convenient.
3. **YouTube API Quota:** 1,600 units per `videos.insert` upload. Unaudited Google Cloud projects are restricted to `private` uploads by default. (Phase 5 gate).
4. **Instagram Graph API Requirements:** Instagram Reels API requires an Instagram Professional account linked to a Facebook Page, and dev-mode app review rules must be verified before live publishing.
