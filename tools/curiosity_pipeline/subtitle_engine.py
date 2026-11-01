#!/usr/bin/env python3
"""Modular Subtitle Engine for Curiosity Shorts Pipeline.
Generates styled ASS subtitles with kinetic per-word karaoke highlighting and semantic color accents."""

import sys
import json
from pathlib import Path

def fmt_ass_time(seconds: float) -> str:
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs >= 100:
        cs = 99
    return f"{hrs:d}:{mins:02d}:{secs:02d}.{cs:02d}"

def generate_subtitles(spec_path: Path):
    with open(spec_path, "r", encoding="utf-8") as f:
        spec = json.load(f)

    project_dir = Path(spec["project_dir"])
    captions_json = project_dir / "captions.json"
    output_ass = project_dir / "captions.ass"

    if not captions_json.exists():
        print(f"Error: {captions_json} does not exist. Run audio_engine.py first.")
        sys.exit(1)

    with open(captions_json, "r", encoding="utf-8") as f:
        words = json.load(f)

    # Chunk words into natural phrases of 2-3 words
    phrases = []
    curr_phrase = []
    for w in words:
        curr_phrase.append(w)
        if w["word"].rstrip().endswith((".", "!", "?", ",")) or len(curr_phrase) >= 3:
            phrases.append(curr_phrase)
            curr_phrase = []
    if curr_phrase:
        phrases.append(curr_phrase)

    # Header with mobile safe-zone (MarginV: 420px from bottom)
    header = """[Script Info]
Title: Curiosity Short Captions
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Liberation Sans,74,&H00FFFFFF,&H0000FFFF,&H00000000,&H90000000,-1,0,0,0,100,100,1,0,1,5.5,3,2,60,60,420,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events = []
    for phrase in phrases:
        for i, target_word in enumerate(phrase):
            w_start = target_word["start"]
            w_end = target_word["end"] + 0.05
            if i + 1 < len(phrase):
                w_end = min(w_end, phrase[i + 1]["start"])

            text_parts = []
            for j, w in enumerate(phrase):
                clean_word = w["word"].upper()
                tag = w.get("tag", "normal")

                if j == i:
                    if tag == "danger":
                        # Vivid crimson red & slight pop
                        text_parts.append(f"{{\\c&H1010FF&\\fscx112\\fscy112\\b1}}{clean_word}{{\\rDefault}}")
                    elif tag == "safe":
                        # Emerald green & slight pop
                        text_parts.append(f"{{\\c&H30E040&\\fscx112\\fscy112\\b1}}{clean_word}{{\\rDefault}}")
                    else:
                        # Bright gold / yellow
                        text_parts.append(f"{{\\c&H00D7FF&\\b1}}{clean_word}{{\\rDefault}}")
                else:
                    text_parts.append(f"{clean_word}")

            line_text = " ".join(text_parts)
            events.append(f"Dialogue: 0,{fmt_ass_time(w_start)},{fmt_ass_time(w_end)},Default,,0,0,0,,{line_text}")

    with open(output_ass, "w", encoding="utf-8") as f:
        f.write(header)
        for ev in events:
            f.write(ev + "\n")

    print(f"Generated {len(events)} styled kinetic dialogue events in {output_ass}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 subtitle_engine.py <path/to/spec.json>")
        sys.exit(1)
    generate_subtitles(Path(sys.argv[1]))
