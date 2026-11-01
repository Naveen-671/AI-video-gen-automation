# Phase 2A Component Evaluation: Video Production Pipeline

**Evaluation Date:** 2026-10-20  
**Target Environment:** Fedora Linux 44, AMD Ryzen 5 8645HS, NVIDIA RTX 3050 (6 GB VRAM), 14 GiB RAM, Python 3.14.6  
**Guiding Principle:** Minimal dependencies, zero external network costs, zero unapproved model downloads, standard-library/installed tool reuse.

---

## 1. Composition & Video Rendering Libraries

### Candidate A: Direct FFmpeg CLI via Python `subprocess` (RECOMMENDED & SELECTED)
- **Repository & License:** [FFmpeg/FFmpeg](https://github.com/FFmpeg/FFmpeg) · LGPL-2.1+ / GPL-2.0+ (Installed binary: FFmpeg 8.1.2 RPM Fusion full build, GPL-2.0+).
- **Capabilities:**
  - Deterministic vertical 9:16 composition (720×1280 or 1080×1920).
  - High-performance scaling and letterboxing/cropping filterchains (`scale`, `pad`, `crop`).
  - Dynamic Ken Burns pan/zoom motion on still images (`zoompan`).
  - Native ASS/SRT caption burning via `libass` and `libfreetype` (already verified present in host binary).
  - Audio concatenation, loudness adjustment, and ducking (`amix`, `volume`, `sidechaincompress`).
  - Software H.264 (`libx264`) and AAC (`aac`) CPU encoding, with optional hardware acceleration (`h264_nvenc`).
- **Python 3.14 Compatibility:** 100%. Uses standard library `subprocess.run(args, ...)` with sanitized argument lists. Requires zero third-party Python packages.
- **Resource Footprint:** 
  - RAM: ~150–350 MB per CPU encode process.
  - VRAM: 0 MB in CPU mode (`libx264`).
  - Disk: 0 MB additional disk space (reuses host system binary).
- **Offline & Cost:** 100% offline, zero recurring costs, no external services.
- **Verdict:** **Selected baseline**. Cleanest, most predictable, and least memory-intensive path. Avoids abstraction layer memory leaks.

### Candidate B: MoviePy (v1 / v2)
- **Repository & License:** [Zulko/moviepy](https://github.com/Zulko/moviepy) · MIT License.
- **Capabilities:** Pythonic API wrapping FFmpeg via pipes.
- **Python 3.14 Compatibility:** Fragile. MoviePy v1 relies on older `imageio`, `proglog`, and `decorator` packages with deprecation warnings and wheel build friction on Python 3.14.
- **Resource Footprint:** High RAM overhead. MoviePy buffers video frames as uncompressed NumPy arrays in Python process memory, causing severe RAM pressure and potential OOM on a 14 GiB host.
- **Verdict:** **Rejected**. Direct FFmpeg filtergraphs are faster, safer, and consume a fraction of the memory.

---

## 2. Text-to-Speech (TTS) Narration Options

### Candidate A: Manual Audio & Silent Modes (SELECTED FOR PHASE 2A)
- **Implementation:** Custom lightweight adapter accepting user-uploaded WAV/MP3 files (`manual_audio`) or producing silent timing tracks (`silent`).
- **Python 3.14 Compatibility:** 100% native (standard library or FFmpeg `anullsrc`).
- **Model Weights:** None.
- **Cost & Dependencies:** Zero.
- **Verdict:** **Selected for Phase 2A**. Allows complete pipeline testing without premature model downloads or unverified AI audio claims.

### Candidate B: Kokoro-82M via `kokoro-onnx` (PROPOSED FOR PHASE 2B/3)
- **Repository & License:** [hexgrad/Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) (Apache-2.0) · [thewh1teagle/kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx) (MIT, transitive phonemizer GPL-3.0).
- **Capabilities:** 82M parameter lightweight text-to-speech model supporting English, Hindi, Spanish, French, Italian, Portuguese, Japanese, and Mandarin. Real-time CPU inference.
- **Python 3.14 Compatibility:** Requires verification of `onnxruntime` wheels on Python 3.14 Linux x86_64.
- **Resource Footprint:** ~300 MB model download; ~500 MB RAM; runs on CPU with 0 VRAM usage.
- **Offline & Cost:** 100% offline once weights are saved locally. Zero recurring cost.
- **Verdict:** **Strongest candidate for local neural TTS**. Deferred to Phase 2B/3 pending model download approval and wheel verification.

### Candidate C: Piper TTS
- **Repository & License:** [rhasspy/piper](https://github.com/rhasspy/piper) · MIT License.
- **Capabilities:** Ultra-fast local neural TTS on CPU. Large catalog of community voices, including regional Indian voices.
- **Python 3.14 Compatibility:** Standalone C++ binary available; Python package has onnxruntime dependency.
- **Resource Footprint:** Models are 50–150 MB each; low RAM.
- **Verdict:** Secondary candidate for extended regional language support.

---

## 3. Visual Assets & Background Generation

### Candidate A: Local SVG / Canvas & User Image Ingest (SELECTED FOR PHASE 2A)
- **Implementation:** 
  1. Default visual generator creates crisp 720×1280 styled SVG / PNG gradient backdrops with scene typography using standard library and FFmpeg image sources.
  2. Asset upload endpoint (`POST /projects/{id}/assets`) allows users to replace any placeholder with their own JPG/PNG images.
- **Capabilities:** Zero-cost, instant, reliable 9:16 vertical frames.
- **Python 3.14 Compatibility:** 100%.
- **Resource Footprint:** Negligible (<10 MB RAM, 0 VRAM).
- **Verdict:** **Selected for Phase 2A**. Provides a complete visual baseline immediately with zero external dependencies.

### Candidate B: Local Stable Diffusion / Diffusers
- **Repository & License:** Stability AI / Black Forest Labs.
- **Resource Footprint:** 4–12 GB VRAM; multi-gigabyte weight downloads. High OOM risk on RTX 3050 Laptop GPU (6 GB VRAM).
- **Verdict:** **Deferred to Phase 4 benchmark harness**. Must not be introduced in core pipeline without strict benchmark gates.

---

## 4. Subtitle & Caption Rendering

### Candidate A: SubStation Alpha (ASS) / SRT via FFmpeg `libass` (SELECTED)
- **Capabilities:** Word-level and scene-level timed captions with custom font family, font size, primary color, outline, shadow, and margin alignment (top/bottom safety margin enforcement).
- **Implementation:** Python generator outputs an ASS script file; FFmpeg burns it using `-vf "subtitles=caption.ass"`.
- **Python 3.14 Compatibility:** 100% (built using standard Python file writing).
- **Resource Footprint:** Negligible.
- **Verdict:** **Selected**. High aesthetic control, exact timing, zero extra libraries.

---

## 5. Summary Recommendation for Phase 2A

| Subsystem | Selected Component | Dependencies | Weights Downloaded |
| :--- | :--- | :--- | :--- |
| **Scripting** | Deterministic Pydantic Mock/Template Adapter | Standard Library | None |
| **Visual Assets** | Local SVG/Gradient Generator + User Uploads | Standard Library + FFmpeg | None |
| **Narration** | `manual_audio` & `silent` Adapters | FFmpeg / Audio Ingest | None |
| **Subtitles** | Structured ASS / SRT Generator | Standard Library | None |
| **Composition** | Direct FFmpeg CLI via `subprocess` | System FFmpeg 8.1.2 | None |
| **Quality Checks** | Direct `ffprobe` CLI via `subprocess` | System FFprobe 8.1.2 | None |

This minimal stack accomplishes 100% of the Phase 2A objectives while preserving zero added cost, zero model downloads, zero GPU overload, and complete Python 3.14 compatibility.
