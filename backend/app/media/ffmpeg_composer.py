"""FFmpeg video composer using safe argument lists to build 9:16 vertical Short videos with Ken Burns motion and xfade transitions."""

import hashlib
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.app.media.rendering_adapters import (
    render_timeline_with_crossfades,
    RenderingAdapterError
)

logger = logging.getLogger("ffmpeg_composer")

VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".mkv", ".avi", ".m4v"}


class FFmpegCompositionError(Exception):
    """Raised when the FFmpeg rendering subprocess fails."""
    pass


class FFmpegComposer:
    """Composes scenes, Ken Burns/video reframing, xfade transitions, subtitles, and audio into an immutable MP4 video."""

    def __init__(self, width: int = 1080, height: int = 1920, fps: int = 30):
        self.width = width
        self.height = height
        self.fps = fps

    def render(
        self,
        scenes: List[Dict[str, Any]],
        output_path: Path,
        subtitles_path: Optional[Path] = None,
        audio_path: Optional[Path] = None,
        enable_motion: bool = True,
        enable_transitions: bool = True,
        transition_duration: float = 0.5,
        use_adapter: bool = True
    ) -> Dict[str, Any]:
        """
        Executes FFmpeg composition using an argument list (no shell injection).
        Produces a web-optimized vertical MP4 with bounded Ken Burns motion / authentic video clips,
        safe cross-dissolve transitions (with duration-preserving handle extensions),
        burned-in subtitles, and AAC audio.
        Delegates to clean-room rendering adapter, preserving legacy fallback.
        """
        if not scenes:
            raise FFmpegCompositionError("Cannot render video with empty scenes list.")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        if use_adapter:
            try:
                res = render_timeline_with_crossfades(
                    scenes=scenes,
                    output_path=output_path,
                    subtitles_path=subtitles_path,
                    audio_path=audio_path,
                    width=self.width,
                    height=self.height,
                    fps=self.fps,
                    enable_motion=enable_motion,
                    enable_transitions=enable_transitions,
                    transition_duration=transition_duration,
                    transition_mode="duration_preserving"
                )
                return {
                    "output_path": res["output_path"],
                    "render_checksum": res["render_checksum"],
                    "byte_size": res["byte_size"],
                    "resolution": f"{self.width}x{self.height}",
                    "fps": self.fps,
                    "enable_motion": enable_motion,
                    "enable_transitions": res.get("transitions_enabled", enable_transitions),
                    "measured_duration": res.get("measured_duration_seconds")
                }
            except Exception as exc:
                logger.warning(f"Rendering adapter encountered exception ({exc}); falling back to legacy render path.")

        # Legacy Fallback Path
        cmd: List[str] = ["ffmpeg", "-y"]
        num_scenes = len(scenes)
        base_durations = [float(s.get("duration_seconds", 5.0)) for s in scenes]

        use_transitions = enable_transitions and num_scenes > 1
        if use_transitions:
            min_required = 2.0 * transition_duration
            if any(d < min_required for d in base_durations):
                logger.info(
                    f"A scene duration is shorter than {min_required}s (2x transition duration {transition_duration}s). "
                    "Falling back to clean jump cuts (concat) to prevent filtergraph clipping."
                )
                use_transitions = False

        for i, scene in enumerate(scenes):
            visual_path = scene.get("visual_asset_path")
            if not visual_path or not Path(visual_path).exists():
                raise FFmpegCompositionError(f"Scene visual asset not found: {visual_path}")

            base_dur = base_durations[i]
            eff_dur = (base_dur + transition_duration) if (use_transitions and i < num_scenes - 1) else base_dur

            path_obj = Path(visual_path)
            is_video = path_obj.suffix.lower() in VIDEO_EXTENSIONS

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

        audio_input_idx: Optional[int] = None
        if audio_path and audio_path.exists():
            audio_input_idx = num_scenes
            cmd.extend(["-i", str(audio_path)])

        filter_parts = []
        for i, scene in enumerate(scenes):
            v_in = f"[{i}:v]"
            v_out = f"[v{i}]"
            base_dur = base_durations[i]
            eff_dur = (base_dur + transition_duration) if (use_transitions and i < num_scenes - 1) else base_dur
            total_frames = max(1, int(round(eff_dur * self.fps)))

            path_obj = Path(scene.get("visual_asset_path"))
            is_video = path_obj.suffix.lower() in VIDEO_EXTENSIONS

            if is_video:
                filter_parts.append(
                    f"{v_in}scale={self.width}:{self.height}:force_original_aspect_ratio=increase,"
                    f"crop={self.width}:{self.height},"
                    f"fps={self.fps},setsar=1,format=yuv420p{v_out}"
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
                        f"{v_in}scale={self.width}:{self.height}:force_original_aspect_ratio=increase,"
                        f"crop={self.width}:{self.height},"
                        f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}':d={total_frames}:s={self.width}x{self.height}:fps={self.fps},"
                        f"setsar=1,fps={self.fps},format=yuv420p{v_out}"
                    )
                else:
                    filter_parts.append(
                        f"{v_in}scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,"
                        f"pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2:color=black,"
                        f"setsar=1,fps={self.fps},format=yuv420p{v_out}"
                    )

        if use_transitions:
            last_label = "[v0]"
            cum_offset = base_durations[0]
            for k in range(1, num_scenes):
                next_label = f"[xf{k}]"
                filter_parts.append(
                    f"{last_label}[v{k}]xfade=transition=fade:duration={transition_duration:.2f}:offset={cum_offset:.2f}{next_label}"
                )
                last_label = next_label
                cum_offset += base_durations[k]
            final_composite_label = last_label
        elif num_scenes > 1:
            concat_inputs = [f"[v{i}]" for i in range(num_scenes)]
            filter_parts.append(f"{''.join(concat_inputs)}concat=n={num_scenes}:v=1:a=0[concat_out]")
            final_composite_label = "[concat_out]"
        else:
            final_composite_label = "[v0]"

        if subtitles_path and subtitles_path.exists() and subtitles_path.stat().st_size > 0:
            clean_sub_path = (
                str(subtitles_path)
                .replace("\\", "/")
                .replace(":", "\\:")
                .replace("'", "'\\''")
                .replace("[", "\\[")
                .replace("]", "\\]")
            )
            filter_parts.append(f"{final_composite_label}subtitles='{clean_sub_path}'[subtitled_v]")
            final_video_label = "[subtitled_v]"
        else:
            final_video_label = final_composite_label

        cmd.extend(["-filter_complex", ";".join(filter_parts)])
        cmd.extend(["-map", final_video_label])

        if audio_input_idx is not None:
            cmd.extend(["-map", f"{audio_input_idx}:a", "-c:a", "aac", "-b:a", "192k"])
        else:
            cmd.extend(["-an"])

        cmd.extend([
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "22",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(output_path)
        ])

        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            raise FFmpegCompositionError(f"FFmpeg render failed with exit code {res.returncode}:\n{res.stderr}")

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise FFmpegCompositionError("Render completed but output file is missing or zero bytes.")

        hasher = hashlib.sha256()
        with output_path.open("rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        checksum = hasher.hexdigest()

        return {
            "output_path": str(output_path),
            "render_checksum": checksum,
            "byte_size": output_path.stat().st_size,
            "resolution": f"{self.width}x{self.height}",
            "fps": self.fps,
            "enable_motion": enable_motion,
            "enable_transitions": use_transitions
        }
