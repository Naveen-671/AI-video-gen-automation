"""
Vertical 9:16 reframer for Stage 5.
Deterministically scales and crops horizontal and non-standard video assets
to 1080x1920 30fps MP4 with configurable crop anchors (center, top, bottom).
Strips original audio and loops/trims to exact duration.
"""

import logging
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger("reframing")


class VideoReframer:
    """Reframes arbitrary video clips to standard vertical 1080x1920 30fps format."""

    @staticmethod
    def get_crop_filter(target_w: int = 1080, target_h: int = 1920, anchor: str = "center") -> str:
        """
        Builds the FFmpeg video filter for aspect-ratio preservation scaling followed by anchored crop.
        """
        anchor_lower = anchor.lower().strip()
        if anchor_lower == "top":
            y_expr = "0"
        elif anchor_lower == "bottom":
            y_expr = f"(in_h-{target_h})"
        else:  # default "center"
            y_expr = f"(in_h-{target_h})/2"

        scale_filter = f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase"
        crop_filter = f"crop={target_w}:{target_h}:(in_w-{target_w})/2:{y_expr}"
        fps_filter = "fps=30"
        return f"{scale_filter},{crop_filter},{fps_filter},format=yuv420p"

    def reframe_clip(
        self,
        input_video_path: Path,
        output_clip_path: Path,
        duration: float,
        anchor: str = "center",
        target_w: int = 1080,
        target_h: int = 1920
    ) -> Path:
        """
        Executes FFmpeg to produce a clean 1080x1920 clip of exact duration.
        - Strips existing audio (-an)
        - Infinite loops if video is shorter than duration (-stream_loop -1)
        - Applies scaling and cropping
        - Trims to exact duration (-t duration)
        """
        output_clip_path.parent.mkdir(parents=True, exist_ok=True)
        vf = self.get_crop_filter(target_w=target_w, target_h=target_h, anchor=anchor)

        cmd = [
            "ffmpeg",
            "-y",
            "-stream_loop", "-1",
            "-i", str(input_video_path),
            "-t", f"{duration:.3f}",
            "-vf", vf,
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "22",
            "-an",  # Strip original audio
            "-movflags", "+faststart",
            str(output_clip_path)
        ]

        logger.info(f"Reframing {input_video_path.name} -> {output_clip_path.name} (anchor={anchor}, dur={duration:.2f}s)")
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            logger.error(f"FFmpeg reframe failed: {res.stderr}")
            raise RuntimeError(f"FFmpeg reframe error: {res.stderr[-500:]}")

        return output_clip_path
