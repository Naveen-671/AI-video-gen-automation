"""SubStation Alpha (ASS) subtitle generator enforcing rhythmic phrase-level sync and mobile safe zones."""

import re
from pathlib import Path
from typing import List, Dict, Any, Optional

def format_timestamp(seconds: float) -> str:
    """Formats seconds into ASS timestamp format: H:MM:SS.cs"""
    if seconds < 0:
        seconds = 0.0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs >= 100:
        cs = 99
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

def split_into_phrase_chunks(text: str, max_words_per_chunk: int = 4) -> List[str]:
    """
    Splits sentence text into natural, readable short phrase chunks (2 to 4 words).
    Preserves Hindi (Devanagari) and English Unicode strings without corruption.
    """
    clean = re.sub(r'\s+', ' ', text).strip()
    if not clean:
        return []

    words = clean.split(' ')
    chunks = []
    current_chunk = []

    for w in words:
        current_chunk.append(w)
        # Break on natural punctuation or max words
        if len(current_chunk) >= max_words_per_chunk or w.endswith(('.', '?', '!', ',', ':', ';', '।')):
            chunks.append(" ".join(current_chunk))
            current_chunk = []

    if current_chunk:
        if chunks and len(current_chunk) == 1 and len(chunks[-1].split()) < max_words_per_chunk:
            # Append trailing single word to previous chunk for better cadence
            chunks[-1] = chunks[-1] + " " + current_chunk[0]
        else:
            chunks.append(" ".join(current_chunk))

    return chunks

def generate_ass_subtitles(
    scenes: List[Dict[str, Any]],
    output_path: Path,
    width: int = 1080,
    height: int = 1920,
    font_size: Optional[int] = None,
    margin_v: Optional[int] = None,
    highlight_active: bool = True
) -> Path:
    """
    Generates an ASS subtitle file with phrase-level synchronized captions.
    Enforces mobile interface safe zones:
    - 1080x1920: font_size 50, bottom margin 240px (clearing YouTube Shorts and Instagram Reels UI).
    - 720x1280: font_size 34, bottom margin 170px.
    """
    # Scale typography and safe zones based on canvas height
    if font_size is None:
        font_size = 50 if height >= 1920 else 34

    if margin_v is None:
        margin_v = 240 if height >= 1920 else 170

    outline_width = 4 if height >= 1920 else 3
    shadow_depth = 2 if height >= 1920 else 1
    margin_lr = 80 if width >= 1080 else 50

    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        # Style Default: Bold White text with thick black outline & soft shadow, centered alignment (2)
        f"Style: Default,DejaVu Sans,{font_size},&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,{outline_width},{shadow_depth},2,{margin_lr},{margin_lr},{margin_v},1",
        # Style Emphasis: Gold/Yellow highlight for key keywords
        f"Style: Emphasis,DejaVu Sans,{font_size},&H003BF0FF,&H0000FFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,{outline_width},{shadow_depth},2,{margin_lr},{margin_lr},{margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
    ]

    current_time = 0.0
    for scene in scenes:
        scene_duration = float(scene.get("duration_seconds", 5.0))
        text = scene.get("caption_text") or scene.get("narration_text") or ""
        text = text.replace("\n", " ").replace("\r", "").strip()

        if text and scene_duration > 0:
            chunks = split_into_phrase_chunks(text, max_words_per_chunk=4)
            if not chunks:
                chunks = [text]

            # Calculate phrase durations proportionally to character length
            total_chars = sum(max(1, len(c)) for c in chunks)
            chunk_start = current_time

            for idx, chunk in enumerate(chunks):
                char_ratio = max(1, len(chunk)) / float(total_chars)
                chunk_duration = scene_duration * char_ratio
                chunk_end = chunk_start + chunk_duration

                # Bound chunk_end to not exceed scene boundary
                if idx == len(chunks) - 1:
                    chunk_end = current_time + scene_duration

                start_str = format_timestamp(chunk_start)
                end_str = format_timestamp(chunk_end)

                # Format text with high-contrast formatting (escape brackets for ASS)
                safe_chunk = chunk.replace("{", "\\{").replace("}", "\\}")
                
                # Active highlight effect on the last or accented word
                if highlight_active and len(safe_chunk.split()) > 1:
                    parts = safe_chunk.split()
                    highlighted = " ".join(parts[:-1]) + f" {{\\c&H003BF0FF}}{parts[-1]}{{\\c&H00FFFFFF}}"
                    lines.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{highlighted}")
                else:
                    lines.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{safe_chunk}")

                chunk_start = chunk_end

        current_time += scene_duration

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    return output_path
