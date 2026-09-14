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

import openai
from openai import OpenAI

from tools import call_tool, get_tool_schemas

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
# gemini-3.6-flash's free tier turned out to cap at just 20 requests/day
# (confirmed live against the API, not a docs claim) -- nowhere near enough
# for a tool-calling assistant. gemini-3.5-flash-lite's free tier is
# meaningfully more usable in practice (lite tiers are built for higher
# throughput); verified it still handles tool-calling and multi-turn
# context correctly before making it the default.
MODEL = os.environ.get("JARVIS_MODEL", "gemini-3.5-flash-lite")

# How many user turns of conversation history to keep. Every call resends
# the full history (on top of the ~1.9K-token tool schema set), so letting
# it grow unbounded across a conversation burns through the per-minute token
# budget faster than it needs to -- see llm.py's Jarvis._trim_history.
MAX_HISTORY_TURNS = 6

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
    "if it's the most natural word for that exact thought."
)


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
        self.history.append({"role": "user", "content": user_text})
        self.last_attachments = []

        try:
            for _ in range(5):  # cap tool-call round-trips to avoid infinite loops
                response = self.client.chat.completions.create(
                    model=MODEL,
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
                        self.last_attachments.append(result.pop("_attachment_path"))
                    self.history.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "content": json.dumps(result),
                        }
                    )

            return "I got stuck juggling tools on that one — try rephrasing?"
        except openai.APIError as exc:
            # Roll back this whole attempt -- don't leave a half-finished turn
            # (a user message with no real reply) sitting in history, since
            # that would silently waste tokens re-sending it on the next ask().
            del self.history[history_len_before:]
            self.last_attachments = []
            return _friendly_api_error(exc)


def _friendly_api_error(exc: openai.APIError) -> str:
    if isinstance(exc, openai.RateLimitError):
        wait = _rate_limit_wait_seconds(exc)
        if wait is not None:
            return f"Hit Gemini's free-tier limit — resets in about {_format_wait(wait)}, try again then."
        return (
            "Hit Gemini's free-tier rate limit — give it a few minutes and "
            "ask again."
        )
    if isinstance(exc, openai.APIConnectionError):
        return "Couldn't reach Gemini's API — check your connection and try again."
    return "The brain's API hiccuped on that one — try again in a bit."


def _rate_limit_wait_seconds(exc: openai.RateLimitError) -> float | None:
    """If the 429 response carries a Retry-After header with the exact
    number of seconds until enough quota frees up, use that instead of
    guessing "a few minutes" -- which can be wildly off in either direction."""
    try:
        return float(exc.response.headers.get("retry-after"))
    except (AttributeError, TypeError, ValueError):
        return None


def _format_wait(seconds: float) -> str:
    seconds = max(1, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    return f"{minutes}m{secs}s" if secs else f"{minutes}m"
