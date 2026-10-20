# Architecture Decision Register (ADR): AI Shorts & Reels Factory

This document tracks all foundational architecture, infrastructure, cost, and security decisions for the project.

---

## Decision Index

| # | Decision Topic | Status | Recommended Default | Rationale | Approval Required |
| :-: | :--- | :---: | :--- | :--- | :-: |
| **1** | Default visual strategy | **PROPOSED** | Stills plus Ken Burns motion in FFmpeg; local diffusion or Flow clips optional | The only path guaranteed to operate reliably within 6 GB VRAM and zero recurring cost. | **YES** |
| **2** | Flow integration | **PROPOSED** | Manual-ingest inbox (`data/inbox/`), zero UI automation | UI automation violates platform terms, is brittle, and Flow credits expire. Manual ingest is safe and transparent. | **YES** |
| **3** | Frontend delivery | **PROPOSED** | Next.js static export (`output: 'export'`) served by FastAPI on `127.0.0.1` | Eliminates a persistent Node.js runtime, saving ~1–1.5 GiB RAM on a 14 GiB host. | **YES** |
| **4** | LLM planning provider | **PROPOSED** | Structured manual-paste adapter + AI Studio free-tier text key | Strict zero added cost; AI Studio free tier covers text models without billing. | **YES** |
| **5** | Language support & TTS | **PROPOSED** | English + Hindi initial local TTS (Kokoro); Kannada, Tamil, etc. supported via manual audio ingest and pluggable adapters | Kokoro-82M provides high-quality local English & Hindi on CPU. Regional languages are not excluded; manual audio import guarantees full accessibility. | **YES** |
| **6** | TTS Engine | **PROPOSED** | Kokoro-82M via ONNX on CPU | Apache-2.0 core model; real-time synthesis on AMD Ryzen CPU without touching 6 GB GPU VRAM. (Note GPL phonemizer for local use). | **YES** |
| **7** | Caption alignment | **PROPOSED** | Rule-based word-duration timing baseline; optional faster-whisper (small) | Baseline requires no heavy dependencies. Speech alignment can be enhanced once python wheels are verified. | **YES** |
| **8** | Publishing order | **PROPOSED** | YouTube private test uploads first; Instagram Reels deferred to Phase 5 | YouTube private API has lower initial configuration friction than Meta dev-mode review. | **YES** |
| **9** | Test accounts | **PROPOSED** | Dedicated test YouTube channel and dedicated Instagram test account | Protects production brand reputation and prevents accidental public publishing during development. | **YES** |
| **10** | FFmpeg binary source | **CONFIRMED** | Use host FFmpeg 8.1.2 (RPM Fusion build already installed) | Inspection confirmed `libx264`, `h264_nvenc`, and `aac` are natively present. Zero system modifications needed. | **CONFIRMED** |
| **11** | Resource guardrails | **PROPOSED** | 10 GB min free disk, 3 GiB min free RAM, 15 GB media cache, 12 GB model cap, 1 GPU slot | Prevents worker from freezing KDE Plasma or thrashing swap on 14 GiB RAM. | **YES** |
| **12** | Authentication & Binding | **PROPOSED** | Strict `127.0.0.1` bind + CSRF origin check + single-user session token | Local-first personal automation tool; protects endpoints from unauthorized local processes. | **YES** |
| **13** | Python environment | **PROPOSED** | Project-local virtual environment (`.venv`) via `python3 -m venv` | Preserves system Python 3.14 integrity; avoids touching OS packages. | **YES** |
| **14** | Synthetic content disclosure | **PROPOSED** | Enabled by default in publishing metadata | Complies with YouTube and Meta platform synthetic media policies. | **YES** |
| **15** | Quota & Audit Verification | **PROPOSED** | Empirical testing during Phase 5 using private uploads with reconciliation logic | Confirms real-world 1,600 unit quota and tests upload reconciliation without blind retry. | **YES** |

---

## Detailed Records

### ADR-01: Default Visual Pipeline — Stills + Ken Burns Motion
- **Context:** The system GPU is an RTX 3050 Laptop GPU with 6144 MiB VRAM. Diffusion models (Wan 2.1, LTX-Video) require 8+ GB VRAM or heavy quantization/offloading, yielding slow render times (e.g. 5 seconds of 480p taking 4–15+ minutes) and high OOM risk.
- **Decision:** The core production pipeline will generate high-resolution visual stills, compose them with dynamic Ken Burns pan/zoom filtergraphs in FFmpeg, and layer narration, ducked background audio, and animated subtitles. Local diffusion video and Google Flow clips are treated as optional modular enhancements.
- **Consequences:** Rendering is fast, deterministic, and uses negligible VRAM.

### ADR-02: Flow Integration via Manual Ingest Inbox
- **Context:** Google Flow provides 1,000 monthly credits under the Jio AI Pro plan, expiring upon plan conclusion. There is no public, free API for Veo/Flow. Automating consumer web UIs violates terms of service.
- **Decision:** The application provides a watched inbox folder (`data/inbox/`). Users drop manually generated Veo/Flow MP4 clips into this folder. The app detects, hashes, and registers the asset, logging estimated credit consumption (10/20/100 credits) in the manual ledger.
- **Consequences:** No brittle browser macros or reverse-engineered private endpoints. 100% compliance with platform terms.

### ADR-03: Next.js Frontend Delivered as Static Export via FastAPI
- **Context:** The machine has 14 GiB RAM with ~6.4 GiB currently available. Running both a long-running Node.js process (Next.js server) and a FastAPI Python backend consumes unnecessary memory.
- **Decision:** Build the Next.js frontend with `output: 'export'`, compiling all pages and assets into static HTML/JS/CSS (`frontend/out`). FastAPI serves these static files directly on `http://127.0.0.1:8000/`.
- **Consequences:** Saves ~1–1.5 GiB RAM. Single port to access UI and API.

### ADR-04: LLM Planning via Schema-Validated Proposals
- **Context:** Commercial LLM APIs incur recurring costs or risk auto-billing if misconfigured.
- **Decision:** LLM interaction produces Pydantic-validated JSON proposals only. The policy engine evaluates rules and commits state changes. Free tier Google AI Studio keys or manual copy-paste adapters are used. No billing-enabled keys are accepted.
- **Consequences:** Zero financial risk. Strict separation of probabilistic generation from deterministic workflow control.

### ADR-05 & ADR-06: Multilingual Narration & Kokoro-82M TTS
- **Context:** Shorts/Reels need multilingual reach. Kokoro-82M provides lightweight, high-fidelity speech synthesis on CPU for English and Hindi. Regional Indian languages (Kannada, Tamil, Telugu) currently lack lightweight verified open-source local TTS models.
- **Decision:** Implement Kokoro ONNX on CPU for English and Hindi. Provide an immediate `manual_audio` provider for Kannada, Tamil, and other languages, allowing users to upload voiceover recordings or use modular third-party TTS engines as they become available.
- **Consequences:** CPU usage is prioritized for TTS, leaving the GPU free. Full multilingual coverage is guaranteed from day one.

### ADR-08 & ADR-09: Publishing Order & Dedicated Test Accounts
- **Context:** Automated social publishing risks platform shadowbans or quota exhaustion. Unaudited YouTube API credentials default to `private` uploads.
- **Decision:** YouTube private uploads will be implemented first in Phase 5. Instagram Reels is sequenced second. All initial integration runs must target dedicated testing accounts.
- **Consequences:** Eliminates risk to live personal or client social channels.

### ADR-10: Host FFmpeg Encoder Configuration
- **Context:** Initial spec hypothesized that Fedora might lack `libx264` or `nvenc`.
- **Decision:** System inspection confirmed FFmpeg 8.1.2 is installed with `libx264`, `h264_nvenc`, `hevc_nvenc`, `av1_nvenc`, `aac`, `libfdk_aac`, and `libass`. We will use `/usr/bin/ffmpeg` directly.
- **Consequences:** No custom compiling, no static binary downloads, no system changes.

### ADR-11: Hardware Resource Safety Guardrails
- **Context:** Memory leaks or heavy rendering can crash the host desktop session.
- **Decision:** Worker polls system resources before starting any render job:
  - If available RAM < 3.0 GiB: Job pauses until memory clears.
  - If free disk < 10.0 GB: Job pauses and flags human alert.
  - Concurrency: Strictly 1 GPU job at a time.
  - Media cache capped at 15 GB with retention pruning.
- **Consequences:** Protects the host desktop from lockups and swap exhaustion.
