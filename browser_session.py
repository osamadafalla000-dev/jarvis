"""Jarvis's browser control: connects to the user's REAL, already-running
Chrome via its remote-debugging (CDP) port, instead of a separate isolated
profile. This gives Jarvis the user's actual logged-in sessions directly.

A prior isolated-profile design tried copying login cookies from the
user's real Chrome into a separate profile instead -- that turned out not
to work on modern Chrome: App-Bound Encryption ties cookies to the specific
profile they were encrypted for, specifically to prevent copying them
elsewhere. Confirmed live (copied cookies, opened Gmail, landed on the
logged-out marketing page instead of an inbox) before abandoning it.

The tradeoff of connecting directly instead: Jarvis now has the same
access the user has in that Chrome window -- whatever's logged in, every
open tab -- not a sandboxed copy. Chrome has to be launched with
--remote-debugging-port first (see launch_chrome_debuggable.vbs); it can't
be added to an already-running Chrome retroactively.

Self-healing: if the CDP connection has died (Chrome closed, debug port
unreachable, etc.) any operation raises a clear, actionable error instead
of a cryptic Playwright traceback.
"""

from __future__ import annotations

import atexit
import os
import subprocess
import time
import urllib.request
from typing import Callable, TypeVar

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

_playwright = None
_browser: Browser | None = None
_context: BrowserContext | None = None

CHROME_EXE = os.environ.get(
    "JARVIS_CHROME_EXE", r"C:\Program Files\Google\Chrome\Application\chrome.exe"
)
# The tab Jarvis itself opened most recently *within the current user turn*
# (see start_new_turn) -- reused by open_tab() instead of always spawning a
# new one. Without this, "open a chrome tab, open gmail" as one described
# task -- however the model chunks it into open_url call(s) -- could open
# two separate tabs (confirmed live: exactly this happened). Deliberately
# reset every turn rather than persisted indefinitely, so an unrelated
# request 10 minutes later still gets its own fresh tab instead of
# hijacking/navigating away from a tab the user might still be using.
_turn_tab: Page | None = None

CDP_PORT = int(os.environ.get("JARVIS_CHROME_DEBUG_PORT", "9222"))
CDP_URL = f"http://localhost:{CDP_PORT}"

T = TypeVar("T")


def _chrome_running() -> bool:
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq chrome.exe", "/NH"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return "chrome.exe" in result.stdout.lower()
    except Exception:  # noqa: BLE001 - can't tell either way; assume running so we don't launch a duplicate
        return True


def _try_auto_launch_chrome() -> bool:
    """If Chrome isn't running at all, launch it ourselves with the debug
    port enabled instead of just telling the user to do it by hand -- the
    user explicitly asked not to have to do this manually every time.
    Nothing to lose here: if Chrome has zero windows open there's no
    session/tabs an auto-launch could disrupt. If Chrome IS running, just
    without the flag, this deliberately does NOT touch it -- force-closing
    windows the user has open without asking could lose real work, so that
    case still needs the user to close Chrome themselves once."""
    if not os.path.exists(CHROME_EXE) or _chrome_running():
        return False
    try:
        subprocess.Popen([CHROME_EXE, f"--remote-debugging-port={CDP_PORT}"])
    except Exception:  # noqa: BLE001
        return False

    for _ in range(20):  # up to ~10s for Chrome to actually start listening
        time.sleep(0.5)
        try:
            urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=1)
            return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _reset() -> None:
    """Drop our connection to Chrome -- never closes the actual browser or
    its tabs. We don't own its lifecycle; the user does."""
    global _playwright, _browser, _context
    if _playwright is not None:
        try:
            _playwright.stop()
        except Exception:  # noqa: BLE001
            pass
    _context = None
    _browser = None
    _playwright = None


def get_context(force_new: bool = False) -> BrowserContext:
    global _playwright, _browser, _context

    if force_new:
        _reset()

    if _context is not None:
        try:
            _context.pages  # noqa: B018 - touch to verify the connection is still alive
            return _context
        except Exception:  # noqa: BLE001
            _reset()

    _playwright = sync_playwright().start()
    try:
        _browser = _playwright.chromium.connect_over_cdp(CDP_URL)
    except Exception as exc:
        _playwright.stop()
        _playwright = None
        if _try_auto_launch_chrome():
            return get_context(force_new=False)
        raise RuntimeError(
            "Can't reach Chrome's remote-debugging port. Chrome is already "
            "running without it enabled -- that flag only takes effect at "
            "launch, so it can't be turned on for an already-open window. "
            "Close every Chrome window (check the taskbar/system tray for "
            "lingering background processes too) and try again -- Jarvis "
            "will relaunch it debuggable itself once nothing's open."
        ) from exc

    # The browser's own existing context -- the user's actual, already
    # logged-in profile and open tabs, not a fresh/incognito one.
    _context = _browser.contexts[0] if _browser.contexts else _browser.new_context()
    return _context


def _with_retry(action: Callable[[], T]) -> T:
    try:
        return action()
    except Exception:  # noqa: BLE001 - connection may have died; force a fresh one and retry once
        get_context(force_new=True)
        return action()


def start_new_turn() -> None:
    """Call once at the start of each user message/ask() -- forgets the
    reusable tab so tab-reuse never bleeds across unrelated requests."""
    global _turn_tab
    _turn_tab = None


def open_tab(url: str, reuse: bool = True) -> Page:
    def _do() -> Page:
        global _turn_tab
        if reuse and _turn_tab is not None and not _turn_tab.is_closed():
            _turn_tab.goto(url, wait_until="domcontentloaded")
            return _turn_tab
        page = get_context().new_page()
        page.goto(url, wait_until="domcontentloaded")
        _turn_tab = page
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
