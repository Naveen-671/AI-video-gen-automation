#!/usr/bin/env python3
"""Modular Audio Engine for Curiosity Shorts Pipeline.
Synthesizes Kokoro narration, procedural tactical Foley SFX, and ambient tension bed."""

import sys
import json
import math
from pathlib import Path
import numpy as np
import soundfile as sf

sys.path.insert(0, "/home/naveenr/Documents/AI_video_agent")
from backend.app.media.narration import LocalTTSAdapter

SR = 24000

def generate_sfx_cue(sfx_type: str, duration: float = 1.2) -> np.ndarray:
    """Generate high-impact procedural SFX using mathematical waveforms."""
    n_samples = int(duration * SR)
    t = np.linspace(0, duration, n_samples, endpoint=False)
    audio = np.zeros(n_samples, dtype=np.float32)

    if sfx_type == "pressure_rise":
        # Exponential frequency sweep from 60 Hz to 450 Hz with swell envelope
        f = np.geomspace(60, 450, n_samples)
        phase = 2 * np.pi * np.cumsum(f) / SR
        env = (t / duration) ** 2.2
        audio = 0.6 * np.sin(phase) * env

    elif sfx_type in ("sub_thud", "trap_thud"):
        # 50 Hz deep sub-bass drop with punchy 10ms attack and exponential decay
        f = np.linspace(90, 38, n_samples)
        phase = 2 * np.pi * np.cumsum(f) / SR
        env = np.exp(-t * 4.5)
        audio = 0.8 * np.sin(phase) * env

    elif sfx_type == "eardrum_snap":
        # Sharp high-frequency pop + 3.8 kHz tinnitus ring
        click_len = int(0.015 * SR)
        click = np.random.uniform(-1, 1, click_len) * np.exp(-np.linspace(0, 10, click_len))
        ring = np.sin(2 * np.pi * 3800 * t) * np.exp(-t * 2.0) * 0.25
        audio[:click_len] += click * 0.7
        audio += ring

    elif sfx_type == "tissue_tear":
        # Filtered bursting noise with rapid jitter
        noise = np.random.uniform(-1, 1, n_samples)
        mod = 0.5 + 0.5 * np.sin(2 * np.pi * 35 * t)
        env = np.exp(-t * 3.5) * (t / 0.1).clip(0, 1)
        audio = noise * mod * env * 0.5

    elif sfx_type == "capillary_pop":
        # High-mid pitch sudden transient pop
        pop_samples = int(0.04 * SR)
        t_pop = t[:pop_samples]
        f_pop = np.linspace(950, 120, pop_samples)
        audio[:pop_samples] = np.sin(2 * np.pi * np.cumsum(f_pop) / SR) * np.exp(-t_pop * 60) * 0.7

    elif sfx_type == "heartbeat_climax":
        # Lub-dub low thump
        t1 = 0.12
        t2 = 0.38
        for pulse_t in [t1, t2]:
            idx = int(pulse_t * SR)
            span = int(0.18 * SR)
            if idx + span < n_samples:
                sub_t = t[:span]
                audio[idx:idx+span] += np.sin(2 * np.pi * 48 * sub_t) * np.exp(-sub_t * 18) * 0.85

    elif sfx_type == "needle_buzz":
        # 130 Hz buzzing oscillation with slight harmonics
        audio = (0.5 * np.sin(2 * np.pi * 130 * t) + 0.25 * np.sin(2 * np.pi * 260 * t)) * np.exp(-t * 2.5)

    elif sfx_type == "cell_squish":
        # Wet resonant squelch (FM modulation)
        mod = np.sin(2 * np.pi * 45 * t) * 80
        carrier = np.sin(2 * np.pi * (160 + mod) * t)
        env = np.exp(-t * 3.0)
        audio = carrier * env * 0.55

    elif sfx_type == "laser_shatter":
        # Crystalline laser chirp (3500 Hz down to 600 Hz) + noise burst
        f = np.linspace(3500, 600, n_samples)
        phase = 2 * np.pi * np.cumsum(f) / SR
        noise = np.random.uniform(-1, 1, n_samples) * 0.3
        env = np.exp(-t * 5.0)
        audio = (np.sin(phase) + noise) * env * 0.65

    elif sfx_type == "relief_chime":
        # Soothing harmonic chime (C5, E5, G5)
        chord = (
            0.35 * np.sin(2 * np.pi * 523.25 * t) +
            0.30 * np.sin(2 * np.pi * 659.25 * t) +
            0.25 * np.sin(2 * np.pi * 783.99 * t)
        )
        audio = chord * np.exp(-t * 1.8)

    else:
        # Default gentle whoosh
        noise = np.random.uniform(-1, 1, n_samples)
        audio = noise * np.exp(-t * 3.5) * 0.3

    return audio.astype(np.float32)

def generate_ambient_drone(duration: float) -> np.ndarray:
    """Generate subtle 40Hz - 60Hz clinical sub drone with gentle beating."""
    n_samples = int(duration * SR)
    t = np.linspace(0, duration, n_samples, endpoint=False)
    d1 = 0.5 * np.sin(2 * np.pi * 55.0 * t)
    d2 = 0.3 * np.sin(2 * np.pi * 55.5 * t) # 0.5 Hz gentle beat
    sub = 0.4 * np.sin(2 * np.pi * 38.0 * t)
    drone = (d1 + d2 + sub) * 0.25
    return drone.astype(np.float32)

def build_audio(spec_path: Path):
    with open(spec_path, "r", encoding="utf-8") as f:
        spec = json.load(f)

    project_dir = Path(spec["project_dir"])
    project_dir.mkdir(parents=True, exist_ok=True)
    total_duration = float(spec.get("total_duration", 56.0))
    voice = spec.get("voice", "am_adam")
    speed = float(spec.get("voice_speed", 1.22))

    print(f"Initializing Kokoro TTS adapter for {spec['title']}...")
    adapter = LocalTTSAdapter(
        model_path="/home/naveenr/Documents/AI_video_agent/models/kokoro/kokoro-v1.0.fp16.onnx",
        voices_path="/home/naveenr/Documents/AI_video_agent/models/kokoro/voices-v1.0.bin",
        lazy_load=False
    )
    kokoro = adapter._kokoro

    master_len = int(total_duration * SR)
    voice_track = np.zeros(master_len, dtype=np.float32)
    sfx_track = np.zeros(master_len, dtype=np.float32)

    word_timings = []

    for scene in spec["scenes"]:
        idx = scene["index"]
        text = scene["narration"]
        target_start = float(scene["target_start"])
        sfx_cue = scene.get("sfx")

        # 1. Synthesize Speech
        samples, sr = kokoro.create(text, voice=voice, speed=speed, lang="en-us")
        dur = len(samples) / sr
        print(f"Scene {idx+1} ({scene['name']}): {dur:.2f}s narration, starts at {target_start:.2f}s")

        start_idx = int(target_start * SR)
        end_idx = min(master_len, start_idx + len(samples))
        voice_track[start_idx:end_idx] += samples[:end_idx - start_idx]

        # 2. Add Tactical Foley SFX
        if sfx_cue:
            sfx_dur = 1.2
            sfx_audio = generate_sfx_cue(sfx_cue, duration=sfx_dur)
            sfx_start = max(0, start_idx - int(0.15 * SR)) # Slight lead-in for punch
            sfx_end = min(master_len, sfx_start + len(sfx_audio))
            sfx_track[sfx_start:sfx_end] += sfx_audio[:sfx_end - sfx_start]

        # 3. Calculate Word Timings & Sentiment Tags
        words = text.split()
        char_counts = [max(1, len(w)) for w in words]
        total_chars = sum(char_counts)
        curr_t = target_start

        danger_set = set(scene.get("danger_words", []))
        safe_set = set(scene.get("safe_words", []))

        for w, c in zip(words, char_counts):
            w_dur = (c / total_chars) * dur
            clean_token = "".join(ch for ch in w.upper() if ch.isalnum())
            tag = "normal"
            if clean_token in danger_set:
                tag = "danger"
            elif clean_token in safe_set:
                tag = "safe"

            word_timings.append({
                "scene_index": idx,
                "word": w,
                "tag": tag,
                "start": round(curr_t, 3),
                "end": round(curr_t + w_dur * 0.95, 3),
                "startMs": int(curr_t * 1000),
                "endMs": int((curr_t + w_dur * 0.95) * 1000)
            })
            curr_t += w_dur

    # 4. Generate Ambient Drone Bed
    drone_track = generate_ambient_drone(total_duration)

    # 5. Master Mix & Normalization
    # Voice: 1.05, SFX: 0.35, Drone: 0.15
    mix = (voice_track * 1.05) + (sfx_track * 0.35) + (drone_track * 0.15)
    peak = np.max(np.abs(mix))
    if peak > 0:
        mix = mix / peak * 0.94

    out_narration = project_dir / "narration.wav"
    sf.write(str(out_narration), mix, SR)
    print(f"Master audio saved to {out_narration} ({len(mix)/SR:.2f}s)")

    out_captions = project_dir / "captions.json"
    with open(out_captions, "w", encoding="utf-8") as f:
        json.dump(word_timings, f, indent=2)
    print(f"Exported {len(word_timings)} words with kinetic tags to {out_captions}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 audio_engine.py <path/to/spec.json>")
        sys.exit(1)
    build_audio(Path(sys.argv[1]))
