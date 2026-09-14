"""Microphone capture, wake-word detection, local STT, and TTS playback."""

from __future__ import annotations

import asyncio
import queue
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000
WAKE_CHUNK_SAMPLES = 1280  # openWakeWord expects 80ms (1280 samples @ 16kHz) frames
WAKE_WORD_MODEL = "hey_jarvis"
TTS_VOICE = "en-GB-RyanNeural"


def ensure_wakeword_models() -> None:
    """Download openWakeWord's pretrained ONNX models on first run (one-time, free)."""
    import openwakeword

    openwakeword.utils.download_models()


class WakeWordListener:
    """Blocks until the "hey jarvis" wake word is heard on the default mic."""

    def __init__(self, threshold: float = 0.5):
        from openwakeword.model import Model

        self.model = Model(wakeword_models=[WAKE_WORD_MODEL])
        self.threshold = threshold
        self._queue: queue.Queue[np.ndarray] = queue.Queue()

    def _callback(self, indata, frames, time_info, status):  # noqa: ARG002
        self._queue.put(indata[:, 0].copy())

    def wait_for_wake_word(self) -> None:
        self.model.reset()
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=WAKE_CHUNK_SAMPLES,
            callback=self._callback,
        ):
            while True:
                chunk = self._queue.get()
                predictions = self.model.predict(chunk)
                if predictions.get(WAKE_WORD_MODEL, 0.0) >= self.threshold:
                    return


def record_utterance(max_seconds: float = 10.0, silence_seconds: float = 1.2) -> np.ndarray:
    """Record from the mic until the user stops talking (simple energy-based VAD)."""
    silence_rms_threshold = 300.0  # int16 RMS; adjust if the mic is very quiet/loud
    block_seconds = 0.2
    block_samples = int(SAMPLE_RATE * block_seconds)
    max_blocks = int(max_seconds / block_seconds)
    silence_blocks_needed = int(silence_seconds / block_seconds)

    frames: list[np.ndarray] = []
    silence_run = 0
    heard_speech = False

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16") as stream:
        for _ in range(max_blocks):
            block, _ = stream.read(block_samples)
            block = block[:, 0]
            frames.append(block)
            rms = float(np.sqrt(np.mean(block.astype(np.float64) ** 2)))
            if rms >= silence_rms_threshold:
                heard_speech = True
                silence_run = 0
            elif heard_speech:
                silence_run += 1
                if silence_run >= silence_blocks_needed:
                    break

    audio_int16 = np.concatenate(frames) if frames else np.zeros(0, dtype=np.int16)
    return audio_int16.astype(np.float32) / 32768.0


_whisper_model = None


def transcribe(audio_input: np.ndarray | str) -> str:
    """Transcribe either an in-memory float32 mono array or a path to an audio file
    (faster-whisper decodes most formats itself, e.g. Telegram's .ogg voice notes)."""
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel

        _whisper_model = WhisperModel("small", device="cpu", compute_type="int8")

    segments, _ = _whisper_model.transcribe(audio_input, language="en", vad_filter=True)
    return " ".join(segment.text.strip() for segment in segments).strip()


def speak(text: str) -> None:
    if not text:
        return
    import edge_tts

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        mp3_path = Path(tmp.name)

    async def _save():
        communicate = edge_tts.Communicate(text, voice=TTS_VOICE)
        await communicate.save(str(mp3_path))

    try:
        asyncio.run(_save())
        subprocess.run(
            ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(mp3_path)],
            check=False,
        )
    finally:
        mp3_path.unlink(missing_ok=True)


def check_ffplay_available() -> bool:
    from shutil import which

    return which("ffplay") is not None


if __name__ == "__main__":
    # Quick manual check: `python audio.py` speaks a test sentence.
    if not check_ffplay_available():
        print("ffplay not found on PATH — install ffmpeg to enable speech playback.")
        sys.exit(1)
    speak("Jarvis audio pipeline is online.")
