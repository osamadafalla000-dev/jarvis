"""Desktop-level mouse/keyboard automation -- clicks and types into
whatever's on screen, in ANY window (any browser, any app), not just
Jarvis's own Playwright-controlled Chrome. find_text_on_screen (OCR) is the
reliable way to find where something is; describe_screen's local vision
model is weak at reading exact text/positions. Then click there, then type.
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

import pyautogui
import pyperclip
import pytesseract
from PIL import ImageGrab

from . import tool

# Moving the mouse to a screen corner aborts whatever pyautogui is doing --
# a manual kill switch if a click/type goes somewhere it shouldn't.
pyautogui.FAILSAFE = True

# pytesseract doesn't reliably find tesseract.exe on PATH on Windows even
# right after a fresh install -- point at it explicitly. Overridable since
# the exact install path can vary.
TESSERACT_CMD = os.environ.get("JARVIS_TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe")
if os.path.exists(TESSERACT_CMD):
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD


def _group_into_lines(ocr_data: dict) -> list[list[dict]]:
    """pytesseract's image_to_data is word-level -- group words that share a
    (block, paragraph, line) back into lines, each word keeping its own
    bounding box, so a phrase like "Jarvis workspace" can be matched even
    though it's two separate detected words."""
    lines: dict[tuple, list[dict]] = {}
    for i, text in enumerate(ocr_data["text"]):
        if not text.strip():
            continue
        key = (ocr_data["block_num"][i], ocr_data["par_num"][i], ocr_data["line_num"][i])
        lines.setdefault(key, []).append(
            {
                "text": text,
                "left": ocr_data["left"][i],
                "top": ocr_data["top"][i],
                "width": ocr_data["width"][i],
                "height": ocr_data["height"][i],
            }
        )
    return list(lines.values())


@tool(
    {
        "name": "find_text_on_screen",
        "description": (
            "Find text visible anywhere on screen right now via OCR and get "
            "click-ready coordinates for it -- much more reliable than "
            "describe_screen for locating a specific label/word/button to "
            "click or type into, since describe_screen's local vision model "
            "is weak at exact text reading and position. Matches are "
            "case-insensitive substrings, so a short distinctive word or "
            "phrase works best -- but 'anywhere on screen' means literally "
            "that: every open window, every browser tab, the taskbar, all "
            "of it, not just the app the user is looking at. A generic "
            "query (e.g. just 'chat' or 'search') can easily match the "
            "wrong instance in a different window and land a click/type "
            "somewhere unintended. Always check each match's returned "
            "`text` (the full surrounding line) actually matches the "
            "expected context before clicking it -- if it's ambiguous, "
            "prefer a more distinctive phrase, or confirm with "
            "describe_screen first."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Text to search for on screen, e.g. 'Jarvis' or 'Save changes'.",
                }
            },
            "required": ["text"],
        },
    }
)
def find_text_on_screen(text: str) -> dict:
    if not os.path.exists(TESSERACT_CMD):
        return {
            "status": "error",
            "message": (
                "Tesseract OCR isn't installed (or not at the expected path) -- "
                "install it (winget install --id tesseract-ocr.tesseract -e) "
                "or set JARVIS_TESSERACT_CMD to its install path."
            ),
        }

    try:
        ocr_data = pytesseract.image_to_data(ImageGrab.grab(), output_type=pytesseract.Output.DICT)
    except Exception as exc:  # noqa: BLE001 - surface OCR failures plainly
        return {"status": "error", "message": f"OCR failed: {exc}"}

    query = text.strip().lower()
    matches = []
    for words in _group_into_lines(ocr_data):
        line_text = " ".join(w["text"] for w in words)
        if query not in line_text.lower():
            continue
        # Narrow to just the word(s) actually containing the query, so the
        # click point is precise instead of the whole line's midpoint.
        target_words = [w for w in words if query in w["text"].lower()] or words
        left = min(w["left"] for w in target_words)
        top = min(w["top"] for w in target_words)
        right = max(w["left"] + w["width"] for w in target_words)
        bottom = max(w["top"] + w["height"] for w in target_words)
        matches.append(
            {"text": line_text.strip(), "x": (left + right) // 2, "y": (top + bottom) // 2}
        )

    if not matches:
        return {"status": "not_found", "matches": []}
    return {"status": "found", "matches": matches[:10]}


@tool(
    {
        "name": "click_at",
        "description": (
            "Click at a pixel coordinate on screen (origin top-left) -- "
            "works on anything currently visible: any browser window, any "
            "desktop app, not just Jarvis's own managed Chrome window. Get "
            "the coordinates from find_text_on_screen if clicking something "
            "with a visible label/word; describe_screen only for non-text "
            "targets (an icon, an image) since its vision model is weak at "
            "exact text/position. For links/buttons/fields inside Jarvis's "
            "own browser tabs specifically, browser_fill_and_submit is more "
            "reliable since it targets by label instead of guessing pixels."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "X coordinate in pixels."},
                "y": {"type": "integer", "description": "Y coordinate in pixels."},
                "double": {
                    "type": ["boolean", "null"],
                    "description": "Double-click instead of a single click (default false).",
                },
            },
            "required": ["x", "y"],
        },
    }
)
def click_at(x: int, y: int, double: bool = False) -> dict:
    if double:
        pyautogui.doubleClick(x, y)
    else:
        pyautogui.click(x, y)
    return {"status": "clicked", "x": x, "y": y, "double": double}


@tool(
    {
        "name": "type_text",
        "description": (
            "Click a field to focus it, then type text into it -- any app, "
            "any browser, not just Jarvis's own browser tabs (use "
            "browser_fill_and_submit for those instead). x/y are required: "
            "launching or switching to an app does NOT reliably give it "
            "keyboard focus (Windows blocks background processes from "
            "stealing focus), so typing without clicking first risks "
            "landing in whatever window the user actually has focused --  "
            "which happened once already and is exactly why this always "
            "clicks first now. Get x/y from find_text_on_screen (or "
            "describe_screen for a non-text target). Pastes via the "
            "clipboard so any text (including emoji/unicode) comes through "
            "reliably, restores "
            "whatever was on the clipboard before, and returns a screenshot "
            "taken right after so the result can be checked."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to type."},
                "x": {
                    "type": "integer",
                    "description": "Click here first to focus the field before typing.",
                },
                "y": {
                    "type": "integer",
                    "description": "Click here first to focus the field before typing.",
                },
                "press_enter": {
                    "type": ["boolean", "null"],
                    "description": "Press Enter after typing (default false).",
                },
            },
            "required": ["text", "x", "y"],
        },
    }
)
def type_text(text: str, x: int, y: int, press_enter: bool = False) -> dict:
    pyautogui.click(x, y)
    time.sleep(0.15)  # let the click-triggered focus change actually land

    previous_clipboard = None
    try:
        previous_clipboard = pyperclip.paste()
    except Exception:  # noqa: BLE001 - clipboard access can fail (e.g. non-text contents); not fatal
        pass

    pyperclip.copy(text)
    time.sleep(0.05)  # let the clipboard actually update before pasting
    pyautogui.hotkey("ctrl", "v")

    if press_enter:
        time.sleep(0.05)
        pyautogui.press("enter")

    if previous_clipboard is not None:
        time.sleep(0.1)
        pyperclip.copy(previous_clipboard)

    screenshot_path = Path(tempfile.mktemp(suffix=".png"))
    ImageGrab.grab().save(screenshot_path, format="PNG")

    return {
        "status": "typed",
        "text": text,
        "pressed_enter": press_enter,
        "_attachment_path": str(screenshot_path),
    }
