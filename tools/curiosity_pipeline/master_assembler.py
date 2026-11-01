#!/usr/bin/env python3
"""Master Video Assembler for Curiosity Shorts Pipeline.
Concatenates scenes, scales to 1080x1920, overlays watermark concealment badge,
burns dynamic karaoke subtitles, and loudnorm-masters the audio."""

import sys
import json
import subprocess
from pathlib import Path

def assemble_master(spec_path: Path):
    with open(spec_path, "r", encoding="utf-8") as f:
        spec = json.load(f)

    project_dir = Path(spec["project_dir"])
    slug = spec.get("slug", "short")
    total_duration = float(spec.get("total_duration", 56.0))
    badge_path = Path(spec.get("watermark_badge", project_dir / "watermark_badge.png"))
    narration_path = project_dir / "narration.wav"
    ass_path = project_dir / "captions.ass"
    final_output = project_dir / f"{slug}_final_short.mp4"
    concat_txt = project_dir / "concat_scenes.txt"

    # Verify all scene files
    scene_files = []
    missing_scenes = []
    for sc in spec["scenes"]:
        sc_file = project_dir / f"{sc['id']}.mp4"
        if not sc_file.exists():
            missing_scenes.append(sc['id'])
        else:
            scene_files.append(sc_file)

    if missing_scenes:
        print(f"Error: Missing scene videos: {missing_scenes}")
        return False

    for required in [narration_path, ass_path, badge_path]:
        if not required.exists():
            print(f"Error: Missing required asset {required}")
            return False

    # Write concat list
    with open(concat_txt, "w", encoding="utf-8") as f:
        for s in scene_files:
            f.write(f"file '{s.resolve()}'\n")

    # Safe subtitle filter escaping for FFmpeg
    escaped_ass = str(ass_path.resolve()).replace("'", "\\'")

    filter_complex = (
        f"[0:v]trim=0:{total_duration},setpts=PTS-STARTPTS,scale=1080:1920:flags=lanczos[scaled];"
        f"[scaled][2:v]overlay=860:1680[badged];"
        f"[badged]subtitles='{escaped_ass}'[v_out];"
        f"[0:a]volume=0.08[clip_a];"
        f"[1:a]volume=1.0[mix_a];"
        f"[clip_a][mix_a]amix=inputs=2:duration=first:dropout_transition=2,atrim=0:{total_duration},loudnorm=I=-14:TP=-1.5:LRA=7[a_out]"
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_txt.resolve()),
        "-i", str(narration_path.resolve()),
        "-i", str(badge_path.resolve()),
        "-filter_complex", filter_complex,
        "-map", "[v_out]",
        "-map", "[a_out]",
        "-c:v", "libx264",
        "-preset", "slow",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "48000",
        "-movflags", "+faststart",
        str(final_output.resolve())
    ]

    print(f"Executing master render for {spec['title']} ({total_duration}s)...")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print("FFmpeg render failed!")
        print("STDERR:\n", res.stderr[-2000:])
        return False

    print(f"Master render successfully created: {final_output}")
    return True

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 master_assembler.py <path/to/spec.json>")
        sys.exit(1)
    success = assemble_master(Path(sys.argv[1]))
    sys.exit(0 if success else 1)
