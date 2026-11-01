"""Narration audio adapters supporting local Kokoro-82M ONNX TTS, manual ingest, and silent test mode."""

import os
import json
import hashlib
import logging
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger("media.narration")

DEFAULT_KOKORO_MODEL_PATH = Path("models/kokoro/kokoro-v1.0.fp16.onnx")
DEFAULT_KOKORO_VOICES_PATH = Path("models/kokoro/voices-v1.0.bin")
DEFAULT_MODEL_PATH = DEFAULT_KOKORO_MODEL_PATH
DEFAULT_VOICES_PATH = DEFAULT_KOKORO_VOICES_PATH


class NarrationAdapterError(Exception):
    """Raised when audio verification or synthesis fails. Strictly fail-closed (no cloud fallbacks)."""
    pass


class BaseNarrationAdapter(ABC):
    @abstractmethod
    def prepare_audio(self, duration_seconds: float, output_path: Path, source_path: Optional[Path] = None) -> Path:
        """Prepares an audio file for the composition pipeline."""
        pass


class SilentNarrationAdapter(BaseNarrationAdapter):
    """Generates a silent stereo audio track matching the project duration."""

    def prepare_audio(self, duration_seconds: float, output_path: Path, source_path: Optional[Path] = None) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", "anullsrc=r=44100:cl=stereo",
            "-t", str(duration_seconds),
            "-c:a", "aac",
            "-b:a", "128k",
            str(output_path)
        ]
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            raise NarrationAdapterError(f"Failed to generate silent audio track: {res.stderr}")
        return output_path


class ManualAudioAdapter(BaseNarrationAdapter):
    """Verifies and ingests a user-provided audio file."""

    def verify_audio(self, audio_path: Path) -> Dict[str, Any]:
        if not audio_path.exists():
            raise NarrationAdapterError(f"Audio file not found: {audio_path}")

        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration,size,bit_rate:stream=codec_name,channels,sample_rate",
            "-of", "json",
            str(audio_path)
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise NarrationAdapterError(f"ffprobe failed to read audio file: {res.stderr}")

        data = json.loads(res.stdout)
        streams = data.get("streams", [])
        if not streams:
            raise NarrationAdapterError("Uploaded file does not contain a valid audio stream.")

        fmt = data.get("format", {})
        return {
            "codec": streams[0].get("codec_name"),
            "channels": streams[0].get("channels"),
            "sample_rate": streams[0].get("sample_rate"),
            "duration": float(fmt.get("duration", 0.0)),
            "size": int(fmt.get("size", 0))
        }

    def prepare_audio(self, duration_seconds: float, output_path: Path, source_path: Optional[Path] = None) -> Path:
        if not source_path or not source_path.exists():
            raise NarrationAdapterError("Source audio file must be provided for manual_audio mode.")
        
        info = self.verify_audio(source_path)
        return source_path


class LocalTTSAdapter(BaseNarrationAdapter):
    """
    Local neural TTS adapter using Kokoro-82M FP16 via ONNX Runtime on CPU.
    Zero recurring cost, strictly fail-closed, with deterministic checksum verification.
    """

    def __init__(
        self,
        model_path: Path = DEFAULT_KOKORO_MODEL_PATH,
        voices_path: Path = DEFAULT_VOICES_PATH,
        lazy_load: bool = True
    ):
        self.model_path = Path(model_path)
        self.voices_path = Path(voices_path)
        self._kokoro = None
        if not lazy_load:
            self._ensure_loaded()

    def _ensure_loaded(self):
        """Loads and configures Kokoro ONNX model and voice vectors."""
        if self._kokoro is not None:
            return

        if not self.model_path.exists():
            raise NarrationAdapterError(f"Kokoro ONNX model file not found at: {self.model_path}")
        if not self.voices_path.exists():
            raise NarrationAdapterError(f"Kokoro voices file not found at: {self.voices_path}")

        try:
            import onnxruntime as ort
            import numpy as np
            from kokoro_onnx import Kokoro

            sess_options = ort.SessionOptions()
            sess_options.log_severity_level = 3  # Suppress internal CPU reciprocal warnings
            sess = ort.InferenceSession(str(self.model_path), sess_options=sess_options, providers=["CPUExecutionProvider"])
            kokoro = Kokoro.from_session(sess, str(self.voices_path))

            # Monkey-patch _create_audio to fix kokoro-onnx 0.4.7 speed tensor dtype incompatibility
            # kokoro-onnx 0.4.7 hardcodes np.int32 for speed when input_ids is present,
            # but kokoro-v1.0.fp16.onnx declares speed as tensor(float) (np.float32).
            def patched_create_audio(phonemes, voice, speed):
                tokens = np.array(kokoro.tokenizer.tokenize(phonemes[:510]), dtype=np.int64)
                voice_vec = voice[len(tokens)]
                tokens_padded = [[0, *tokens, 0]]
                speed_type = np.float32
                for inp in kokoro.sess.get_inputs():
                    if inp.name == "speed" and "int" in inp.type:
                        speed_type = np.int32
                        break
                inputs = {
                    "input_ids": tokens_padded,
                    "style": np.array(voice_vec, dtype=np.float32),
                    "speed": np.array([speed], dtype=speed_type),
                }
                audio = kokoro.sess.run(None, inputs)[0]
                return audio, 24000

            kokoro._create_audio = patched_create_audio
            self._kokoro = kokoro
            logger.info("Local Kokoro TTS engine initialized successfully.")
        except Exception as e:
            raise NarrationAdapterError(f"Failed to initialize Kokoro TTS engine: {e}") from e

    def get_available_voices(self) -> List[str]:
        """Returns sorted list of all available voice identifiers."""
        self._ensure_loaded()
        return self._kokoro.get_voices()

    def synthesize(
        self,
        text: str,
        output_path: Path,
        voice: str = "af_bella",
        speed: float = 1.0,
        lang: str = "en-us"
    ) -> Dict[str, Any]:
        """
        Synthesizes text to a 24 kHz WAV file.
        Returns metadata dict including deterministic SHA-256 checksum and audio duration.
        """
        if not text or not text.strip():
            raise NarrationAdapterError("Cannot synthesize narration: input text is empty.")

        if not (0.5 <= speed <= 2.0):
            raise NarrationAdapterError(f"Speed {speed} out of valid range (0.5 to 2.0).")

        self._ensure_loaded()

        available_voices = self._kokoro.voices
        if voice not in available_voices:
            raise NarrationAdapterError(
                f"Unsupported voice '{voice}'. Choose from {len(available_voices)} available voices."
            )

        try:
            audio, sample_rate = self._kokoro.create(
                text=text.strip(),
                voice=voice,
                speed=speed,
                lang=lang
            )
        except Exception as e:
            raise NarrationAdapterError(f"TTS inference failed for lang='{lang}', voice='{voice}': {e}") from e

        if audio is None or len(audio) == 0:
            raise NarrationAdapterError("TTS inference produced empty audio.")

        import soundfile as sf
        output_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(output_path), audio, sample_rate)

        # Compute deterministic SHA-256
        hasher = hashlib.sha256()
        with output_path.open("rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        checksum = hasher.hexdigest()

        duration = len(audio) / float(sample_rate)
        return {
            "output_path": str(output_path),
            "checksum": checksum,
            "duration": duration,
            "sample_rate": sample_rate,
            "samples": len(audio),
            "channels": 1,
            "voice": voice,
            "lang": lang
        }

    def prepare_audio(
        self,
        duration_seconds: float,
        output_path: Path,
        source_path: Optional[Path] = None,
        text: Optional[str] = None,
        voice: str = "af_bella",
        speed: float = 1.0,
        lang: str = "en-us",
        pad_to_duration: bool = True
    ) -> Path:
        """
        Prepares narration audio for the FFmpeg composition pipeline.
        If text is given, synthesizes speech via Kokoro.
        If pad_to_duration is True, pads trailing silence up to duration_seconds so video doesn't cut prematurely.
        """
        import soundfile as sf
        import numpy as np

        script_text = text
        if not script_text and source_path and Path(source_path).exists():
            # Check if source_path is a text file
            try:
                content = Path(source_path).read_text(encoding="utf-8").strip()
                if content:
                    script_text = content
            except Exception:
                pass

        if not script_text:
            raise NarrationAdapterError("Text must be provided for local TTS synthesis.")

        self._ensure_loaded()
        if voice not in self._kokoro.voices:
            raise NarrationAdapterError(f"Unsupported voice '{voice}'.")

        try:
            audio, sample_rate = self._kokoro.create(
                text=script_text.strip(),
                voice=voice,
                speed=speed,
                lang=lang
            )
        except Exception as e:
            raise NarrationAdapterError(f"TTS inference failed: {e}") from e

        if audio is None or len(audio) == 0:
            raise NarrationAdapterError("TTS inference produced empty audio.")

        # Pad with trailing silence if shorter than target duration
        if pad_to_duration and duration_seconds > 0:
            target_samples = int(duration_seconds * sample_rate)
            if len(audio) < target_samples:
                silence = np.zeros(target_samples - len(audio), dtype=audio.dtype)
                audio = np.concatenate([audio, silence])

        output_path.parent.mkdir(parents=True, exist_ok=True)

        if output_path.suffix.lower() == ".aac":
            # Write temp wav and encode to AAC via FFmpeg
            temp_wav = output_path.with_suffix(".tmp.wav")
            sf.write(str(temp_wav), audio, sample_rate)
            cmd = [
                "ffmpeg", "-y",
                "-i", str(temp_wav),
                "-c:a", "aac",
                "-b:a", "128k",
                str(output_path)
            ]
            res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            if temp_wav.exists():
                temp_wav.unlink()
            if res.returncode != 0:
                raise NarrationAdapterError(f"Failed to encode synthesized audio to AAC: {res.stderr}")
        else:
            sf.write(str(output_path), audio, sample_rate)

        return output_path


def get_narration_adapter(mode: str) -> BaseNarrationAdapter:
    if mode == "silent":
        return SilentNarrationAdapter()
    elif mode == "manual_audio":
        return ManualAudioAdapter()
    elif mode == "local_tts":
        return LocalTTSAdapter()
    else:
        raise ValueError(f"Unsupported narration mode '{mode}'. Choose 'silent', 'manual_audio', or 'local_tts'.")
