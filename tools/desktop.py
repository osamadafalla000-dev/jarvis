"""Desktop-level mouse/keyboard automation -- clicks and types into
whatever's on screen, in ANY window (any browser, any app), not just
Jarvis's own Playwright-controlled Chrome. Complements describe_screen:
look at the screen to find where something is, click there, then type.
"""

from __future__ import annotations

import time

import pyautogui
import pyperclip

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
            "Type text into a field -- any app, any browser, not just "
            "Jarvis's own browser tabs (use browser_fill_and_submit for "
            "those instead). STRONGLY prefer passing x/y (from "
            "describe_screen) so this clicks the field to focus it "
            "immediately before typing -- launching or switching to an app "
            "does NOT reliably give it keyboard focus (Windows blocks "
            "background processes from stealing focus), so typing with no "
            "x/y risks landing in whatever window the user actually has "
            "focused, which may not be the intended target at all. Only "
            "omit x/y if a click/type into this exact field already "
            "happened in the previous turn. Pastes via the clipboard so any "
            "text (including emoji/unicode) comes through reliably, and "
            "restores whatever was on the clipboard before."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to type."},
                "x": {
                    "type": ["integer", "null"],
                    "description": "Click here first to focus the field before typing. Strongly recommended.",
                },
                "y": {
                    "type": ["integer", "null"],
                    "description": "Click here first to focus the field before typing. Strongly recommended.",
                },
                "press_enter": {
                    "type": ["boolean", "null"],
                    "description": "Press Enter after typing (default false).",
                },
            },
            "required": ["text"],
        },
    }
)
def type_text(
    text: str, x: int | None = None, y: int | None = None, press_enter: bool = False
) -> dict:
    if x is not None and y is not None:
        pyautogui.click(x, y)
        time.sleep(0.1)  # let the click-triggered focus change actually land

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

    return {
        "status": "typed",
        "text": text,
        "clicked_first": x is not None and y is not None,
        "pressed_enter": press_enter,
    }
