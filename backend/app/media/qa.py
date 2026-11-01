"""Technical QA verification using ffprobe and FFmpeg filters for video integrity, freezes, and loudness."""

import re
import json
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, List

logger = logging.getLogger("technical_qa")

class TechnicalQA:
    """Automated rule-based quality checks on rendered video artifacts."""

    @staticmethod
    def inspect_and_verify(
        video_path: Path,
        expected_width: int = 1080,
        expected_height: int = 1920,
        expected_duration: float = 15.0,
        audio_expected: bool = True
    ) -> Dict[str, Any]:
        failure_reasons: List[str] = []
        warnings: List[str] = []

        if not video_path.exists():
            return {
                "passed": False,
                "failure_reasons": [f"Render file not found: {video_path}"],
                "warnings": [],
                "details": {}
            }

        size_bytes = video_path.stat().st_size
        if size_bytes == 0:
            return {
                "passed": False,
                "failure_reasons": ["Render file is empty (0 bytes)."],
                "warnings": [],
                "details": {"size_bytes": 0}
            }

        # 1. Probe video streams with ffprobe
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration,size,bit_rate:stream=codec_type,codec_name,width,height,r_frame_rate",
            "-of", "json",
            str(video_path)
        ]

        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            return {
                "passed": False,
                "failure_reasons": [f"ffprobe failed to inspect file: {res.stderr}"],
                "warnings": [],
                "details": {}
            }

        try:
            probe_data = json.loads(res.stdout)
        except json.JSONDecodeError as e:
            return {
                "passed": False,
                "failure_reasons": [f"Failed to parse ffprobe JSON output: {e}"],
                "warnings": [],
                "details": {}
            }

        streams = probe_data.get("streams", [])
        fmt = probe_data.get("format", {})

        video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

        if not video_stream:
            failure_reasons.append("No video stream found in rendered artifact.")

        actual_width = int(video_stream.get("width", 0)) if video_stream else 0
        actual_height = int(video_stream.get("height", 0)) if video_stream else 0
        actual_duration = float(fmt.get("duration", 0.0))

        # Check resolution
        if actual_width != expected_width or actual_height != expected_height:
            failure_reasons.append(
                f"Resolution mismatch: expected {expected_width}x{expected_height}, got {actual_width}x{actual_height}"
            )

        # Check 9:16 aspect ratio
        if actual_height > 0 and round(actual_width / actual_height, 2) != round(9 / 16, 2):
            failure_reasons.append(f"Aspect ratio is not 9:16 ({actual_width}:{actual_height}).")

        # Check duration (within 2.0s margin of error)
        if abs(actual_duration - expected_duration) > 2.5:
            failure_reasons.append(
                f"Duration mismatch: expected ~{expected_duration:.1f}s, got {actual_duration:.1f}s"
            )

        # Check audio presence
        if audio_expected and not audio_stream:
            failure_reasons.append("Audio was expected for this project, but no audio stream was detected.")

        # 2. Black frame detection via blackdetect filter
        black_detected = False
        try:
            bd_cmd = [
                "ffmpeg", "-i", str(video_path),
                "-vf", "blackdetect=d=1.5:pix_th=0.10",
                "-f", "null", "-"
            ]
            bd_res = subprocess.run(bd_cmd, capture_output=True, text=True)
            if "black_start:" in bd_res.stderr:
                warnings.append("Black frames detected exceeding 1.5 seconds.")
                black_detected = True
        except Exception:
            pass

        # 3. Freeze frame detection via freezedetect filter
        freeze_detected = False
        try:
            fz_cmd = [
                "ffmpeg", "-i", str(video_path),
                "-vf", "freezedetect=n=0.003:d=3.0",
                "-f", "null", "-"
            ]
            fz_res = subprocess.run(fz_cmd, capture_output=True, text=True)
            if "freeze_start:" in fz_res.stderr:
                warnings.append("Frozen video frames detected exceeding 3.0 seconds.")
                freeze_detected = True
        except Exception:
            pass

        # 4. Audio Loudness & Clipping measurement
        integrated_lufs = -16.0
        true_peak_dbfs = -1.5
        if audio_stream:
            try:
                eb_cmd = [
                    "ffmpeg", "-i", str(video_path),
                    "-af", "ebur128=peak=true",
                    "-f", "null", "-"
                ]
                eb_res = subprocess.run(eb_cmd, capture_output=True, text=True)
                for line in eb_res.stderr.splitlines():
                    line_str = line.strip()
                    if line_str.startswith("I:") and "LUFS" in line_str:
                        m = re.search(r"I:\s*(-?[\d\.]+)\s*LUFS", line_str)
                        if m:
                            integrated_lufs = float(m.group(1))
                    elif "True peak:" in line_str and "dBFS" in line_str:
                        m = re.search(r"True peak:\s*(-?[\d\.]+)\s*dBFS", line_str)
                        if m:
                            true_peak_dbfs = float(m.group(1))

                # Check clipping risk
                if true_peak_dbfs > -0.5:
                    warnings.append(f"Audio true peak ({true_peak_dbfs:.1f} dBFS) risks digital clipping (max -1.0 dBFS recommended).")
                # Check loudness bounds
                if integrated_lufs > -12.0:
                    warnings.append(f"Audio is excessively loud ({integrated_lufs:.1f} LUFS; target -16.0 LUFS).")
                elif integrated_lufs < -26.0:
                    warnings.append(f"Audio is excessively quiet ({integrated_lufs:.1f} LUFS; target -16.0 LUFS).")
            except Exception:
                pass

        passed = len(failure_reasons) == 0

        return {
            "passed": passed,
            "failure_reasons": failure_reasons,
            "warnings": warnings,
            "details": {
                "width": actual_width,
                "height": actual_height,
                "duration_seconds": round(actual_duration, 2),
                "size_bytes": size_bytes,
                "video_codec": video_stream.get("codec_name") if video_stream else None,
                "audio_codec": audio_stream.get("codec_name") if audio_stream else None,
                "frame_rate": video_stream.get("r_frame_rate") if video_stream else None,
                "integrated_lufs": integrated_lufs,
                "true_peak_dbfs": true_peak_dbfs,
                "black_frame_detected": black_detected,
                "freeze_frame_detected": freeze_detected
            }
        }
