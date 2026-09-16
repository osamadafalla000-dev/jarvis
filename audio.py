"""Microphone capture, wake-word detection, local STT, and TTS playback."""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
import queue
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Callable

import numpy as np

try:
    # Needs PortAudio's native library, which requires actual audio
    # hardware/drivers -- absent on a headless cloud host running only
    # telegram_bot.py (which never touches live mic input, only
    # transcribe() on already-downloaded files). Importing audio.py at all
    # shouldn't crash there just because this one piece can't load; only
    # the mic-capture functions below (WakeWordListener, record_utterance)
    # actually need it, and they check SOUNDDEVICE_AVAILABLE themselves.
    import sounddevice as sd

    SOUNDDEVICE_AVAILABLE = True
except Exception:  # noqa: BLE001
    sd = None
    SOUNDDEVICE_AVAILABLE = False

SAMPLE_RATE = 16000
WAKE_CHUNK_SAMPLES = 1280  # openWakeWord expects 80ms (1280 samples @ 16kHz) frames
WAKE_WORD_MODEL = "hey_jarvis"
TTS_VOICE = "en-CA-LiamNeural"
# A livelier, more human delivery -- same voice and same wording (that's
# SYSTEM_PROMPT's job, in llm.py), just less flat/robotic prosody.
TTS_RATE = os.environ.get("JARVIS_TTS_RATE", "+8%")
TTS_PITCH = os.environ.get("JARVIS_TTS_PITCH", "+15Hz")
# int16 RMS below this counts as "silence" for end-of-utterance detection.
# Lowered from the historical 300 -- at 300, a normal mid-sentence dip in
# volume (trailing off at the end of a clause, a softer word) could read as
# "done talking" and get treated as a real pause. Adjust if the mic is very
# quiet/loud.
SILENCE_RMS_THRESHOLD = float(os.environ.get("JARVIS_SILENCE_RMS_THRESHOLD", "220"))
# How long a pause has to last before Jarvis decides you're done talking and
# moves on to answering. Bumped up from 1.2s -- that was cutting people off
# mid-thought on any natural pause longer than a beat (e.g. "use it." was all
# that got captured from a much longer sentence with a mid-thought pause).
COMMAND_SILENCE_SECONDS = float(os.environ.get("JARVIS_SILENCE_SECONDS", "1.8"))
# Lower threshold = accepts weaker/quieter matches (catches "hey jarvis" from
# further away, at the cost of more false triggers from ambient noise/TV --
# or from just saying "jarvis" with no "hey" in front of it, since a low
# threshold + high gain lets the model fire on a weak partial match to the
# back half of the phrase alone). Pulled back from 0.4/3.0 for exactly that
# reason. Both are tunable via env vars, since the right values depend on
# the room and mic.
WAKE_WORD_THRESHOLD = float(os.environ.get("JARVIS_WAKE_THRESHOLD", "0.5"))
WAKE_WORD_GAIN = float(os.environ.get("JARVIS_WAKE_GAIN", "2.0"))
# "small" was the dominant latency cost in the whole pipeline -- 5+ seconds
# to transcribe a 5-second utterance on this CPU (no usable GPU path: CUDA
# Toolkit isn't installed, only the driver). "base" measured 2.5x+ faster
# with byte-identical transcripts on test sentences including names and
# multi-clause commands. "tiny" was faster still but is known to degrade
# more on real noisy/accented speech than clean test audio, so "base" is
# the safer default; drop to "tiny" via env var if more speed is wanted.
WHISPER_MODEL_SIZE = os.environ.get("JARVIS_WHISPER_MODEL", "base")
_ACK_CACHE_PATH = Path(tempfile.gettempdir()) / "jarvis_ack.mp3"
_ack_ready = False


def _run_async(coro):
    """Run an asyncio coroutine to completion on a fresh worker thread.

    Playwright's sync API (used by the browser tools) marks whichever thread
    it's started on as permanently "inside a running event loop" for as
    long as the browser session stays open -- browser_session.py keeps it
    open across calls by design. asyncio.run() then fails on that thread
    for the rest of the process's life. Running our own asyncio work
    (TTS) on a throwaway thread sidesteps that entirely, regardless of
    whether the browser has been opened yet.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def ensure_wakeword_models() -> None:
    """Download openWakeWord's pretrained ONNX models on first run (one-time, free)."""
    import openwakeword

    openwakeword.utils.download_models()


class WakeWordListener:
    """Blocks until the "hey jarvis" wake word is heard on the default mic."""

    def __init__(self, threshold: float = WAKE_WORD_THRESHOLD, gain: float = WAKE_WORD_GAIN):
        if not SOUNDDEVICE_AVAILABLE:
            raise RuntimeError(
                "No usable audio input on this machine (sounddevice/PortAudio "
                "didn't load) -- live mic listening only works where there's "
                "real audio hardware, e.g. the laptop, not a headless server."
            )
        from openwakeword.model import Model

        self.model = Model(wakeword_models=[WAKE_WORD_MODEL])
        self.threshold = threshold
        self.gain = gain
        self._queue: queue.Queue[np.ndarray] = queue.Queue()

    def _callback(self, indata, frames, time_info, status):  # noqa: ARG002
        # Store the raw chunk -- gain is applied separately, only for wake-word
        # prediction (see _amplify), so anything recorded from this same
        # queue for an actual command isn't stuck at wake-word-detection gain.
        self._queue.put(indata[:, 0].copy())

    def _amplify(self, chunk: np.ndarray) -> np.ndarray:
        if self.gain == 1.0:
            return chunk
        # Widen to int32 first so loud input clips cleanly instead of
        # wrapping around int16.
        return np.clip(chunk.astype(np.int32) * self.gain, -32768, 32767).astype(np.int16)

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
                predictions = self.model.predict(self._amplify(chunk))
                if predictions.get(WAKE_WORD_MODEL, 0.0) >= self.threshold:
                    return True
        return False

    def listen_for_command(
        self,
        max_seconds: float = 10.0,
        silence_seconds: float = COMMAND_SILENCE_SECONDS,
        on_detected: "Callable[[], None] | None" = None,
    ) -> np.ndarray:
        """Wait for "hey jarvis", then seamlessly keep recording the command
        that follows on the SAME live mic stream -- so "hey jarvis, open
        chrome" said in one breath isn't clipped by closing the mic after
        detection and reopening a fresh stream for the command, which is
        what wait_for_wake_word() + record_utterance() used to do. Anything
        already queued the instant detection fires (spoken with zero gap
        right after "jarvis") is naturally picked up first, since nothing
        gets discarded between the two phases.

        on_detected, if given, is called the moment the wake word is heard
        (e.g. to fire off an ack sound) -- fire-and-forget, so it shouldn't
        block for long or it'll delay capturing the command.

        Returns recorded audio as float32 mono, same shape as record_utterance().
        """
        self.model.reset()
        with self._queue.mutex:
            self._queue.queue.clear()

        block_seconds = WAKE_CHUNK_SAMPLES / SAMPLE_RATE
        max_blocks = int(max_seconds / block_seconds)
        silence_blocks_needed = int(silence_seconds / block_seconds)

        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=WAKE_CHUNK_SAMPLES,
            callback=self._callback,
        ):
            # Phase 1: wait for the wake word.
            while True:
                chunk = self._queue.get()
                predictions = self.model.predict(self._amplify(chunk))
                if predictions.get(WAKE_WORD_MODEL, 0.0) >= self.threshold:
                    break

            if on_detected is not None:
                on_detected()

            # Phase 2: keep recording the command on the same live stream.
            frames: list[np.ndarray] = []
            silence_run = 0
            heard_speech = False
            for _ in range(max_blocks):
                try:
                    chunk = self._queue.get(timeout=1.0)
                except queue.Empty:
                    break
                frames.append(chunk)
                rms = float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2)))
                if rms >= SILENCE_RMS_THRESHOLD:
                    heard_speech = True
                    silence_run = 0
                elif heard_speech:
                    silence_run += 1
                    if silence_run >= silence_blocks_needed:
                        break

        audio_int16 = np.concatenate(frames) if frames else np.zeros(0, dtype=np.int16)
        return audio_int16.astype(np.float32) / 32768.0


def record_utterance(
    max_seconds: float = 10.0,
    silence_seconds: float = COMMAND_SILENCE_SECONDS,
    initial_wait_seconds: float | None = None,
) -> np.ndarray:
    """Record from the mic until the user stops talking (simple energy-based VAD).

    If initial_wait_seconds is given, recording gives up early (returning
    whatever silence it captured, which transcribes to "") if the user never
    starts talking within that window -- used for follow-up conversation
    turns, where silence means "done talking to Jarvis", as opposed to the
    turn right after the wake word, where the user is already mid-sentence.
    """
    block_seconds = 0.2
    block_samples = int(SAMPLE_RATE * block_seconds)
    max_blocks = int(max_seconds / block_seconds)
    silence_blocks_needed = int(silence_seconds / block_seconds)
    initial_wait_blocks = (
        int(initial_wait_seconds / block_seconds) if initial_wait_seconds is not None else None
    )

    if not SOUNDDEVICE_AVAILABLE:
        raise RuntimeError(
            "No usable audio input on this machine (sounddevice/PortAudio "
            "didn't load) -- live mic recording only works where there's "
            "real audio hardware, e.g. the laptop, not a headless server."
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
            if rms >= SILENCE_RMS_THRESHOLD:
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
        communicate = edge_tts.Communicate("Hey.", voice=TTS_VOICE, rate=TTS_RATE, pitch=TTS_PITCH)
        await communicate.save(str(_ACK_CACHE_PATH))

    _run_async(_save())
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

        _whisper_model = WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")

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
        communicate = edge_tts.Communicate(text, voice=TTS_VOICE, rate=TTS_RATE, pitch=TTS_PITCH)
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
        _run_async(_stream())
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
