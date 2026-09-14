"""Desktop-level mouse/keyboard automation -- clicks and types into
whatever's on screen, in ANY window (any browser, any app), not just
Jarvis's own Playwright-controlled Chrome. Complements describe_screen and
find_text_on_screen: find where something is, click there, then type.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import pyautogui
import pyperclip
from PIL import ImageGrab

from . import tool

# Moving the mouse to a screen corner aborts whatever pyautogui is doing --
# a manual kill switch if a click/type goes somewhere it shouldn't.
pyautogui.FAILSAFE = True


@tool(
    {
        "name": "click_at",
        "description": (
            "Click at a pixel coordinate on screen (origin top-left) -- "
            "works on anything currently visible: any browser window, any "
            "desktop app, not just Jarvis's own managed Chrome window. Use "
            "describe_screen first to see what's on screen and figure out "
            "where to click. For links/buttons/fields inside Jarvis's own "
            "browser tabs specifically, browser_fill_and_submit is more "
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
            "clicks first now. Get x/y from describe_screen or "
            "find_text_on_screen. Pastes via the clipboard so any text "
            "(including emoji/unicode) comes through reliably, restores "
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
