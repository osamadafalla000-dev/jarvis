"""Groq-backed brain for Jarvis: a small tool-calling chat loop."""

from __future__ import annotations

import json
import os

import groq
from groq import Groq

from tools import call_tool, get_tool_schemas

MODEL = os.environ.get("JARVIS_MODEL", "openai/gpt-oss-120b")

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
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Copy .env.example to .env and add "
                "your free key from console.groq.com/keys."
            )
        self.client = Groq(api_key=api_key)
        self.history: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        # Files (e.g. a screenshot from describe_screen) produced by tool calls
        # during the most recent ask(). Front-ends that can show files (like
        # the Telegram bot) can send these; voice-only front-ends can ignore it.
        self.last_attachments: list[str] = []

    def ask(self, user_text: str) -> str:
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
        except groq.APIError as exc:
            # Roll back this whole attempt -- don't leave a half-finished turn
            # (a user message with no real reply) sitting in history, since
            # that would silently waste tokens re-sending it on the next ask().
            del self.history[history_len_before:]
            self.last_attachments = []
            return _friendly_api_error(exc)


def _friendly_api_error(exc: groq.APIError) -> str:
    if isinstance(exc, groq.RateLimitError):
        return (
            "Hit Groq's free-tier rate limit — give it a few minutes and "
            "ask again."
        )
    if isinstance(exc, groq.APIConnectionError):
        return "Couldn't reach Groq's API — check your connection and try again."
    return "The brain's API hiccuped on that one — try again in a bit."
