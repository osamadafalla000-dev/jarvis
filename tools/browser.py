"""Basic browser automation via Playwright (free, open-source).

Opens a real, visible Chromium window so the user can see and take over
what Jarvis is doing — no headless "invisible" actions on their behalf.
"""

from __future__ import annotations

from . import tool


@tool(
    {
        "name": "browser_fill_and_submit",
        "description": (
            "Open a URL in a visible browser window and fill in one form field "
            "by its visible label or placeholder, optionally submitting it. "
            "For general web search use the `web_search` tool instead — major "
            "search engines like Google actively block automated browsers, so "
            "this tool is only reliable on ordinary websites/forms without "
            "bot-detection (e.g. Wikipedia, most login-free forms)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to open."},
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
            "required": ["url", "field_hint", "text"],
        },
    }
)
def browser_fill_and_submit(
    url: str, field_hint: str, text: str, submit: bool = True
) -> dict:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        try:
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded")

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
                page.wait_for_load_state("domcontentloaded")

            return {"status": "done", "page_title": page.title(), "final_url": page.url}
        finally:
            browser.close()
