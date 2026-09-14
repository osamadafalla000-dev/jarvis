"""A single persistent, visible Google Chrome window shared by every
browser-related tool, so tabs stay open across tool calls and can be
listed/closed later — instead of a fresh throwaway browser per action.
"""

from __future__ import annotations

import atexit

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

_playwright = None
_browser: Browser | None = None
_context: BrowserContext | None = None


def get_context() -> BrowserContext:
    global _playwright, _browser, _context

    if _context is not None and _browser is not None and _browser.is_connected():
        return _context

    if _playwright is None:
        _playwright = sync_playwright().start()

    # channel="chrome" uses the user's actual installed Google Chrome,
    # not Playwright's bundled Chromium.
    _browser = _playwright.chromium.launch(channel="chrome", headless=False)
    _context = _browser.new_context()
    return _context


def open_tab(url: str) -> Page:
    context = get_context()
    page = context.new_page()
    page.goto(url, wait_until="domcontentloaded")
    return page


def list_tabs() -> list[Page]:
    if _context is None:
        return []
    return [p for p in _context.pages if not p.is_closed()]


def close_tab(page: Page) -> None:
    if not page.is_closed():
        page.close()


def shutdown() -> None:
    global _playwright, _browser, _context
    if _browser is not None:
        try:
            _browser.close()
        except Exception:  # noqa: BLE001
            pass
    if _playwright is not None:
        try:
            _playwright.stop()
        except Exception:  # noqa: BLE001
            pass
    _browser = None
    _context = None
    _playwright = None


atexit.register(shutdown)
