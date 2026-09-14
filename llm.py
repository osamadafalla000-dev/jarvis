"""Groq-backed brain for Jarvis: a small tool-calling chat loop."""

from __future__ import annotations

import json
import os

from groq import Groq

from tools import call_tool, get_tool_schemas

MODEL = os.environ.get("JARVIS_MODEL", "openai/gpt-oss-120b")

SYSTEM_PROMPT = (
    "You are Jarvis, a concise, dry-witted personal voice assistant. "
    "You are being heard, not read, so keep replies short and speakable — "
    "no markdown, no bullet lists, no code blocks. Use tools whenever a "
    "question needs live information (time, files, apps) instead of "
    "guessing. If a tool call fails, say so plainly rather than making "
    "something up."
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

    def ask(self, user_text: str) -> str:
        self.history.append({"role": "user", "content": user_text})

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
                self.history.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(result),
                    }
                )

        return "I got stuck juggling tools on that one — try rephrasing?"
