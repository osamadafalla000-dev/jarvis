"""List and close tabs in Jarvis's managed Google Chrome window."""

from __future__ import annotations

from . import tool


@tool(
    {
        "name": "list_open_tabs",
        "description": "List the tabs currently open in Jarvis's Chrome window.",
        "parameters": {"type": "object", "properties": {}},
    }
)
def list_open_tabs() -> dict:
    import browser_session

    tabs = browser_session.list_tabs()
    return {
        "tabs": [
            {"index": i, "title": page.title(), "url": page.url}
            for i, page in enumerate(tabs)
        ]
    }


@tool(
    {
        "name": "close_tab",
        "description": (
            "Close a tab in Jarvis's Chrome window. Pass either the tab's "
            "index (from list_open_tabs) or a hint that matches part of its "
            "title/URL. If neither is given, closes the most recently opened tab."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "index": {
                    "type": ["integer", "null"],
                    "description": "Tab index from list_open_tabs.",
                },
                "hint": {
                    "type": ["string", "null"],
                    "description": "Text matching part of the tab's title or URL.",
                },
            },
        },
    }
)
def close_tab(index: int | None = None, hint: str | None = None) -> dict:
    import browser_session

    tabs = browser_session.list_tabs()
    if not tabs:
        return {"status": "error", "message": "no tabs are currently open"}

    if index is not None:
        if not 0 <= index < len(tabs):
            return {"status": "error", "message": f"no tab at index {index}"}
        target = tabs[index]
    elif hint:
        hint_lower = hint.lower()
        matches = [p for p in tabs if hint_lower in p.title().lower() or hint_lower in p.url.lower()]
        if not matches:
            return {"status": "error", "message": f"no open tab matches '{hint}'"}
        target = matches[0]
    else:
        target = tabs[-1]

    title = target.title()
    browser_session.close_tab(target)
    return {"status": "closed", "title": title}
