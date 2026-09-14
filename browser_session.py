"""A single persistent, visible Google Chrome window shared by every
browser-related tool, using its own dedicated profile (isolated from the
user's real day-to-day Chrome profile/session — never touches their actual
logins, history, or cookies). Tabs stay open across tool calls, including
ones the user opens by hand in that same window, and can be listed/closed/
acted on later by any tool.

Self-healing: if the browser connection has died (crashed, closed by hand,
etc.) any operation transparently relaunches a fresh session and retries
once, instead of leaving the process stuck with a dead reference.

Google login: Jarvis's profile starts logged out (it's a separate profile
dir, not the user's real one), which meant every Google site opened logged
out too. sync_google_login() copies the login cookies from one of the
user's REAL Chrome profiles into Jarvis's isolated one, so sites open
already signed in without Jarvis ever sharing a live browser process with
the user's actual day-to-day Chrome. ALLOWED_GOOGLE_PROFILES is a hardcoded
allowlist, not something the LLM can pick freely -- this machine has other
people's Google accounts logged into other Chrome profiles (e.g. a friend's
"Maria" profile), and those are deliberately NOT in this dict, so there's
no code path that can ever read their cookies, regardless of what any
prompt or tool argument says.
"""

from __future__ import annotations

import atexit
import os
import shutil
from pathlib import Path
from typing import Callable, TypeVar

from playwright.sync_api import BrowserContext, Page, sync_playwright

_playwright = None
_context: BrowserContext | None = None

PROFILE_DIR = Path(__file__).resolve().parent / ".chrome-profile"

# friendly name -> real Chrome profile folder name (under
# %LOCALAPPDATA%\Google\Chrome\User Data). Only the user's own profiles --
# never add a profile here without confirming whose account it actually is.
ALLOWED_GOOGLE_PROFILES = {
    "default": "Default",  # osamadafalla2@gmail.com, main/last-used
    "gemsgfm": "Profile 1",  # osama.d_5638@gemsgfm.com
    "badawithe": "Profile 3",  # badawithegoat@gmail.com
    "osamami": "Profile 4",  # osamadafalla294@gmail.com
}

T = TypeVar("T")


def sync_google_login(profile_key: str) -> dict:
    """Copy Google login cookies from one of the user's real Chrome
    profiles (see ALLOWED_GOOGLE_PROFILES) into Jarvis's isolated profile,
    then restart the browser session so the next tab opened picks it up.
    """
    if profile_key not in ALLOWED_GOOGLE_PROFILES:
        return {
            "status": "error",
            "message": f"'{profile_key}' isn't an allowed profile. Choose one of: "
            f"{', '.join(ALLOWED_GOOGLE_PROFILES)}.",
        }

    folder = ALLOWED_GOOGLE_PROFILES[profile_key]
    source = Path(os.environ["LOCALAPPDATA"]) / "Google" / "Chrome" / "User Data" / folder / "Network" / "Cookies"
    if not source.exists():
        return {"status": "error", "message": f"couldn't find that profile's cookies at {source}"}

    dest = PROFILE_DIR / "Default" / "Network" / "Cookies"
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Close Jarvis's own browser first so nothing has the destination file
    # open while we overwrite it.
    _reset()
    shutil.copyfile(source, dest)

    return {"status": "synced", "profile": profile_key}


def _reset() -> None:
    global _playwright, _context
    if _context is not None:
        try:
            _context.close()
        except Exception:  # noqa: BLE001
            pass
    if _playwright is not None:
        try:
            _playwright.stop()
        except Exception:  # noqa: BLE001
            pass
    _context = None
    _playwright = None


def get_context(force_new: bool = False) -> BrowserContext:
    global _playwright, _context

    if force_new:
        _reset()

    if _context is not None:
        try:
            _context.pages  # noqa: B018 - touch to verify the connection is still alive
            return _context
        except Exception:  # noqa: BLE001
            _reset()

    _playwright = sync_playwright().start()
    PROFILE_DIR.mkdir(exist_ok=True)
    # launch_persistent_context with channel="chrome": the real installed
    # Google Chrome (not Edge, not Playwright's bundled Chromium), but in a
    # dedicated profile dir Jarvis owns -- not the user's actual default
    # Chrome profile.
    _context = _playwright.chromium.launch_persistent_context(
        str(PROFILE_DIR), channel="chrome", headless=False
    )
    return _context


def _with_retry(action: Callable[[], T]) -> T:
    try:
        return action()
    except Exception:  # noqa: BLE001 - connection may have died; force a fresh one and retry once
        get_context(force_new=True)
        return action()


def open_tab(url: str) -> Page:
    def _do() -> Page:
        page = get_context().new_page()
        page.goto(url, wait_until="domcontentloaded")
        return page

    return _with_retry(_do)


def list_tabs() -> list[Page]:
    def _do() -> list[Page]:
        return [p for p in get_context().pages if not p.is_closed()]

    return _with_retry(_do)


def find_tab(index: int | None = None, hint: str | None = None) -> Page | None:
    """Resolve a tab from any currently open one -- including tabs the user
    opened by hand in the same window -- by index, a title/URL hint, or the
    most recently opened/focused tab if neither is given."""
    tabs = list_tabs()
    if not tabs:
        return None
    if index is not None:
        return tabs[index] if 0 <= index < len(tabs) else None
    if hint:
        hint_lower = hint.lower()
        for page in tabs:
            if hint_lower in page.title().lower() or hint_lower in page.url.lower():
                return page
        return None
    return tabs[-1]


def close_tab(page: Page) -> None:
    if not page.is_closed():
        page.close()


def shutdown() -> None:
    _reset()


atexit.register(shutdown)
