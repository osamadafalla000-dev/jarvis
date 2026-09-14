"""Telegram front-end for Jarvis — chat with it from your phone, for free.

Runs via long-polling (Telegram's servers are polled by this script), so
there's no port-forwarding, public IP, or paid tunnel needed. The PC running
this script just needs to be on and connected to the internet.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import os

from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import audio
from llm import Jarvis

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
ALLOWED_CHAT_ID = os.environ.get("TELEGRAM_ALLOWED_CHAT_ID")

# One conversation history per Telegram chat, so multiple chats don't bleed
# into each other's context.
_sessions: dict[int, Jarvis] = {}


def _get_jarvis(chat_id: int) -> Jarvis:
    if chat_id not in _sessions:
        _sessions[chat_id] = Jarvis()
    return _sessions[chat_id]


async def _speak_to_voice_note(text: str) -> Path | None:
    """Generate a spoken reply and transcode it to Opus/OGG for a real Telegram
    voice-note bubble (Telegram only renders send_voice as a voice bubble for
    Opus-in-OGG; edge-tts itself only outputs mp3)."""
    import edge_tts

    mp3_path = Path(tempfile.mktemp(suffix=".mp3"))
    ogg_path = Path(tempfile.mktemp(suffix=".ogg"))

    try:
        communicate = edge_tts.Communicate(text, voice=audio.TTS_VOICE)
        await communicate.save(str(mp3_path))
        result = await asyncio.to_thread(
            subprocess.run,
            ["ffmpeg", "-y", "-i", str(mp3_path), "-c:a", "libopus", str(ogg_path)],
            capture_output=True,
        )
        if result.returncode != 0 or not ogg_path.exists():
            return None
        return ogg_path
    finally:
        mp3_path.unlink(missing_ok=True)


async def _handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:  # noqa: ARG001
    message = update.message
    if message is None:
        return
    chat_id = update.effective_chat.id
    print(f"Message from chat id: {chat_id}", flush=True)

    if ALLOWED_CHAT_ID and str(chat_id) != str(ALLOWED_CHAT_ID):
        await message.reply_text(
            f"Not authorized. Your chat id is {chat_id} — add it to .env as "
            f"TELEGRAM_ALLOWED_CHAT_ID and restart the bot."
        )
        return

    if message.voice:
        voice_file = await message.voice.get_file()
        ogg_path = Path(tempfile.mktemp(suffix=".ogg"))
        await voice_file.download_to_drive(str(ogg_path))
        try:
            text = audio.transcribe(str(ogg_path))
        finally:
            ogg_path.unlink(missing_ok=True)
    else:
        text = (message.text or "").strip()

    if not text:
        await message.reply_text("(didn't catch any words in that)")
        return

    jarvis = _get_jarvis(chat_id)
    reply = jarvis.ask(text)
    await message.reply_text(reply)

    voice_reply = await _speak_to_voice_note(reply)
    if voice_reply:
        try:
            with open(voice_reply, "rb") as f:
                await message.reply_voice(f)
        finally:
            voice_reply.unlink(missing_ok=True)


def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN is not set. Message @BotFather on Telegram to "
            "create a free bot and get a token, then add it to .env."
        )
    if not ALLOWED_CHAT_ID:
        print(
            "WARNING: TELEGRAM_ALLOWED_CHAT_ID is not set — anyone who finds "
            "this bot could use it. Message it once to learn your chat id, "
            "then add it to .env and restart.",
            file=sys.stderr,
        )

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT | filters.VOICE, _handle))
    print("Jarvis Telegram bot is running. Message your bot to talk to it. (Ctrl+C to stop)")
    app.run_polling()


if __name__ == "__main__":
    main()
