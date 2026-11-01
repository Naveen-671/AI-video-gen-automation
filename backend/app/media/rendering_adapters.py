"""FFmpeg Rendering Adapters: Clean-room, independently testable compositing, sidechain ducking, and EBU R128 compliance."""

import os
import re
import json
import hashlib
import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("rendering_adapters")

VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".mkv", ".avi", ".m4v"}


class RenderingAdapterError(Exception):
    """Raised when an FFmpeg rendering, mixing, or normalization operation fails."""
    pass


def escape_ffmpeg_filter_path(path_str: str) -> str:
    """Escapes backslashes, colons, and single quotes for FFmpeg filtergraph strings."""
    return (
        path_str.replace("\\", "/")
        .replace(":", "\\:")
        .replace("'", "'\\''")
        .replace("[", "\\[")
        .replace("]", "\\]")
    )


def measure_ebur128_loudness(audio_or_video_path: Path) -> Dict[str, Any]:
    """
    Measures Integrated Loudness (LUFS), True Peak (dBTP/dBFS), and Loudness Range (LRA)
    using FFmpeg's official ebur128 filter according to ITU-R BS.1770-4 / EBU R128.
    """
    if not audio_or_video_path.exists():
        raise RenderingAdapterError(f"File for loudness measurement does not exist: {audio_or_video_path}")

    cmd = [
        "ffmpeg", "-i", str(audio_or_video_path),
        "-af", "ebur128=peak=true",
        "-f", "null", "-"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)

    integrated_lufs = -70.0
    true_peak_dbfs = -70.0
    lra_lu = 0.0

    # Parse ebur128 summary block from stderr
    for line in res.stderr.splitlines():
        line_str = line.strip()
        if line_str.startswith("I:") and "LUFS" in line_str:
            m = re.search(r"I:\s*(-?[\d\.]+)\s*LUFS", line_str)
            if m:
                integrated_lufs = float(m.group(1))
        elif line_str.startswith("Peak:") and "dBFS" in line_str:
            m = re.search(r"Peak:\s*(-?[\d\.]+)\s*dBFS", line_str)
            if m:
                true_peak_dbfs = float(m.group(1))
        elif "True peak:" in line_str and ("dBFS" in line_str or "dBTP" in line_str):
            m = re.search(r"True peak:\s*(-?[\d\.]+)", line_str)
            if m:
                true_peak_dbfs = float(m.group(1))
        elif line_str.startswith("LRA:") and "LU" in line_str:
            m = re.search(r"LRA:\s*(-?[\d\.]+)\s*LU", line_str)
            if m:
                lra_lu = float(m.group(1))

    return {
        "integrated_lufs": integrated_lufs,
        "true_peak_dbfs": true_peak_dbfs,
        "lra_lu": lra_lu,
        "is_compliant": (-15.5 <= integrated_lufs <= -13.0) and (true_peak_dbfs <= -1.0)
    }


def mix_speech_and_music_ducked(
    speech_path: Path,
    output_path: Path,
    music_path: Optional[Path] = None,
    target_lufs: float = -14.0,
    true_peak_ceiling: float = -1.0,
    ducking_ratio: float = 8.0,
    ducking_threshold: float = 0.08,
    ducking_attack_ms: int = 100,
    ducking_release_ms: int = 350,
    music_base_volume: float = 0.22
) -> Dict[str, Any]:
    """
    Clean-room implementation of speech/music mixing with configurable sidechain ducking
    and EBU R128 loudness normalization.
    - Speech narration remains primary, unclipped, and full-fidelity.
    - Background music ducks smoothly when speech is active and recovers during pauses.
    - Output is normalized to the specified target LUFS and true-peak ceiling.
    """
    if not speech_path.exists():
        raise RenderingAdapterError(f"Primary speech audio not found: {speech_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Branch A: Voice-only (no background music)
    if not music_path or not music_path.exists():
        filter_str = f"loudnorm=I={target_lufs}:TP={true_peak_ceiling}:LRA=7:linear=true"
        cmd = [
            "ffmpeg", "-y",
            "-i", str(speech_path),
            "-af", filter_str,
            "-c:a", "aac",
            "-b:a", "192k",
            str(output_path)
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            logger.warning(f"Voice-only loudnorm failed (likely pure silence or short audio), copying directly: {res.stderr[:200]}")
            cmd_copy = [
                "ffmpeg", "-y",
                "-i", str(speech_path),
                "-c:a", "aac",
                "-b:a", "192k",
                str(output_path)
            ]
            res_copy = subprocess.run(cmd_copy, capture_output=True, text=True)
            if res_copy.returncode != 0:
                raise RenderingAdapterError(f"Voice-only loudnorm and pass-through both failed: {res.stderr}")

        loudness = measure_ebur128_loudness(output_path)
        checksum = compute_file_sha256(output_path)
        return {
            "output_path": str(output_path),
            "checksum": checksum,
            "mode": "voice_only",
            "target_lufs": target_lufs,
            "true_peak_ceiling": true_peak_ceiling,
            "measured_lufs": loudness["integrated_lufs"],
            "measured_true_peak": loudness["true_peak_dbfs"],
            "measured_lra": loudness["lra_lu"],
            "is_compliant": loudness["is_compliant"]
        }

    # Branch B: Dual-track with Sidechain Compression Ducking
    filter_complex = (
        f"[1:a]volume={music_base_volume}[bg_bed];"
        f"[bg_bed][0:a]sidechaincompress="
        f"threshold={ducking_threshold}:ratio={ducking_ratio}:"
        f"attack={ducking_attack_ms}:release={ducking_release_ms}[ducked_bg];"
        f"[0:a][ducked_bg]amix=inputs=2:duration=first:dropout_transition=2[mixed];"
        f"[mixed]loudnorm=I={target_lufs}:TP={true_peak_ceiling}:LRA=7:linear=true[aout]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", str(speech_path),
        "-i", str(music_path),
        "-filter_complex", filter_complex,
        "-map", "[aout]",
        "-c:a", "aac",
        "-b:a", "192k",
        str(output_path)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RenderingAdapterError(f"Sidechain audio ducking render failed: {res.stderr}")

    loudness = measure_ebur128_loudness(output_path)
    checksum = compute_file_sha256(output_path)

    return {
        "output_path": str(output_path),
        "checksum": checksum,
        "mode": "sidechain_ducked",
        "target_lufs": target_lufs,
        "true_peak_ceiling": true_peak_ceiling,
        "measured_lufs": loudness["integrated_lufs"],
        "measured_true_peak": loudness["true_peak_dbfs"],
        "measured_lra": loudness["lra_lu"],
        "is_compliant": loudness["is_compliant"]
    }


def render_timeline_with_crossfades(
    scenes: List[Dict[str, Any]],
    output_path: Path,
    subtitles_path: Optional[Path] = None,
    audio_path: Optional[Path] = None,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    enable_motion: bool = True,
    enable_transitions: bool = True,
    transition_duration: float = 0.5,
    transition_mode: str = "duration_preserving"
) -> Dict[str, Any]:
    """
    Renders multi-scene vertical video with duration-correct crossfades.
    - 'duration_preserving' mode: each scene's visible core duration is preserved by extending
      input handles by transition_duration, resulting in total duration = sum(base_durations).
    - 'standard_overlap' mode: clips overlap by transition_duration, resulting in
      total duration = sum(base_durations) - (N-1) * transition_duration.
    Safe parameter lists are used exclusively (no shell injection).
    """
    if not scenes:
        raise RenderingAdapterError("Cannot render timeline with zero scenes.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd: List[str] = ["ffmpeg", "-y"]

    num_scenes = len(scenes)
    base_durations = [float(s.get("duration_seconds", 5.0)) for s in scenes]

    use_transitions = enable_transitions and num_scenes > 1
    if use_transitions:
        # Minimum duration gate: scene must be at least 2x transition duration
        min_required = 2.0 * transition_duration
        if any(d < min_required for d in base_durations):
            logger.warning(
                f"A scene duration is shorter than {min_required}s (2x transition duration). "
                "Falling back to clean cuts to prevent filtergraph clipping."
            )
            use_transitions = False

    # 1. Add visual inputs with appropriate handle durations
    for i, scene in enumerate(scenes):
        visual_path = scene.get("visual_asset_path")
        if not visual_path or not Path(visual_path).exists():
            raise RenderingAdapterError(f"Visual asset not found for Scene {i+1}: {visual_path}")

        base_dur = base_durations[i]
        path_obj = Path(visual_path)
        is_video = path_obj.suffix.lower() in VIDEO_EXTENSIONS

        # In duration_preserving mode, extend scene 0..N-2 by transition_duration
        if use_transitions and transition_mode == "duration_preserving" and i < num_scenes - 1:
            eff_dur = base_dur + transition_duration
        else:
            eff_dur = base_dur

        if is_video:
            cmd.extend([
                "-stream_loop", "-1",
                "-t", f"{eff_dur:.3f}",
                "-i", str(visual_path)
            ])
        else:
            motion_preset = scene.get("motion_preset", "zoom_in")
            is_motion = enable_motion and motion_preset != "static"
            if is_motion:
                cmd.extend(["-i", str(visual_path)])
            else:
                cmd.extend([
                    "-loop", "1",
                    "-t", f"{eff_dur:.3f}",
                    "-i", str(visual_path)
                ])

    # 2. Add audio input if provided
    audio_input_idx: Optional[int] = None
    if audio_path and audio_path.exists():
        audio_input_idx = num_scenes
        cmd.extend(["-i", str(audio_path)])

    # 3. Construct filter complex
    filter_parts: List[str] = []
    for i, scene in enumerate(scenes):
        v_in = f"[{i}:v]"
        v_out = f"[v{i}]"
        base_dur = base_durations[i]
        if use_transitions and transition_mode == "duration_preserving" and i < num_scenes - 1:
            eff_dur = base_dur + transition_duration
        else:
            eff_dur = base_dur

        total_frames = max(1, int(round(eff_dur * fps)))
        path_obj = Path(scene.get("visual_asset_path"))
        is_video = path_obj.suffix.lower() in VIDEO_EXTENSIONS

        if is_video:
            # Normalize video stream: scale, crop to target aspect ratio, fps, yuv420p
            filter_parts.append(
                f"{v_in}scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},"
                f"fps={fps},setsar=1,format=yuv420p{v_out}"
            )
        else:
            motion_preset = scene.get("motion_preset", "zoom_in")
            if enable_motion and motion_preset != "static":
                if motion_preset == "zoom_in":
                    z_expr = f"min(1.0+0.12*(on/{total_frames}),1.12)"
                    x_expr = "iw/2-(iw/zoom/2)"
                    y_expr = "ih/2-(ih/zoom/2)"
                elif motion_preset == "zoom_out":
                    z_expr = f"max(1.12-0.12*(on/{total_frames}),1.0)"
                    x_expr = "iw/2-(iw/zoom/2)"
                    y_expr = "ih/2-(ih/zoom/2)"
                elif motion_preset == "pan_left":
                    z_expr = "1.08"
                    x_expr = f"(iw-iw/zoom)*(1-on/{total_frames})"
                    y_expr = "ih/2-(ih/zoom/2)"
                else:
                    z_expr = f"min(1.0+0.10*(on/{total_frames}),1.10)"
                    x_expr = "iw/2-(iw/zoom/2)"
                    y_expr = "ih/2-(ih/zoom/2)"

                filter_parts.append(
                    f"{v_in}scale={width}:{height}:force_original_aspect_ratio=increase,"
                    f"crop={width}:{height},"
                    f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}':d={total_frames}:s={width}x{height}:fps={fps},"
                    f"setsar=1,fps={fps},format=yuv420p{v_out}"
                )
            else:
                filter_parts.append(
                    f"{v_in}scale={width}:{height}:force_original_aspect_ratio=decrease,"
                    f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
                    f"setsar=1,fps={fps},format=yuv420p{v_out}"
                )

    # 4. Assemble video stream with xfade or concat
    if use_transitions:
        last_label = "[v0]"
        cum_offset = base_durations[0]
        for k in range(1, num_scenes):
            next_label = f"[xf{k}]"
            # Offset calculation based on mode
            if transition_mode == "duration_preserving":
                offset_val = cum_offset
                cum_offset += base_durations[k]
            else:
                offset_val = cum_offset - (k * transition_duration)
                cum_offset += base_durations[k]

            filter_parts.append(
                f"{last_label}[v{k}]xfade=transition=fade:duration={transition_duration:.2f}:offset={offset_val:.2f}{next_label}"
            )
            last_label = next_label
        final_composite_label = last_label
    elif num_scenes > 1:
        concat_inputs = [f"[v{i}]" for i in range(num_scenes)]
        filter_parts.append(f"{''.join(concat_inputs)}concat=n={num_scenes}:v=1:a=0[concat_out]")
        final_composite_label = "[concat_out]"
    else:
        final_composite_label = "[v0]"

    # 5. Burn-in subtitles if provided
    if subtitles_path and subtitles_path.exists() and subtitles_path.stat().st_size > 0:
        clean_sub_path = escape_ffmpeg_filter_path(str(subtitles_path))
        filter_parts.append(f"{final_composite_label}subtitles='{clean_sub_path}'[subtitled_v]")
        final_video_label = "[subtitled_v]"
    else:
        final_video_label = final_composite_label

    cmd.extend(["-filter_complex", ";".join(filter_parts)])
    cmd.extend(["-map", final_video_label])

    # 6. Audio mapping
    if audio_input_idx is not None:
        cmd.extend(["-map", f"{audio_input_idx}:a", "-c:a", "aac", "-b:a", "192k"])
    else:
        cmd.extend(["-an"])

    # Video encoding flags
    cmd.extend([
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "22",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path)
    ])

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RenderingAdapterError(f"FFmpeg timeline composition failed:\n{res.stderr}")

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RenderingAdapterError("Render finished but output file is missing or zero bytes.")

    meta = generate_render_metadata(output_path, additional_context={
        "width": width,
        "height": height,
        "fps": fps,
        "scenes_count": num_scenes,
        "transitions_enabled": use_transitions,
        "transition_mode": transition_mode if use_transitions else "none",
        "transition_duration": transition_duration if use_transitions else 0.0
    })

    return meta


def compute_file_sha256(file_path: Path) -> str:
    """Computes deterministic SHA-256 hash of a file."""
    hasher = hashlib.sha256()
    with file_path.open("rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def generate_render_metadata(
    rendered_file_path: Path,
    additional_context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Computes deterministic SHA-256 checksum and extracts verified stream properties
    including duration, dimensions, framerate, and loudness.
    """
    if not rendered_file_path.exists():
        raise RenderingAdapterError(f"Rendered file does not exist: {rendered_file_path}")

    checksum = compute_file_sha256(rendered_file_path)
    file_size = rendered_file_path.stat().st_size

    # ffprobe stream inspection
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration,size,bit_rate:stream=index,codec_type,codec_name,width,height,r_frame_rate,duration,nb_frames",
        "-of", "json",
        str(rendered_file_path)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    probe = json.loads(res.stdout) if res.returncode == 0 else {}

    streams = probe.get("streams", [])
    format_info = probe.get("format", {})

    v_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
    has_audio = any(s.get("codec_type") == "audio" for s in streams)

    w = int(v_stream.get("width", 0))
    h = int(v_stream.get("height", 0))
    codec = v_stream.get("codec_name", "unknown")
    dur = float(v_stream.get("duration") or format_info.get("duration", "0.0"))

    # Loudness measurement if audio is present
    loudness_info = measure_ebur128_loudness(rendered_file_path) if has_audio else {}

    result = {
        "output_path": str(rendered_file_path),
        "render_checksum": checksum,
        "byte_size": file_size,
        "measured_duration_seconds": round(dur, 3),
        "resolution": f"{w}x{h}",
        "video_codec": codec,
        "has_audio": has_audio,
        "loudness": loudness_info
    }
    if additional_context:
        result.update(additional_context)

    return result
