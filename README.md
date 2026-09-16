# Jarvis (free, local voice assistant)

A "Hey Jarvis" voice assistant built entirely from free components: no paid
APIs, no subscriptions, no phone integration.

- **Wake word:** [openWakeWord](https://github.com/dscripka/openWakeWord) (local, pretrained "hey jarvis" model)
- **Speech-to-text:** `faster-whisper` (local, runs on CPU)
- **Brain:** [Gemini](https://aistudio.google.com) free API tier, `gemini-3.5-flash-lite`, with tool-calling
- **Text-to-speech:** [`edge-tts`](https://github.com/rany2/edge-tts) (free, no key)
- **Desktop control:** `pyautogui` (click/type into any window) + Tesseract OCR (find text on screen to click)

## Setup (Windows)

1. **Install ffmpeg** (provides `ffplay`, used to play back speech):
   `winget install Gyan.FFmpeg` (skip if already installed — check with `ffplay -version`)

1b. **Install Tesseract OCR** (used by `find_text_on_screen` to locate and click things by their on-screen text):
   `winget install --id tesseract-ocr.tesseract -e` — approve the UAC prompt if one appears.
   Without it, that one tool degrades to a clear error message; everything else still works.

2. **Create a virtual environment and install dependencies:**
   ```
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Get a free Gemini API key:** sign in at https://aistudio.google.com/apikey
   (no credit card required for the free tier).

4. **Add your key:**
   ```
   copy .env.example .env
   ```
   Then edit `.env` and set `GEMINI_API_KEY=your-key-here`.

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

## Auto-start at login (always-on, like a real assistant)

So you don't have to manually run `python main.py` / `python telegram_bot.py`
every time — both are set up to start automatically, hidden (no console
window), whenever you log into Windows.

**How it works:** `run_jarvis.vbs` and `run_telegram_bot.vbs` launch each
script hidden via `wscript.exe`, logging output to `jarvis_log.txt` /
`telegram_bot_log.txt` so you can check on them. Copies of both live in
your Startup folder (`shell:startup` — paste that into Windows Explorer's
address bar to open it), which Windows runs automatically at every logon.

Both scripts also run `git pull` (logged to `update_log.txt`) before
starting Python, so every restart automatically picks up the latest fixes
from this repo with no manual step — **only if the project folder is
itself a git checkout** (i.e. you got it via `git clone`, not by
downloading/extracting a zip). If it's not a git checkout, the pull just
fails silently and Jarvis starts on whatever code is already there; run
`git clone` once to switch it over, or keep pulling by hand as before.

(Task Scheduler would normally be the more robust way to do this — restart
on crash, etc. — but task creation was blocked by a permission restriction
on this machine, so the Startup folder is the fallback. It works the same
day-to-day, just without auto-restart-on-crash.)

**To check if it's running:** open Task Manager, or check the log files —
`jarvis_log.txt` should say `Jarvis is listening for "hey jarvis"...` and
`telegram_bot_log.txt` should say `Jarvis Telegram bot is running.`

**To stop it running automatically:** delete `run_jarvis.vbs` and/or
`run_telegram_bot.vbs` from the Startup folder (`shell:startup`). To stop
an already-running hidden instance, end its `python.exe` process in Task
Manager (or `taskkill /IM python.exe /F` closes *all* Python processes —
careful if you have other Python things running).

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

### Always-on cloud relay (so it still answers when the laptop's off)

By default `telegram_bot.py` is just a Python process on your laptop — if
the laptop is off or asleep, there is no process anywhere to receive your
message, so you get silence, not an error. That's a hosting problem, not
something a code change on its own can fix: it needs a second machine
that's actually always on.

Moving `telegram_bot.py` to a free-tier always-on cloud VM (Oracle Cloud's
"Always Free" tier, or similar) or a Raspberry Pi/spare PC left running
fixes this for everything **except** screen/browser control, which
inherently needs the laptop itself:

| Works from the cloud relay | Still needs the laptop on |
|---|---|
| Plain conversation | `click_at`, `type_text`, `find_text_on_screen` |
| Calendar, email (read + draft) | `describe_screen` |
| Notes, web search | `browser_fill_and_submit`, tab management |
| Voice notes (transcription) | Spoken replies (`main.py` only, laptop-only anyway) |

`tools/__init__.py` disables each screen-control tool individually if its
package isn't installed rather than crashing the whole bot, and the system
prompt is told exactly which ones are missing on a given host -- so on the
cloud relay, Jarvis will say a request needs your laptop's Jarvis instead
of either hallucinating a click or telling you to do it yourself (which is
never right anyway, remote or not).

**Setup:**

1. Spin up the VM (or use your Pi), then get this repo onto it: `git clone`
   the repo (same URL as this branch), or `git pull` if you already cloned
   it there.
2. `python3 -m venv venv && source venv/bin/activate`
3. `pip install -r requirements-cloud.txt` — a trimmed dependency list that
   skips everything laptop/display-only (pyautogui, playwright, sounddevice,
   openwakeword, edge-tts) so install doesn't fail trying to build things a
   bare server can't (some of those packages don't even build without
   desktop libraries present).
4. Copy over `.env` (just `GEMINI_API_KEY`, `TELEGRAM_BOT_TOKEN`,
   `TELEGRAM_ALLOWED_CHAT_ID`) — and `credentials.json`/`token.json` too if
   you want Calendar/Gmail working from the cloud relay as well (those don't
   need the laptop either).
5. Run it so it survives your SSH session ending — a systemd service is the
   robust option:
   ```
   sudo tee /etc/systemd/system/jarvis-telegram.service <<'EOF'
   [Unit]
   Description=Jarvis Telegram bot
   After=network.target

   [Service]
   WorkingDirectory=/path/to/jarvis
   ExecStart=/path/to/jarvis/venv/bin/python -u telegram_bot.py
   Restart=always
   EnvironmentFile=/path/to/jarvis/.env

   [Install]
   WantedBy=multi-user.target
   EOF
   sudo systemctl enable --now jarvis-telegram
   ```
   (`tmux`/`screen` + manually restarting after a reboot works too, just
   less hands-off.)

**Important:** only run *one* `telegram_bot.py` at a time for a given bot
token. Telegram's long-polling doesn't support two pollers on the same
token — running it on both the cloud VM and the laptop simultaneously
causes a `Conflict` error and dropped/duplicate messages. Once it's on the
cloud relay, stop it on the laptop (the Startup-folder copy can go, or just
leave `run_telegram_bot.vbs` out of `shell:startup`) — the laptop still
runs `main.py` for the voice loop, that's unaffected.

### Knowing when the laptop itself is actually offline

The cloud relay above already means Telegram never goes silent — but on
its own, it only mentions the laptop when a specific request needs
screen/browser control. If you want Jarvis to be able to answer "is my
laptop on?" directly (or mention it's been offline a specific amount of
time, unprompted), set up the heartbeat: the laptop checks in with the
cloud relay every couple of minutes while it's actually running, and
`get_laptop_status` reads that to give a real answer instead of a guess.

1. **On the cloud VM**, run `heartbeat_server.py` (pure stdlib, no extra
   install) as another systemd service, same pattern as `jarvis-telegram`
   above:
   ```
   sudo tee /etc/systemd/system/jarvis-heartbeat.service <<'EOF'
   [Unit]
   Description=Jarvis laptop heartbeat receiver
   After=network.target

   [Service]
   WorkingDirectory=/path/to/jarvis
   ExecStart=/path/to/jarvis/venv/bin/python -u heartbeat_server.py
   Restart=always
   EnvironmentFile=/path/to/jarvis/.env

   [Install]
   WantedBy=multi-user.target
   EOF
   sudo systemctl enable --now jarvis-heartbeat
   ```
2. **Open the port** (`8765` by default) in the cloud provider's firewall/
   security group, and set `JARVIS_HEARTBEAT_TOKEN` (any random string) in
   the cloud VM's `.env`.
3. **On the laptop**, add the same `JARVIS_HEARTBEAT_TOKEN` plus
   `JARVIS_HEARTBEAT_URL=http://your-cloud-vm-ip:8765/heartbeat` to `.env`
   (see `.env.example`). `main.py`'s normal wake-word loop (`run_loop()`)
   starts sending the heartbeat automatically — nothing else to run.

If the heartbeat isn't configured at all, `get_laptop_status` just reports
"unknown" rather than doing anything misleading — everything else in this
README works exactly the same with or without it.

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

`describe_screen` uses Gemini's own vision capability — same API/key as
the main brain, no extra setup. (It used to run locally via Ollama +
moondream; that was noticeably weaker at reading on-screen text and
context, so it's gone.)

## Browser automation (Phase 3)

Uses [Playwright](https://playwright.dev) (free, open-source) to drive
your **actual, real Chrome** via its remote-debugging port
(`browser_session.py`) — not a separate profile. Jarvis sees and can act on
whatever's logged in and every open tab, the same as you.

(An earlier design used a separate, isolated Chrome profile instead —
safer in principle, but Google sites always opened logged out and there
was no working way to fix that: copying login cookies into the isolated
profile turned out not to work on modern Chrome, since App-Bound Encryption
ties them to the profile they came from. Connecting to the real browser
was the tradeoff made instead, deliberately, after that came up short.)

**Setup:** close every Chrome window (check the taskbar/system tray for
lingering background processes too), then launch Chrome via
`launch_chrome_debuggable.vbs` instead of your normal shortcut once, to get
started. Everything else about Chrome — your profile, extensions, open tabs
— works exactly as normal; it just also listens on `localhost:9222` for
Jarvis to connect to.

**You shouldn't need to do that by hand going forward.** Two things handle
it automatically: `run_chrome_debuggable.vbs`, placed in the Startup folder
alongside Jarvis's own scripts, launches a debuggable Chrome at every login
(but only if Chrome isn't already running, so it won't fight one that
started another way or double-launch). And if Chrome is ever fully closed
when a browser tool actually gets used, `browser_session.py` launches it
itself, debuggable, with nothing for you to do. The one case neither of
those covers: Chrome already open, just without the flag (it only takes
effect at launch, so it can't be turned on retroactively) — close every
Chrome window once and it comes back debuggable next time, same as always.

- `open_url` and `browser_fill_and_submit` open tabs in this Chrome window
  instead of the system default browser.
- `browser_fill_and_submit` can target a **new** tab (`url`) or an
  **existing** one (`tab_index`/`tab_hint`) — including tabs opened by
  hand, not just ones Jarvis itself opened. It fills one form field,
  submits it, waits for the page to actually finish loading (a "networkidle"
  signal, bounded to 8s so a stuck page can't hang the tool), then
  screenshots the result directly as part of the same call.
- `list_open_tabs` / `screenshot_tab` / `close_tab` / `close_all_tabs`
  manage every open tab (by index or a text hint matching the title/URL)
  — tabs stick around until explicitly closed, and these tools see *all*
  open tabs, including ones you opened yourself in that same window.

**Known limitation:** sites with aggressive bot-detection (Google search
being the biggest example) will block or CAPTCHA-challenge an automated
browser — confirmed by testing. For anything search-related, the `web_search`
tool is the reliable path since it doesn't drive a real browser at all.
Browser automation is best reserved for ordinary forms/websites (confirmed
working against Wikipedia's search box, including the full open -> fill ->
wait -> screenshot -> close-tab flow, and acting on an already-open tab
rather than opening a new one).

**If Chrome isn't running at all**, Jarvis launches it itself, debuggable,
the moment a browser tool needs it. **If Chrome is running without the
debug port enabled**, browser tools fail with a clear message telling you
to close every Chrome window and try again — Jarvis never force-closes your
browser itself, since that could lose tabs/work it doesn't know about; it
only ever launches a fresh Chrome when there's nothing already open to lose.

## What's built so far

**Phase 1 — core voice loop:**
- Full voice loop: wake word -> record -> transcribe -> think -> speak

**Phone access — Telegram bot:**
- Text or voice-note conversations with Jarvis from anywhere, free,
  no tunneling. Text-only replies (plus images when a tool attaches one).
- Locked to one authorized chat id so it can't be hijacked by a stranger.

**Phase 2 — tools:**
- `get_current_datetime`, `open_application`, `close_application`,
  `open_url`, `search_files` (Downloads/Documents/Desktop) — `close_application`
  tries a normal close first (lets the app prompt to save), verifies it
  actually closed rather than trusting a false-positive exit code (Windows
  Store/UWP apps like the Windows 11 Calculator report success while
  ignoring the close), and only force-kills if asked or if a normal close
  didn't really work
- `get_calendar_events` — Google Calendar, read-only
- `get_unread_emails`, `create_email_draft` — Gmail, read + draft-only
  (never auto-sends)
- `search_notes`, `add_note` — local Markdown "second brain" in `notes/`
  (git-ignored, stays on your machine)
- `web_search` — free, no API key, via DDGS

**Phase 3 — tools:**
- `describe_screen` — screen vision via Gemini (same API/key as the brain)
- `find_text_on_screen` — OCR (Tesseract) for precise click-ready
  coordinates of any visible text
- `find_element_on_screen` — Gemini vision for things with no literal text
  to search for (unread/bold, a checked box, an icon, a color)
- `click_at`, `type_text` — desktop-wide mouse/keyboard control, any
  window or app, not just Jarvis's own browser tabs
- `scroll` — scroll any page/panel up or down
- `browser_fill_and_submit`, `list_open_tabs`, `screenshot_tab`,
  `close_tab`, `close_all_tabs` — connected to the user's real Chrome, full
  control over every open tab, new or existing
- `get_laptop_status` — reads the laptop's heartbeat (see "Always-on cloud
  relay" above) to answer "is my laptop on?" for real, or give a specific
  offline duration instead of a guess

**Personality:** casual, dry-witted, talks like a sharp friend texting
back rather than a formal assistant — light slang/emoji only when it
genuinely fits (max one per reply), never forced in. Tuned based on
research into what actually reads as authentic vs. "trying too hard."

## Not built (by design)

- **No phone calls** — excluded on purpose, no Twilio/Vapi/phone number of
  any kind.

## Notes

- All processing after the wake word triggers goes to Gemini's cloud API
  (for the LLM) — wake-word detection and STT run fully locally, so no
  audio leaves your machine until you've actually said "hey jarvis" and
  started talking.
- If wake-word detection is too sensitive or not sensitive enough, tweak
  `JARVIS_WAKE_THRESHOLD`/`JARVIS_WAKE_GAIN` (see audio.py).
- If the main model (`JARVIS_MODEL`) hits its free-tier rate limit (daily
  cap or a per-minute burst), Jarvis automatically retries the same request
  on the next model in a fallback chain, each with its own separate quota
  (`gemini-3.6-flash` → `gemini-3.8-flash` → `gemini-3.1-flash-lite` by
  default) instead of just erroring out. Later models can be a bit weaker —
  a dumber reply beats no reply — but the odds of every quota in the chain
  being hit on the same day keep shrinking the longer it is. Configure via
  a comma-separated `JARVIS_FALLBACK_MODELS` in `.env`. Only when every
  model in the chain is rate-limited does Jarvis actually tell you to wait.
