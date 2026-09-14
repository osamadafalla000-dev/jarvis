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
   Check the console the bot is running in — it logs `Message from chat id:
   1234...`. Copy that number into `.env` as `TELEGRAM_ALLOWED_CHAT_ID`,
   then restart `telegram_bot.py`. This locks the bot to only you, so a
   leaked bot token can't let a stranger read your calendar/files/etc.
   (Until you set this, the bot will answer *anyone* who messages it.)
5. **Chat normally** — text or send a voice note. Telegram replies are
   **text-only** (plus an image if a tool attaches one, e.g. a screenshot).
   Spoken voice replies only happen on the desktop version (`main.py`),
   since that's the "talking out loud" front-end — no wake word needed on
   Telegram since messaging it is the "wake up".

## Calendar, email, notes, and web search (Phase 2)

**Notes and web search work immediately, no setup needed.** Calendar and
email need a one-time free Google Cloud OAuth setup:

1. Go to https://console.cloud.google.com/ , create a project (free).
2. **APIs & Services -> Library**: enable the **Google Calendar API** and
   the **Gmail API**.
3. **APIs & Services -> OAuth consent screen**: set it up as "External" +
   "Testing" mode, add your own Google account as a test user.
4. **APIs & Services -> Credentials -> Create Credentials -> OAuth client
   ID**, application type **Desktop app**. Download the JSON.
5. Save the downloaded file as `credentials.json` in this project's root
   folder (already git-ignored).
6. The first time a calendar/email tool actually runs, a browser window
   opens asking you to sign in and consent — after that, a `token.json` is
   cached locally (also git-ignored) so you won't be asked again.

Everything after that is read-only for email/calendar **except** creating
drafts — Jarvis can draft a reply, but never calls a "send" endpoint, so
every draft sits in Gmail until you personally open it and hit send.

## Screen vision (Phase 3)

Groq has no working free vision model for this account, so screen vision
runs entirely **locally** instead via [Ollama](https://ollama.com) (free)
serving the small `moondream` vision model — no cloud, no API key.

1. Install Ollama: `winget install Ollama.Ollama` (it runs automatically
   as a background service afterward — check with `ollama --version`).
2. Pull the vision model once: `ollama pull moondream` (~1.7 GB, one-time).
3. That's it — `describe_screen` will work as soon as Ollama is running.

## Browser automation (Phase 3)

Uses [Playwright](https://playwright.dev) (free, open-source) to drive
Jarvis's own **persistent, visible Google Chrome window** (`browser_session.py`
— the real installed Chrome via Playwright's `channel="chrome"`, not Edge
and not Playwright's bundled Chromium, and not a fresh throwaway browser
per action — one window, real tabs, kept open across tool calls).

- `open_url` and `browser_fill_and_submit` both open tabs in this shared
  Chrome window instead of the system default browser.
- `browser_fill_and_submit` fills one form field, submits it, waits for the
  result page to actually finish loading (not just DOM-ready — a much
  stronger "networkidle" signal, bounded to 8s so a stuck page can't hang
  the tool), then screenshots that result page directly as part of the same
  call — no separate follow-up screenshot request needed.
- `list_open_tabs` / `close_tab` manage tabs (by index or a text hint
  matching the title/URL) — tabs stick around until explicitly closed.

Setup:
1. `pip install playwright` (already in `requirements.txt`)
2. Google Chrome must be installed normally (not managed by Playwright)

**Known limitation:** sites with aggressive bot-detection (Google search
being the biggest example) will block or CAPTCHA-challenge an automated
browser — confirmed by testing. For anything search-related, the `web_search`
tool is the reliable path since it doesn't drive a real browser at all.
Browser automation is best reserved for ordinary forms/websites (confirmed
working against Wikipedia's search box, including the full open -> fill ->
wait -> screenshot -> close-tab flow).

## What's built so far

**Phase 1 — core voice loop:**
- Full voice loop: wake word -> record -> transcribe -> think -> speak

**Phone access — Telegram bot:**
- Text or voice-note conversations with Jarvis from anywhere, free,
  no tunneling. Text-only replies (plus images when a tool attaches one).
- Locked to one authorized chat id so it can't be hijacked by a stranger.

**Phase 2 — tools:**
- `get_current_datetime`, `open_application`, `open_url`, `search_files`
  (Downloads/Documents/Desktop)
- `get_calendar_events` — Google Calendar, read-only
- `get_unread_emails`, `create_email_draft` — Gmail, read + draft-only
  (never auto-sends)
- `search_notes`, `add_note` — local Markdown "second brain" in `notes/`
  (git-ignored, stays on your machine)
- `web_search` — free, no API key, via DDGS

**Phase 3 — tools:**
- `describe_screen` — local screen vision via Ollama + moondream, free
- `browser_fill_and_submit`, `list_open_tabs`, `close_tab` — persistent
  Chrome window with real, manageable tabs

**Personality:** casual, dry-witted, talks like a sharp friend texting
back rather than a formal assistant — light slang/emoji only when it
genuinely fits (max one per reply), never forced in. Tuned based on
research into what actually reads as authentic vs. "trying too hard."

## Not built (by design)

- **No phone calls** — excluded on purpose, no Twilio/Vapi/phone number of
  any kind.

## Notes

- All processing after the wake word triggers goes to Groq's cloud API
  (for the LLM) — wake-word detection and STT run fully locally, so no
  audio leaves your machine until you've actually said "hey jarvis" and
  started talking.
- If wake-word detection is too sensitive or not sensitive enough, tweak
  the `threshold` passed to `WakeWordListener` in `main.py`.
