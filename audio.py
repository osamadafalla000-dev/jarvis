"""Microphone capture, wake-word detection, local STT, and TTS playback."""

from __future__ import annotations

import asyncio
import queue
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000
WAKE_CHUNK_SAMPLES = 1280  # openWakeWord expects 80ms (1280 samples @ 16kHz) frames
WAKE_WORD_MODEL = "hey_jarvis"
TTS_VOICE = "en-GB-RyanNeural"
_ACK_CACHE_PATH = Path(tempfile.gettempdir()) / "jarvis_ack.mp3"
_ack_ready = False


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

    def wait_for_wake_word(self, stop_event: threading.Event | None = None) -> bool:
        """Blocks until the wake word is heard, returning True. If stop_event
        is given, also bails out early (returning False) once it's set --
        used to stop listening for an interrupt once Jarvis is done talking."""
        self.model.reset()
        # Drain anything queued from a previous run so a stale chunk can't
        # trigger an instant "detection" the moment we start listening again.
        with self._queue.mutex:
            self._queue.queue.clear()
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=WAKE_CHUNK_SAMPLES,
            callback=self._callback,
        ):
            while stop_event is None or not stop_event.is_set():
                try:
                    chunk = self._queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                predictions = self.model.predict(chunk)
                if predictions.get(WAKE_WORD_MODEL, 0.0) >= self.threshold:
                    return True
        return False


def record_utterance(
    max_seconds: float = 10.0,
    silence_seconds: float = 1.2,
    initial_wait_seconds: float | None = None,
) -> np.ndarray:
    """Record from the mic until the user stops talking (simple energy-based VAD).

    If initial_wait_seconds is given, recording gives up early (returning
    whatever silence it captured, which transcribes to "") if the user never
    starts talking within that window -- used for follow-up conversation
    turns, where silence means "done talking to Jarvis", as opposed to the
    turn right after the wake word, where the user is already mid-sentence.
    """
    silence_rms_threshold = 300.0  # int16 RMS; adjust if the mic is very quiet/loud
    block_seconds = 0.2
    block_samples = int(SAMPLE_RATE * block_seconds)
    max_blocks = int(max_seconds / block_seconds)
    silence_blocks_needed = int(silence_seconds / block_seconds)
    initial_wait_blocks = (
        int(initial_wait_seconds / block_seconds) if initial_wait_seconds is not None else None
    )

    frames: list[np.ndarray] = []
    silence_run = 0
    heard_speech = False

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16") as stream:
        for block_index in range(max_blocks):
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
            elif initial_wait_blocks is not None and block_index + 1 >= initial_wait_blocks:
                break  # gave up waiting for the user to start talking

    audio_int16 = np.concatenate(frames) if frames else np.zeros(0, dtype=np.int16)
    return audio_int16.astype(np.float32) / 32768.0


def warm_up_ack() -> None:
    """Pre-synthesize the "hey" acknowledgment once (at startup) so it's a
    local file by the time the wake word first fires -- playing it back then
    costs no network round trip, so it can play essentially instantly."""
    global _ack_ready
    if _ack_ready:
        return
    import edge_tts

    async def _save():
        communicate = edge_tts.Communicate("Hey.", voice=TTS_VOICE)
        await communicate.save(str(_ACK_CACHE_PATH))

    asyncio.run(_save())
    _ack_ready = True


def play_ack() -> None:
    """Instantly acknowledge the wake word. Falls back to a live (slower)
    TTS call if warm_up_ack() hasn't run yet."""
    if not _ack_ready or not _ACK_CACHE_PATH.exists():
        speak("Hey.")
        return
    subprocess.run(
        ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(_ACK_CACHE_PATH)],
        check=False,
    )


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


def speak(text: str, interrupt_listener: "WakeWordListener | None" = None) -> bool:
    """Speak text, streaming synthesized audio straight into ffplay's stdin as
    it arrives instead of waiting for the whole clip to render to disk first
    -- this is what makes playback start almost immediately.

    If interrupt_listener is given, it listens for the wake word on the mic
    while Jarvis is talking; hearing it again cuts playback off. Returns True
    if playback was interrupted that way (so the caller can skip straight to
    recording the next command instead of waiting for the wake word again).
    """
    if not text:
        return False
    import edge_tts

    process = subprocess.Popen(
        ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", "-f", "mp3", "pipe:0"],
        stdin=subprocess.PIPE,
    )

    stop_listening = threading.Event()
    interrupted = threading.Event()

    def _watch_for_interrupt():
        if interrupt_listener is not None and interrupt_listener.wait_for_wake_word(stop_listening):
            interrupted.set()
            process.terminate()

    watcher = None
    if interrupt_listener is not None:
        watcher = threading.Thread(target=_watch_for_interrupt, daemon=True)
        watcher.start()

    async def _stream():
        communicate = edge_tts.Communicate(text, voice=TTS_VOICE)
        async for chunk in communicate.stream():
            if chunk["type"] != "audio":
                continue
            if process.stdin is None or process.stdin.closed:
                return
            try:
                process.stdin.write(chunk["data"])
                process.stdin.flush()
            except (BrokenPipeError, OSError):
                return  # ffplay already exited (e.g. interrupted)

    try:
        asyncio.run(_stream())
    finally:
        if process.stdin is not None and not process.stdin.closed:
            try:
                process.stdin.close()
            except OSError:
                pass
        process.wait()
        stop_listening.set()
        if watcher is not None:
            watcher.join(timeout=1)

    return interrupted.is_set()


def check_ffplay_available() -> bool:
    from shutil import which

    return which("ffplay") is not None


if __name__ == "__main__":
    # Quick manual check: `python audio.py` speaks a test sentence.
    if not check_ffplay_available():
        print("ffplay not found on PATH — install ffmpeg to enable speech playback.")
        sys.exit(1)
    speak("Jarvis audio pipeline is online.")
