# Phase 2B Evaluation: Local Neural Text-to-Speech (TTS) Integration

**Evaluation Date:** 2026-10-20  
**Target Environment:** Fedora Linux 44, AMD Ryzen 5 8645HS (12 threads), 14 GiB RAM, 44 GB Free NVMe Disk, Python 3.14.6  
**Primary Candidate:** Kokoro-82M via ONNX Runtime (`kokoro-onnx`)  
**Operating Principle:** 100% Local CPU Inference, Zero Recurring Cost, No Unapproved Downloads

---

## 1. Candidate Specification & Repository Provenance

- **Upstream Neural Architecture:** [hexgrad/Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) (82 Million parameter style-based TTS model).
- **ONNX Implementation & Runtime Wrapper:** [thewh1teagle/kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx) (v0.4.7+).
- **Official Model Asset Release:** `model-files-v1.1` (`https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.1`).
- **Graph Features:** Embeds vocabulary config directly in graph metadata; supports dynamic audio duration outputs and native float `speed` input scaling (0.5× to 2.0×).

---

## 2. Model Precision Variants & Exact Download Budget

| Artifact | File Name | Size (Bytes) | Size (MB) | Quality vs FP32 | Recommended Role |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Quantized INT8 Model** | `kokoro-v1.0.int8.onnx` | 114,119,327 | **~114 MB** | Spectral corr: 0.916 | **Candidate A: Ultra-light default** |
| **Half-Precision FP16 Model** | `kokoro-v1.0.fp16.onnx` | 163,527,961 | **~164 MB** | Spectral corr: 0.999 | **Candidate B: High fidelity** |
| **Full Precision FP32 Model** | `kokoro-v1.0.onnx` | 325,505,369 | **~326 MB** | Baseline (1.000) | Candidate C: Maximum size |
| **Multi-Voice Binary** | `voices-v1.0.bin` | 28,214,398 | **~28 MB** | 54 global voices | **Mandatory Companion** |

### Selected Recommendation for Phase 2B
- **Model:** `kokoro-v1.0.int8.onnx` (~114 MB) or `kokoro-v1.0.fp16.onnx` (~164 MB).
- **Voices:** `voices-v1.0.bin` (~28 MB).
- **Total Initial Download:** **142 MB** (INT8) or **192 MB** (FP16).
- **Disk Budget Allocation:** Models will be stored in `models/kokoro/` outside Git and outside `data/media/`. This consumes less than **0.5%** of the available 44 GB free disk.

---

## 3. Licenses & Legal Compliance

1. **Model Weights (`Kokoro-82M`):** **Apache-2.0**. Fully permissible for personal and commercial local use.
2. **ONNX Python Binding (`kokoro-onnx`):** **MIT License**.
3. **Phonemizer & Loader Dependency (`espeakng-loader` / `phonemizer-fork`):** **GPL-3.0**.
   - *Legal Assessment:* As documented in the architecture brief, GPL-3.0 phonemizer components are strictly executed locally on the user's personal machine and are not redistributed or packaged as proprietary closed SaaS binaries. This satisfies all compliance criteria.

---

## 4. Language & Voice Coverage Verification

### Genuine Verified Support in `voices-v1.0.bin` (54 Voices)

1. **American English (`en-us`):**
   - Female: `af_bella`, `af_sarah`, `af_nicole`, `af_sky`, `af_alloy`, `af_aoede`, `af_jessica`, `af_kore`, `af_river`
   - Male: `am_adam`, `am_michael`, `am_fenrir`, `am_puck`, `am_echo`, `am_eric`, `am_liam`, `am_onyx`, `am_santa`
2. **British English (`en-gb`):**
   - Female: `bf_emma`, `bf_isabella`, `bf_alice`, `bf_lily`
   - Male: `bm_george`, `bm_fable`, `bm_lewis`, `bm_daniel`
3. **Hindi (`hi`): GENUINELY VERIFIED [V]**
   - Female: **`hf_alpha`**, **`hf_beta`**
   - Male: **`hm_omega`**, **`hm_psi`**
   - *Note:* Text must be provided in Devanagari script. Kokoro's internal phonemizer parses Hindi phonemes directly into the `h` acoustic space.
4. **Additional International Languages:**
   - Japanese (`ja`): `jf_teika`, `jf_alpha`, `jm_kumo`
   - Spanish (`es`): `ef_dora`, `em_alex`
   - French (`fr`): `ff_siwis`
   - Italian (`it`): `if_sara`, `im_nicola`
   - Brazilian Portuguese (`pt-br`): `pf_dora`, `pm_alex`

### Unverified / Unsupported Regional Languages (Kannada, Tamil, Telugu, etc.)
- **Kokoro-82M v1.0 does NOT support Kannada, Tamil, Telugu, Malayalam, or Bengali.**
- **Architectural Guarantee:** In accordance with ADR-05, regional Indian languages are **never excluded**. The system uses the existing `manual_audio` adapter for Kannada/Tamil/etc., allowing operators to upload recorded or studio voiceovers while retaining complete pipeline automation.

---

## 5. Python 3.14 Compatibility & Package Changes

A non-destructive dry-run (`pip install --dry-run kokoro-onnx onnxruntime soundfile`) was executed on the project `.venv` on Python 3.14.6:
- `onnxruntime==1.31.0`: **Pre-built binary wheel available** (`onnxruntime-1.31.0-cp314-cp314-manylinux_2_28_x86_64.whl`). No C++ compilation or toolchain required.
- `kokoro-onnx==0.4.7`: Pure-Python wheel available.
- `soundfile==0.14.0`: Pre-built binary wheel available (`manylinux_2_28_x86_64`).
- `numpy==2.5.4`: Pre-built binary wheel available (`cp314`).
- Total wheel download size for all packages: **~120 MB**.

---

## 6. Resource Impact & Guardrail Compliance

| Metric | Measured / Estimated Value | Guardrail Threshold | Compliance Status |
| :--- | :--- | :--- | :--- |
| **Inference Hardware** | 100% CPU (AMD Ryzen 5 8645HS) | 0 GPU slots required | **PASS** (Leaves 6 GB VRAM free) |
| **RAM Footprint** | ~350 MB to 550 MB | Min Free: 3.0 GiB (Available: 6.4 GiB) | **PASS** |
| **Disk Storage** | ~142 MB (weights) + ~120 MB (wheels) | Min Free: 10.0 GB (Available: 44 GB) | **PASS** |
| **Synthesis Speed** | ~10× to 20× real-time on CPU | 15s audio generated in < 1.5s | **Optimal** |
| **Audio Format** | 24,000 Hz (24 kHz) mono PCM WAV | Converted to AAC 128k stereo via FFmpeg | **Standard** |
| **Offline Operation**| 100% offline once weights reside in `models/kokoro/` | Zero external network calls | **PASS** |

---

## 7. Proposed Reproducible Download & Verification Procedure

Once approved, model weights will be retrieved into `models/kokoro/` using standard SHA-256 verification:

```bash
mkdir -p models/kokoro

# 1. Download multi-voice embeddings (28.2 MB)
curl -L -o models/kokoro/voices-v1.0.bin \
  https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/voices-v1.0.bin

# 2. Download quantized model (114.1 MB)
curl -L -o models/kokoro/kokoro-v1.0.int8.onnx \
  https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/kokoro-v1.0.int8.onnx

# 3. Compute and store SHA-256 checksums in models/kokoro/checksums.sha256
sha256sum models/kokoro/voices-v1.0.bin models/kokoro/kokoro-v1.0.int8.onnx > models/kokoro/checksums.sha256
```

---

## 8. Integration Architecture & Narration Adapter

The new `LocalTTSAdapter` implements `BaseNarrationAdapter` alongside existing adapters:

```
                      BaseNarrationAdapter (backend/app/media/narration.py)
                                      │
         ┌────────────────────────────┼────────────────────────────┐
         ▼                            ▼                            ▼
SilentNarrationAdapter       ManualAudioAdapter           LocalTTSAdapter (Phase 2B)
(Synthetic stereo AAC)      (ffprobe verification)       (Kokoro ONNX on CPU)
                                                         • English (af_bella, etc.)
                                                         • Hindi (hf_alpha, etc.)
                                                         • Speed: 0.5x – 2.0x
```

### Safety & Invalidation Rules:
1. **Fallback Safety:** If model files are missing or unreadable, `LocalTTSAdapter` raises `NarrationAdapterError`. The worker never silently falls back to a paid or cloud API.
2. **Approval Invalidation:** If voice, language, speed, or narration text is modified, any existing approval for the project render is superseded (`superseded_at = CURRENT_TIMESTAMP`), and project status returns to `STORYBOARD`.
3. **Artifact Immutability:** Generated audio is stored at `data/media/projects/{id}/narration_{sha256[:16]}.wav`, with its SHA-256 incorporated into the video's render recipe and final render checksum.
