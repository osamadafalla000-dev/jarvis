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


def _screenshot_and_describe(prompt: str) -> tuple[Path, str | None]:
    """Screenshot right now and ask Gemini what's actually visible -- so
    click_at/type_text's result carries real, observed feedback the model
    itself can read, instead of a bare "status: clicked/typed" it has no way
    to verify. Without this, a missed click or a field that didn't actually
    focus reads identical to a successful one from the tool's return value
    alone -- confirmed live: Jarvis reported a click and a "history opened"
    as successful when neither one had actually happened on screen.
    Description is best-effort (None on any failure) -- a vision hiccup
    here shouldn't break the click/type action that already happened."""
    screenshot_path = Path(tempfile.mktemp(suffix=".png"))
    ImageGrab.grab().save(screenshot_path, format="PNG")

    try:
        from llm import GEMINI_BASE_URL, MODEL  # lazy: avoid llm.py's circular import at load time
        import base64
        from openai import OpenAI

        image_b64 = base64.b64encode(screenshot_path.read_bytes()).decode()
        client = OpenAI(api_key=os.environ["GEMINI_API_KEY"], base_url=GEMINI_BASE_URL)
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                        },
                    ],
                }
            ],
        )
        description = (response.choices[0].message.content or "").strip()
    except Exception:  # noqa: BLE001 - best-effort; the action itself already happened
        description = None

    return screenshot_path, description


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
        "name": "scroll",
        "description": (
            "Scroll up or down on whatever's currently visible -- any "
            "browser tab, any app. Scrolls wherever the mouse cursor "
            "currently is unless x/y is given, which moves it there first "
            "-- pass x/y when scrolling a specific panel (e.g. a chat "
            "sidebar) rather than the main page/whatever the cursor happens "
            "to be over. No result-verification screenshot (unlike click_at/"
            "type_text) -- scrolling is usually a prep step before looking "
            "again with find_text_on_screen/describe_screen, so keeping it "
            "fast matters more than confirming each individual scroll."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "enum": ["up", "down"],
                    "description": "Which way to scroll.",
                },
                "amount": {
                    "type": ["integer", "null"],
                    "description": "How far, in scroll clicks (default 5 -- a few clicks is a modest scroll, more for a bigger jump).",
                },
                "x": {
                    "type": ["integer", "null"],
                    "description": "Move the mouse here first, so the scroll happens over this element/panel.",
                },
                "y": {
                    "type": ["integer", "null"],
                    "description": "Move the mouse here first, so the scroll happens over this element/panel.",
                },
            },
            "required": ["direction"],
        },
    }
)
def scroll(direction: str, amount: int = 5, x: int | None = None, y: int | None = None) -> dict:
    if x is not None and y is not None:
        pyautogui.moveTo(x, y)
    clicks = amount if direction == "up" else -amount
    pyautogui.scroll(clicks)
    return {"status": "scrolled", "direction": direction, "amount": amount}


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
            "reliable since it targets by label instead of guessing pixels. "
            "Returns `after` -- what's actually visible right after the "
            "click -- trust that over assuming the click landed correctly; "
            "a click can miss (stale coordinates, a still-animating menu, "
            "the wrong window in front) and still return 'clicked'."
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
    time.sleep(0.4)  # let menus/dropdowns/page transitions actually settle

    screenshot_path, description = _screenshot_and_describe(
        "A click just happened at the crosshair-ish center of this screen. "
        "In one or two sentences: what's visible right now, and does it "
        "look like the click actually landed on something (a menu opened, "
        "a page changed, a field got focus, etc.) or did nothing visible "
        "happen?"
    )

    return {
        "status": "clicked",
        "x": x,
        "y": y,
        "double": double,
        "after": description or "(couldn't analyze the result -- check manually if unsure)",
        "_attachment_path": str(screenshot_path),
    }


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
            "reliably, and restores whatever was on the clipboard before. "
            "Returns `after` -- what's actually visible right after typing "
            "-- trust that over assuming it worked; the click that's "
            "supposed to focus the field can itself miss, in which case "
            "nothing was typed anywhere useful even though this still "
            "returns 'typed'."
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

    screenshot_path, description = _screenshot_and_describe(
        f"Text was just typed into a field on this screen: {text!r}. In one "
        "or two sentences: what's visible right now, and does that text "
        "actually appear typed into a field, or does nothing visible show "
        "it worked?"
    )

    return {
        "status": "typed",
        "text": text,
        "pressed_enter": press_enter,
        "after": description or "(couldn't analyze the result -- check manually if unsure)",
        "_attachment_path": str(screenshot_path),
    }
