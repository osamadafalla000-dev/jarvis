"""Jarvis entry point: wake word -> listen -> think -> speak."""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Windows' default console codepage (cp1252) can't encode some characters
# models like to use (narrow no-break spaces, em dashes, etc.) — force UTF-8.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _discard_attachments(jarvis) -> None:
    """The desktop front-end is voice-only — drop any files tools produced
    (e.g. describe_screen's screenshot) instead of leaving them on disk."""
    for path in jarvis.last_attachments:
        Path(path).unlink(missing_ok=True)


def run_text(query: str) -> None:
    """Send one text query straight to the brain, no audio involved."""
    from llm import Jarvis

    jarvis = Jarvis()
    print(jarvis.ask(query))
    _discard_attachments(jarvis)


def run_once() -> None:
    """One push-to-talk turn (press Enter to record) — no wake word needed.

    Useful for verifying the mic/STT/LLM/TTS pipeline without first tuning
    the wake-word threshold.
    """
    import audio
    from llm import Jarvis

    input("Press Enter, then get ready to speak...")
    for n in (3, 2, 1):
        print(n, flush=True)
        time.sleep(1)
    print("Listening...")
    recording = audio.record_utterance()
    text = audio.transcribe(recording)
    print(f"You said: {text}")
    if not text:
        print("(heard nothing, exiting)")
        return

    jarvis = Jarvis()
    reply = jarvis.ask(text)
    print(f"Jarvis: {reply}")
    audio.speak(reply)
    _discard_attachments(jarvis)


FOLLOW_UP_SILENCE_SECONDS = 6.0  # how long to wait for a follow-up before going back to sleep

# Words that don't count as an actual request on their own -- just the wake
# word, or a bare greeting, with nothing else said.
_FILLER_WORDS = {"jarvis", "hey", "yo", "hi", "hello", "ok", "okay", "um", "uh"}


def _is_just_the_wake_word(text: str) -> bool:
    """True if text has no real content beyond the name itself/greeting
    filler -- e.g. just "Jarvis" or "Hey Jarvis" with nothing following.
    Covers both a false wake-word trigger on the bare name (someone talking
    ABOUT Jarvis, not TO it) and trailing off right after saying it -- either
    way, there's no actual request here to answer."""
    words = re.findall(r"[a-zA-Z']+", text.lower())
    return bool(words) and all(w in _FILLER_WORDS for w in words)


def run_loop() -> None:
    """The real assistant loop: always-on wake word -> converse -> repeat.

    "Hey jarvis, <command>" works said in one breath -- listen_for_command()
    keeps the mic stream open across wake-word detection and command
    recording, so nothing said right up against "jarvis" gets clipped.

    After Jarvis answers, it keeps listening for a few seconds without
    requiring the wake word again -- so a real back-and-forth doesn't need
    "hey jarvis" before every line. Staying silent for FOLLOW_UP_SILENCE_SECONDS
    ends the conversation and puts it back to sleep, waiting for the wake word.
    """
    import threading

    import audio
    import heartbeat_client
    from llm import Jarvis

    print("Downloading/verifying wake-word models (first run only)...")
    audio.ensure_wakeword_models()
    audio.warm_up_ack()
    # No-ops unless JARVIS_HEARTBEAT_URL is set (i.e. a cloud relay is
    # actually configured to receive it) -- see heartbeat_client.py.
    heartbeat_client.start_if_configured()

    jarvis = Jarvis()
    listener = audio.WakeWordListener()

    def _play_ack_async() -> None:
        # Fire-and-forget so it doesn't delay capturing whatever's said
        # right after "hey jarvis" in the same breath.
        threading.Thread(target=audio.play_ack, daemon=True).start()

    print(
        'Jarvis is listening for "hey jarvis"... say your command in the '
        'same breath, no need to pause after the wake word. Keep talking '
        'after it answers and it\'ll follow along without saying "hey '
        'jarvis" again. Say it again anytime to interrupt it mid-sentence. '
        'Ctrl+C to quit.'
    )
    while True:
        print("Listening...")
        recording = listener.listen_for_command(on_detected=_play_ack_async)
        while True:
            text = audio.transcribe(recording)
            if not text or _is_just_the_wake_word(text):
                break  # silence, or just the name/a greeting -- nothing to answer, go back to sleep
            print(f"You said: {text}")
            reply = jarvis.ask(text)
            print(f"Jarvis: {reply}")
            interrupted = audio.speak(reply, interrupt_listener=listener)
            _discard_attachments(jarvis)
            if interrupted:
                _play_ack_async()  # they said "hey jarvis" again -- acknowledge and keep going
            print("Listening...")
            recording = audio.record_utterance(initial_wait_seconds=FOLLOW_UP_SILENCE_SECONDS)


def main() -> None:
    parser = argparse.ArgumentParser(description="Jarvis voice assistant")
    parser.add_argument(
        "--text", metavar="QUERY", help="send one text query directly (no audio)"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="one push-to-talk turn (press Enter to record), skips wake-word",
    )
    args = parser.parse_args()

    try:
        if args.text:
            run_text(args.text)
        elif args.once:
            run_once()
        else:
            run_loop()
    except KeyboardInterrupt:
        print("\nShutting down.")
        sys.exit(0)


if __name__ == "__main__":
    main()
