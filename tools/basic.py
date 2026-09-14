"""First-pass tools: clock, launching apps/URLs, local file search."""

from __future__ import annotations

import datetime
import os
import subprocess
import time
from pathlib import Path

from . import tool

# Common spoken app names -> the command Windows can actually launch.
# Anything not in this map is passed straight to `os.startfile`, which also
# resolves plain .exe names found on PATH or registered under App Paths.
_APP_ALIASES = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "explorer": "explorer.exe",
    "file explorer": "explorer.exe",
    "paint": "mspaint.exe",
    "task manager": "taskmgr.exe",
    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",
    "edge": "msedge.exe",
    "spotify": "spotify.exe",
    "vscode": "code.exe",
    "vs code": "code.exe",
    "visual studio code": "code.exe",
}

# Some apps' actual running process differs from their launch command --
# most notably Windows 11's Calculator: `calc.exe` is a legacy launcher
# stub that redirects to the real Store-packaged process, CalculatorApp.exe.
# taskkill needs the real process name, not the launch command.
_CLOSE_PROCESS_NAMES = {
    "calculator": "CalculatorApp.exe",
    "calc": "CalculatorApp.exe",
}


@tool(
    {
        "name": "get_current_datetime",
        "description": "Get the current local date and time.",
        "parameters": {"type": "object", "properties": {}},
    }
)
def get_current_datetime() -> dict:
    now = datetime.datetime.now()
    return {
        "iso": now.isoformat(timespec="seconds"),
        "day_of_week": now.strftime("%A"),
        "date": now.strftime("%B %d, %Y"),
        "time": now.strftime("%I:%M %p"),
    }


@tool(
    {
        "name": "open_application",
        "description": (
            "Open a desktop application by name, e.g. 'notepad', 'calculator', "
            "'chrome', 'file explorer'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The application's common name.",
                }
            },
            "required": ["name"],
        },
    }
)
def open_application(name: str) -> dict:
    command = _APP_ALIASES.get(name.strip().lower(), name)
    try:
        os.startfile(command)  # noqa: S606 - user-invoked, local desktop app launch
        return {"status": "opened", "app": command}
    except OSError as exc:
        return {"status": "error", "app": command, "error": str(exc)}


@tool(
    {
        "name": "close_application",
        "description": (
            "Close a running desktop application by name, e.g. 'notepad', "
            "'calculator', 'chrome'. Tries a normal close first, which lets "
            "the app prompt to save unsaved work if it has any -- only pass "
            "force=true if a normal close doesn't work, since that can lose "
            "unsaved work."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The application's common name.",
                },
                "force": {
                    "type": ["boolean", "null"],
                    "description": (
                        "Force-kill instead of a normal close (default false)."
                    ),
                },
            },
            "required": ["name"],
        },
    }
)
def close_application(name: str, force: bool = False) -> dict:
    key = name.strip().lower()
    exe_name = _CLOSE_PROCESS_NAMES.get(key)
    if exe_name is None:
        command = _APP_ALIASES.get(key, name)
        exe_name = command if command.lower().endswith(".exe") else f"{command}.exe"

    args = ["taskkill", "/IM", exe_name]
    if force:
        args.append("/F")
    result = subprocess.run(args, capture_output=True, text=True)

    if result.returncode != 0:
        return {
            "status": "error",
            "app": exe_name,
            "message": (result.stderr or result.stdout).strip(),
        }

    if not force:
        # taskkill returns success as soon as the close is *requested* --
        # some apps (Windows Store/UWP-packaged ones especially, e.g. the
        # Windows 11 Calculator) ignore a plain close and keep running.
        # Verify it's actually gone before reporting success.
        time.sleep(0.5)
        check = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {exe_name}"],
            capture_output=True,
            text=True,
        )
        if exe_name.lower() in check.stdout.lower():
            return {
                "status": "still_running",
                "app": exe_name,
                "message": (
                    "close was requested but the app is still running "
                    "(common for Windows Store/UWP apps) -- retry with force=true"
                ),
            }

    return {"status": "closed", "app": exe_name, "forced": force}


@tool(
    {
        "name": "open_url",
        "description": (
            "Open a URL in a new tab of Jarvis's managed Google Chrome window "
            "(not the system's default browser). Tabs stay open across "
            "requests — use list_open_tabs / close_tab to manage them."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to open."}
            },
            "required": ["url"],
        },
    }
)
def open_url(url: str) -> dict:
    import browser_session

    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    page = browser_session.open_tab(url)
    return {"status": "opened", "url": url, "page_title": page.title()}


_DEFAULT_SEARCH_ROOTS = [
    Path.home() / "Downloads",
    Path.home() / "Documents",
    Path.home() / "Desktop",
]


@tool(
    {
        "name": "search_files",
        "description": (
            "Search for files by (partial) name under the user's common folders "
            "(Downloads, Documents, Desktop)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Filename or partial filename to search for.",
                },
                "max_results": {
                    "type": ["integer", "null"],
                    "description": "Maximum number of matches to return (default 10).",
                },
            },
            "required": ["query"],
        },
    }
)
def search_files(query: str, max_results: int = 10) -> dict:
    query_lower = query.lower()
    matches: list[str] = []
    for root in _DEFAULT_SEARCH_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and query_lower in path.name.lower():
                matches.append(str(path))
                if len(matches) >= max_results:
                    return {"matches": matches}
    return {"matches": matches}
