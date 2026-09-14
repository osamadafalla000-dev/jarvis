# Jarvis (free, local voice assistant)

A "Hey Jarvis" voice assistant built entirely from free components: no paid
APIs, no subscriptions, no phone integration.

- **Wake word:** [openWakeWord](https://github.com/dscripka/openWakeWord) (local, pretrained "hey jarvis" model)
- **Speech-to-text:** `faster-whisper` (local, runs on CPU)
- **Brain:** [Groq](https://console.groq.com) free API tier, `openai/gpt-oss-120b`, with tool-calling
- **Text-to-speech:** [`edge-tts`](https://github.com/rany2/edge-tts) (free, no key)

## Setup (Windows)

1. **Install ffmpeg** (provides `ffplay`, used to play back speech):
   `winget install Gyan.FFmpeg` (skip if already installed — check with `ffplay -version`)

2. **Create a virtual environment and install dependencies:**
   ```
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Get a free Groq API key:** sign up at https://console.groq.com/keys
   (no credit card required for the free tier).

4. **Add your key:**
   ```
   copy .env.example .env
   ```
   Then edit `.env` and set `GROQ_API_KEY=your-key-here`.

5. **Grant microphone access** to Python when Windows prompts for it on first run.

## Running it

```
python main.py
```

Say **"Hey Jarvis"**, wait for it to start listening, then speak your
command. It'll transcribe, think (with tool access to the clock, apps,
URLs, and local file search), and speak the reply back.

### Faster ways to test without a live mic loop

- `python main.py --text "what time is it?"` — sends one text query straight
  to the brain, no audio involved. Fastest way to check the LLM + tools.
- `python main.py --once` — one push-to-talk turn (press Enter, then speak).
  Skips wake-word detection, useful for checking the mic/STT/TTS pipeline
  without first tuning the wake-word sensitivity.
- `python audio.py` — plays a one-line test sentence to confirm TTS
  playback (`ffplay`) works at all.

## Using it from your phone (Telegram bot)

Runs via long-polling — no port-forwarding, public IP, or paid tunnel
needed. Your PC just needs to be on and running the script.

1. **Create a free bot:** open Telegram, message **@BotFather**, send
   `/newbot`, follow the prompts. It gives you a token.
2. **Add the token to `.env`:** set `TELEGRAM_BOT_TOKEN=your-token-here`.
3. **Run the bot:**
   ```
   python telegram_bot.py
   ```
4. **Message your bot** from your phone (search its @username in Telegram).
   The first message comes back with *"Not authorized. Your chat id is
   1234..."* — copy that number into `.env` as `TELEGRAM_ALLOWED_CHAT_ID`,
   then restart `telegram_bot.py`. This locks the bot to only you, so a
   leaked bot token can't let a stranger read your calendar/files/etc.
5. **Chat normally** — text or send a voice note. It replies with text
   *and* a spoken voice note (same brain, same tools, as the desktop
   version — just no wake word needed since messaging it is the "wake up").

## What's built so far

**Phase 1 — core voice loop:**
- Full voice loop: wake word -> record -> transcribe -> think -> speak
- Tools: current date/time, open an application, open a URL, search local
  files (Downloads/Documents/Desktop)

**Phone access — Telegram bot:**
- Text or voice-note conversations with Jarvis from anywhere, free,
  no tunneling. Replies with text + a spoken voice note.
- Locked to one authorized chat id so it can't be hijacked by a stranger.

## Not built (by design)

- **No phone calls** — excluded on purpose, no Twilio/Vapi/phone number of
  any kind.
- Calendar, email, notes search, web search — planned for Phase 2.
- Screen vision, browser automation — optional Phase 3 stretch goals.

## Notes

- All processing after the wake word triggers goes to Groq's cloud API
  (for the LLM) — wake-word detection and STT run fully locally, so no
  audio leaves your machine until you've actually said "hey jarvis" and
  started talking.
- If wake-word detection is too sensitive or not sensitive enough, tweak
  the `threshold` passed to `WakeWordListener` in `main.py`.
