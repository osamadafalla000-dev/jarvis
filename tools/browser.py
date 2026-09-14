"""Basic browser automation via Playwright (free, open-source).

Uses Jarvis's one persistent, visible Google Chrome window (browser_session)
so the user can see and take over what Jarvis is doing, and so the opened
tab stays around afterward — manage it with list_open_tabs / close_tab.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from . import tool


@tool(
    {
        "name": "browser_fill_and_submit",
        "description": (
            "Fill in one form field by its visible label or placeholder and "
            "optionally submit it, in either a NEW tab (pass url) or an "
            "EXISTING tab already open in Jarvis's Chrome window (pass "
            "tab_index or tab_hint instead of url) -- this can act on any "
            "currently open tab, including ones opened by hand, not just ones "
            "Jarvis itself opened. Waits for the page to actually finish "
            "loading, then screenshots it (sent automatically -- no need to "
            "separately call describe_screen/screenshot_tab after this). The "
            "tab stays open afterward — use close_tab when done. "
            "For general web search use the `web_search` tool instead — major "
            "search engines like Google actively block automated browsers, so "
            "this tool is only reliable on ordinary websites/forms without "
            "bot-detection (e.g. Wikipedia, most login-free forms)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": ["string", "null"],
                    "description": "URL to open in a new tab. Omit to act on an existing tab instead.",
                },
                "tab_index": {
                    "type": ["integer", "null"],
                    "description": "Index (from list_open_tabs) of an existing tab to act on instead of opening a new one.",
                },
                "tab_hint": {
                    "type": ["string", "null"],
                    "description": "Title/URL hint identifying an existing tab to act on instead of opening a new one.",
                },
                "field_hint": {
                    "type": "string",
                    "description": (
                        "Visible label, placeholder, or name attribute of the "
                        "field to type into, e.g. 'Search' or 'Email'."
                    ),
                },
                "text": {"type": "string", "description": "Text to type into the field."},
                "submit": {
                    "type": ["boolean", "null"],
                    "description": "Press Enter after typing (default true).",
                },
            },
            "required": ["field_hint", "text"],
        },
    }
)
def browser_fill_and_submit(
    field_hint: str,
    text: str,
    url: str | None = None,
    tab_index: int | None = None,
    tab_hint: str | None = None,
    submit: bool = True,
) -> dict:
    import browser_session

    if tab_index is not None or tab_hint is not None:
        page = browser_session.find_tab(index=tab_index, hint=tab_hint)
        if page is None:
            which = f"index {tab_index}" if tab_index is not None else f"'{tab_hint}'"
            return {"status": "error", "message": f"no open tab matches {which}"}
        if url:
            page.goto(url, wait_until="domcontentloaded")
    elif url:
        page = browser_session.open_tab(url)
    else:
        return {"status": "error", "message": "need either a url or a tab_index/tab_hint"}

    locator = page.get_by_label(field_hint)
    if locator.count() == 0:
        locator = page.get_by_placeholder(field_hint)
    if locator.count() == 0:
        locator = page.locator(f'[name="{field_hint}"]')
    if locator.count() == 0:
        return {
            "status": "error",
            "message": f"couldn't find a field matching '{field_hint}' on {url}",
        }

    locator.first.fill(text)
    if submit:
        locator.first.press("Enter")
        # Wait for the page to actually settle before screenshotting —
        # domcontentloaded fires before results render on most sites;
        # networkidle is a much stronger signal. Bounded so a page with
        # persistent connections (analytics, websockets) can't hang us.
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:  # noqa: BLE001 - timeout is fine, just proceed
            pass

    screenshot_path = Path(tempfile.mktemp(suffix=".png"))
    page.screenshot(path=str(screenshot_path))

    return {
        "status": "done",
        "page_title": page.title(),
        "final_url": page.url,
        "_attachment_path": str(screenshot_path),
    }
