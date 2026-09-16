"""Gemini-backed brain for Jarvis: a small tool-calling chat loop.

Uses the `openai` SDK pointed at Google's OpenAI-compatible endpoint rather
than Google's native SDK, so the tool-calling plumbing below is the same
shape either provider would need. Gemini's free tier (250K TPM, shared
across models) was picked over Groq's (8K TPM for gpt-oss-120b) because
Jarvis resends its full ~1.9K-token tool schema set on every single call --
Groq's tier could only sustain 2-4 such calls per minute; Gemini's isn't
close to that bottleneck at normal conversational pace.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import openai
from openai import OpenAI

import tools
from tools import call_tool, get_tool_schemas

# Human-readable capability names for tool modules that might not load on a
# given host (e.g. tools/desktop.py's pyautogui needs a real display, which
# an always-on cloud/server deployment running only telegram_bot.py won't
# have). Only listed here if failing genuinely means "not on this machine" --
# calendar_tool/email_tool failing more likely means missing credentials.json,
# which the model already reports as a plain tool error, not a capability gap.
_SCREEN_CONTROL_MODULES = {
    "desktop": "clicking/typing anywhere on screen, or reading it via OCR",
    "vision": "describe_screen (looking at what's currently on screen)",
    "browser": "controlling your actual Chrome (opening tabs, filling forms)",
    "tabs": "managing your open Chrome tabs",
}

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
# gemini-3.6-flash's free tier turned out to cap at just 20 requests/day
# (confirmed live against the API, not a docs claim) -- nowhere near enough
# for a tool-calling assistant. gemini-3.5-flash-lite's free tier is
# meaningfully more usable in practice (lite tiers are built for higher
# throughput); verified it still handles tool-calling and multi-turn
# context correctly before making it the default.
MODEL = os.environ.get("JARVIS_MODEL", "gemini-3.5-flash-lite")

# Free-tier request quotas are tracked per model, not per key -- confirmed by
# the MODEL history above (switching off gemini-3.6-flash was exactly this:
# a different model name meant a fresh quota bucket). So when the primary
# model's quota is hit (daily cap or a per-minute burst), retrying the same
# request against a different model can succeed immediately instead of
# making the user wait. Defaults to the one other model this codebase has
# already confirmed works (gemini-3.6-flash) -- its own daily cap is low
# (20/day), but that's still a completely separate 20/day from MODEL's,
# so it's a real fallback, not a fresh way to hit the same wall. Override/
# extend via a comma-separated JARVIS_FALLBACK_MODELS in .env.
FALLBACK_MODELS = [
    m.strip()
    for m in os.environ.get("JARVIS_FALLBACK_MODELS", "gemini-3.6-flash").split(",")
    if m.strip()
]

# How many user turns of conversation history to keep. Every call resends
# the full history (on top of the ~1.9K-token tool schema set), so letting
# it grow unbounded across a conversation burns through the per-minute token
# budget faster than it needs to -- see llm.py's Jarvis._trim_history.
MAX_HISTORY_TURNS = 6

# How many tool-call round-trips a single ask() can make before giving up.
# 5 was tuned back when most requests were single-tool (get_current_datetime,
# open_url). A full multi-app task described in one message (open an app,
# find a workspace, type into it) can easily chain 8-12 tool calls once
# Jarvis is actually expected to carry the whole thing through instead of
# pausing after each step -- see SYSTEM_PROMPT below.
MAX_TOOL_ROUNDS = 16

SYSTEM_PROMPT = (
    "You're Jarvis. Talk like a sharp, laid-back friend texting back — not a "
    "formal assistant, not a butler, never call the user 'sir'. Casual "
    "phrasing, contractions, dry humor. Light slang (fr, ngl, lowkey, no "
    "cap) is fine ONLY when it actually fits naturally — at most one such "
    "word per reply, and skip it entirely most of the time. Forcing slang "
    "into every line reads as trying too hard, which is worse than not "
    "using it at all. Same deal with emoji: rare, at most one per reply, "
    "only when it genuinely adds something — never stack them, never use "
    "them as decoration. No 'as an AI', no corporate hedging, no customer- "
    "support voice. You're being heard (or read as a quick text), so keep "
    "it short — no markdown, no bullet lists, no code blocks. Use tools "
    "whenever a question needs live info instead of guessing. If a tool "
    "call fails, say so plainly rather than making something up.\n\n"
    "Calibration — right: \"yeah it's 3pm, you've got the dentist at 4\". "
    "Also right: \"oof, that sucks, wanna talk about it\". "
    "Wrong (too much): \"OMG bestie it's literally 3pm rn, no cap, time is "
    "FLYING today! \U0001f525\U0001f480\". Slang/emoji tacked onto the end "
    "of a sentence just to have some there is always wrong — only use one "
    "if it's the most natural word for that exact thought.\n\n"
    "Desktop/browser UI tasks (clicking or typing into an app or website via "
    "click_at/type_text/find_text_on_screen/browser_fill_and_submit) are "
    "multi-step by nature — do them one verified step at a time internally: "
    "act, check the result, then immediately move to the next step yourself "
    "-- keep calling tools back-to-back in this SAME reply until the WHOLE "
    "task the user described is actually done. Don't stop after one step to "
    "report progress and wait for the user to say 'next' or 'ok now do the "
    "next part' -- if they described the whole task in one message (open an "
    "app, find a specific workspace/window, type something into it), do all "
    "of it before replying, the same way a person would just go do it "
    "instead of narrating each motion and waiting for a go-ahead. E.g. "
    "sending an email: find/click Compose, confirm it opened, find/click "
    "the To field, type it, find/click Subject, type it, find/click the "
    "body, type it, find/click Send -- all of that from one instruction, "
    "not eight separate ones. Don't assume a click landed correctly or a "
    "field is the right one — check (describe_screen, or what "
    "find_text_on_screen returns) before moving on, but checking is silent/"
    "internal, not a reason to stop and ask the user.\n\n"
    "Your entire reason to exist is being the user's hands on this computer "
    "when they can't be -- away from it, on their phone via Telegram, or "
    "just don't want to. Because of that, NEVER tell the user to click, "
    "type, open, scroll to, or navigate to something themselves -- "
    "'click the blue Compose button' or 'go to Settings and toggle X' is a "
    "failure response, not a helpful one, since if they could do that "
    "they wouldn't need you. You have click_at, type_text, "
    "find_text_on_screen, describe_screen, and the browser tools -- that's "
    "you doing it, not you narrating it. If find_text_on_screen doesn't "
    "find something on the first try, that's not the end: describe_screen "
    "to see what's actually on screen, scroll if it might be off-screen, "
    "try alternate wording for the same element (the button might say "
    "'Send' not 'Submit'), before concluding it's not there. Only after "
    "real attempts like that fail should you say you're stuck. When you do, "
    "the user reached you remotely (voice, or texting from their phone via "
    "Telegram) specifically because they're not at the machine -- 'do it "
    "yourself' or any variant of handing the steps back is never a valid "
    "reply, it's just as useless as never answering. What they actually "
    "need instead is the real, specific problem: what you were trying to "
    "do, exactly what you saw or what happened when it broke (the literal "
    "error text, which field/button/dialog it was, what describe_screen "
    "showed), and what you already tried. 'Ran into a problem' with nothing "
    "after it tells them nothing they can act on -- 'tried clicking Send "
    "three times, the button's still there but the compose window isn't "
    "closing, might be waiting on something else' actually does. This "
    "applies even to the genuinely-only-the-user's-to-do cases -- typing a "
    "2FA code sent to their phone, solving a CAPTCHA, approving a "
    "biometric/password prompt: still describe exactly what's asking for "
    "it and why you can't, don't just declare it their problem and stop. "
    "Only interrupt with a question if truly stuck after real attempts, "
    "hit one of those genuine can't-do-it-for-them cases, or are missing a "
    "detail you can't proceed without (who an email's to, what it should "
    "say, which of several matching things was meant) — ask that once, up "
    "front or the moment it's discovered, then carry on through the rest "
    "without further check-ins."
)

_missing_screen_control = {
    name: desc for name, desc in _SCREEN_CONTROL_MODULES.items() if name in tools.UNAVAILABLE_MODULES
}
if _missing_screen_control:
    # This instance is running somewhere without a real display/browser to
    # control -- e.g. an always-on cloud server standing in for the laptop
    # while it's off. The model has no other way to know these tools simply
    # don't exist right now rather than existing-but-failing, so it needs to
    # be told outright, or it'll either hallucinate trying them or, worse,
    # fall back into telling the user to do it by hand.
    SYSTEM_PROMPT += (
        "\n\nIMPORTANT: this specific instance of you is running somewhere "
        "without a real screen/browser to control, so you do NOT have "
        + "; ".join(_missing_screen_control.values())
        + " -- those tools don't exist in this conversation at all, not "
        "even to try. If a request needs one of those, say plainly that it "
        "needs your laptop/desktop instance of Jarvis running for that part "
        "specifically (not just 'do it yourself' -- that's still wrong for "
        "the same reason as always: they're texting you because they're "
        "not at it). Before saying that, call get_laptop_status if it's "
        "available -- it tells you how long it's actually been since the "
        "laptop's own Jarvis checked in, so you can say something real "
        "('it's been offline about 40 minutes') instead of a bare 'needs "
        "your laptop' every time, whether or not it's actually off right "
        "now. Everything else -- chat, calendar, email, notes, web "
        "search -- works completely normally from here."
    )
del _missing_screen_control


class Jarvis:
    def __init__(self):
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Copy .env.example to .env and add "
                "your free key from aistudio.google.com/apikey."
            )
        self.client = OpenAI(api_key=api_key, base_url=GEMINI_BASE_URL)
        self.history: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        # Files (e.g. a screenshot from describe_screen) produced by tool calls
        # during the most recent ask(). Front-ends that can show files (like
        # the Telegram bot) can send these; voice-only front-ends can ignore it.
        self.last_attachments: list[str] = []

    def _trim_history(self) -> None:
        """Drop the oldest turns once history exceeds MAX_HISTORY_TURNS,
        keeping the system prompt plus the most recent turns. Only cuts at
        user-message boundaries -- an assistant's tool_calls message has to
        stay adjacent to its tool results, or the API rejects the request."""
        user_indices = [i for i, m in enumerate(self.history) if m["role"] == "user"]
        if len(user_indices) <= MAX_HISTORY_TURNS:
            return
        cutoff = user_indices[-MAX_HISTORY_TURNS]
        self.history = [self.history[0], *self.history[cutoff:]]

    def ask(self, user_text: str) -> str:
        self._trim_history()
        history_len_before = len(self.history)
        self.last_attachments = []

        models = [MODEL, *[m for m in FALLBACK_MODELS if m != MODEL]]
        last_exc: openai.APIError | None = None
        for attempt, model in enumerate(models):
            self.history.append({"role": "user", "content": user_text})
            try:
                return self._run_tool_loop(model)
            except openai.APIError as exc:
                # Roll back this whole attempt -- don't leave a half-finished
                # turn (a user message with no real reply) sitting in
                # history, since that would silently waste tokens re-sending
                # it on the next ask() (or the next model tried below).
                del self.history[history_len_before:]
                for old_path in self.last_attachments:
                    Path(old_path).unlink(missing_ok=True)
                self.last_attachments = []
                # Print the raw error so it lands in jarvis_log.txt -- the
                # friendly message below deliberately hides Gemini's actual
                # wording, but that wording (which quota, per-minute vs
                # per-day) is exactly what you need to diagnose a stuck
                # "limit hit" case.
                print(f"[Jarvis] Gemini API error on model {model!r}: {exc}", file=sys.stderr)
                last_exc = exc
                is_last_model = attempt == len(models) - 1
                if isinstance(exc, openai.RateLimitError) and not is_last_model:
                    # A rate limit (daily or per-minute) is exactly the case
                    # a different model's separate quota bucket can dodge --
                    # keep going instead of surfacing an error the user would
                    # otherwise have to wait out.
                    continue
                return _friendly_api_error(exc, exhausted_models=models if is_last_model else None)

        # Unreachable in practice (the loop above always returns or raises),
        # but keeps the type checker honest about ask()'s return type.
        assert last_exc is not None
        return _friendly_api_error(last_exc)

    def _run_tool_loop(self, model: str) -> str:
        for _ in range(MAX_TOOL_ROUNDS):
            response = self.client.chat.completions.create(
                model=model,
                messages=self.history,
                tools=get_tool_schemas(),
                tool_choice="auto",
            )
            message = response.choices[0].message
            self.history.append(message.model_dump(exclude_none=True))

            if not message.tool_calls:
                return message.content or ""

            for call in message.tool_calls:
                args = json.loads(call.function.arguments or "{}")
                result = call_tool(call.function.name, args)
                if isinstance(result, dict) and "_attachment_path" in result:
                    attachment_path = result.pop("_attachment_path")
                    # Keep only the most recent screenshot per ask() --
                    # earlier ones already served their purpose (feeding
                    # that tool's own `after` verification back into the
                    # conversation); sending every intermediate one as a
                    # separate Telegram photo for one multi-step task
                    # (e.g. click then type) was confusing, not helpful.
                    for old_path in self.last_attachments:
                        Path(old_path).unlink(missing_ok=True)
                    self.last_attachments = [attachment_path]
                self.history.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(result),
                    }
                )

        return "I got stuck juggling tools on that one — try rephrasing?"


def _friendly_api_error(exc: openai.APIError, exhausted_models: list[str] | None = None) -> str:
    if isinstance(exc, openai.RateLimitError):
        if exhausted_models and len(exhausted_models) > 1:
            # Every model in the fallback chain hit its own rate limit for
            # this request -- worth saying so explicitly, since otherwise
            # this reads exactly like the single-model case even though
            # Jarvis already tried to route around it.
            names = ", ".join(exhausted_models)
            return (
                f"Hit Gemini's free-tier limit on every model I've got "
                f"configured ({names}) — add another to JARVIS_FALLBACK_MODELS "
                f"in .env, check usage at aistudio.google.com/apikey, or wait "
                f"a bit and try again."
            )
        quota = _quota_info(exc)
        if quota.is_daily:
            # A per-day quota doesn't refill by waiting a few minutes -- it
            # only resets on Google's daily cycle (midnight Pacific time).
            # Telling the user to "try again in a bit" here is actively
            # misleading: they can retry for hours and it'll keep failing
            # until the reset actually happens.
            return (
                "Hit Gemini's free-tier DAILY request cap, not a short-term "
                "rate limit -- retrying every few minutes won't help, it "
                "only resets once every 24h (around midnight Pacific time). "
                "Check usage at aistudio.google.com/apikey, or wait for the "
                "daily reset."
            )
        if quota.wait_seconds is not None:
            return f"Hit Gemini's free-tier limit — resets in about {_format_wait(quota.wait_seconds)}, try again then."
        return (
            "Hit Gemini's free-tier rate limit — give it a few minutes and "
            "ask again."
        )
    if isinstance(exc, openai.APIConnectionError):
        return "Couldn't reach Gemini's API — check your connection and try again."
    return "The brain's API hiccuped on that one — try again in a bit."


class _QuotaInfo:
    def __init__(self, wait_seconds: float | None, is_daily: bool):
        self.wait_seconds = wait_seconds
        self.is_daily = is_daily


def _quota_info(exc: openai.RateLimitError) -> _QuotaInfo:
    """Figure out what kind of 429 this actually is.

    Two independent things can tell us: an HTTP Retry-After header (rare --
    Gemini's OpenAI-compat endpoint generally doesn't send one) and the JSON
    error body, which does carry Google's real quota details (a
    google.rpc.RetryInfo delay, and a google.rpc.QuotaFailure naming which
    quota was hit, e.g. a "...PerDay..." quotaId/quotaMetric for the daily
    cap vs "...PerMinute..." for a short-term one). The old code only
    checked the header, so it silently always fell through to the vague
    "a few minutes" message -- including for daily-cap hits, which is the
    misleading case that makes Jarvis look stuck for hours.
    """
    wait_seconds = None
    try:
        wait_seconds = float(exc.response.headers.get("retry-after"))
    except (AttributeError, TypeError, ValueError):
        pass

    body = exc.body if isinstance(exc.body, dict) else {}
    error = body.get("error") if isinstance(body.get("error"), dict) else body
    message = str(error.get("message") or "") if isinstance(error, dict) else ""
    details = error.get("details") or [] if isinstance(error, dict) else []
    if not isinstance(details, list):
        details = []

    is_daily = "per day" in message.lower() or "daily" in message.lower()
    for detail in details:
        if not isinstance(detail, dict):
            continue
        detail_type = str(detail.get("@type", ""))
        if wait_seconds is None and detail_type.endswith("RetryInfo"):
            match = re.match(r"([\d.]+)s?$", str(detail.get("retryDelay", "")))
            if match:
                wait_seconds = float(match.group(1))
        if detail_type.endswith("QuotaFailure"):
            for violation in detail.get("violations", []) or []:
                if not isinstance(violation, dict):
                    continue
                quota_name = " ".join(
                    str(violation.get(key, ""))
                    for key in ("quotaId", "quotaMetric", "quotaDimensions")
                ).lower()
                if "day" in quota_name:
                    is_daily = True

    # A daily-cap 429 will often still carry a short RetryInfo delay -- that
    # delay is a generic per-request backoff hint, not an actual "quota
    # refills in N seconds" promise, so once we know it's the daily quota,
    # trust that over any short wait_seconds we parsed.
    return _QuotaInfo(wait_seconds=None if is_daily else wait_seconds, is_daily=is_daily)


def _format_wait(seconds: float) -> str:
    seconds = max(1, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    return f"{minutes}m{secs}s" if secs else f"{minutes}m"
