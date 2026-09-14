"""Screen vision via a local Ollama vision model (free, fully offline).

Groq has no working free vision model for this account, so screen vision
runs entirely locally instead: Ollama (https://ollama.com, free) serving
the small `moondream` vision model. Requires Ollama installed and running
(`ollama serve` — on Windows it runs automatically as a background service
once installed) and the model pulled once with `ollama pull moondream`.
"""

from __future__ import annotations

import base64
import io

import requests
from PIL import ImageGrab

from . import tool

OLLAMA_URL = "http://localhost:11434/api/generate"
VISION_MODEL = "moondream"


def _screenshot_base64() -> str:
    image = ImageGrab.grab()
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


@tool(
    {
        "name": "describe_screen",
        "description": (
            "Take a screenshot of the user's screen right now and describe it, "
            "or answer a specific question about what's currently visible on it."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": (
                        "What to look for or ask about the screen. Pass a "
                        "general description request if nothing specific was asked."
                    ),
                }
            },
            "required": ["question"],
        },
    }
)
def describe_screen(question: str = "Describe what's on this screen.") -> dict:
    try:
        image_b64 = _screenshot_base64()
    except Exception as exc:  # noqa: BLE001
        return {"error": f"couldn't capture the screen: {exc}"}

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": VISION_MODEL,
                "prompt": question,
                "images": [image_b64],
                "stream": False,
            },
            timeout=60,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        return {
            "error": (
                f"couldn't reach the local Ollama vision model: {exc}. "
                "Make sure Ollama is running and `ollama pull moondream` has "
                "been run once."
            )
        }

    return {"description": response.json().get("response", "").strip()}
