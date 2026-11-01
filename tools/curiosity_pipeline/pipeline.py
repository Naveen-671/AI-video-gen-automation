#!/usr/bin/env python3
"""Curiosity Shorts Daily Production CLI Pipeline.
Orchestrates script spec loading, audio generation, Foley SFX, dynamic subtitles, and master assembly."""

import sys
import argparse
from pathlib import Path

# Add pipeline directory to path
PIPELINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PIPELINE_DIR))

from audio_engine import build_audio
from subtitle_engine import generate_subtitles
from master_assembler import assemble_master

def run_pipeline(spec_path: Path, step: str = "all"):
    spec_path = spec_path.resolve()
    if not spec_path.exists():
        print(f"Error: Specification file not found: {spec_path}")
        sys.exit(1)

    print(f"\n==========================================")
    print(f"  CURIOSITY SHORTS PRODUCTION PIPELINE")
    print(f"  Target: {spec_path.name}")
    print(f"  Step: {step.upper()}")
    print(f"==========================================\n")

    if step in ("all", "audio"):
        print("[Step 1/3] Generating Audio Track (Kokoro Narration + Procedural SFX + Ambient Drone)...")
        build_audio(spec_path)

    if step in ("all", "subtitles"):
        print("\n[Step 2/3] Generating Kinetic Dynamic Karaoke Subtitles (.ass)...")
        generate_subtitles(spec_path)

    if step in ("all", "assemble"):
        print("\n[Step 3/3] Assembling Master 1080x1920 Short with FFmpeg...")
        success = assemble_master(spec_path)
        if not success:
            print("Assembly failed or waiting on scene videos.")
            return False

    print("\n Pipeline execution completed successfully!")
    return True

def main():
    parser = argparse.ArgumentParser(description="Daily Curiosity Shorts Automation Pipeline")
    parser.add_argument("spec", type=str, help="Path to project spec JSON")
    parser.add_argument(
        "--step",
        choices=["all", "audio", "subtitles", "assemble"],
        default="all",
        help="Pipeline step to execute (default: all)"
    )
    args = parser.parse_args()

    success = run_pipeline(Path(args.spec), step=args.step)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
