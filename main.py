"""Jarvis entry point: wake word -> listen -> think -> speak."""

from __future__ import annotations

import argparse
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


def run_loop() -> None:
    """The real assistant loop: always-on wake word -> converse -> repeat."""
    import audio
    from llm import Jarvis

    print("Downloading/verifying wake-word models (first run only)...")
    audio.ensure_wakeword_models()

    jarvis = Jarvis()
    listener = audio.WakeWordListener()

    print('Jarvis is listening for "hey jarvis"... (Ctrl+C to quit)')
    while True:
        listener.wait_for_wake_word()
        print("Wake word heard — listening...")
        recording = audio.record_utterance()
        text = audio.transcribe(recording)
        if not text:
            continue
        print(f"You said: {text}")
        reply = jarvis.ask(text)
        print(f"Jarvis: {reply}")
        audio.speak(reply)
        _discard_attachments(jarvis)


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
