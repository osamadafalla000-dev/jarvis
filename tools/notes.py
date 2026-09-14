"""Local Markdown notes — Jarvis's free "second brain". No cloud, no cost."""

from __future__ import annotations

from pathlib import Path

from . import tool

NOTES_DIR = Path(__file__).resolve().parent.parent / "notes"
NOTES_DIR.mkdir(exist_ok=True)


@tool(
    {
        "name": "search_notes",
        "description": "Search the user's local notes for a keyword or phrase.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword or phrase to search for.",
                }
            },
            "required": ["query"],
        },
    }
)
def search_notes(query: str) -> dict:
    query_lower = query.lower()
    matches = []
    for path in NOTES_DIR.rglob("*.md"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        idx = text.lower().find(query_lower)
        if idx == -1:
            continue
        start, end = max(0, idx - 100), min(len(text), idx + 200)
        matches.append({"file": path.name, "snippet": text[start:end].strip()})
    return {"matches": matches}


@tool(
    {
        "name": "add_note",
        "description": "Save a new note to the user's local notes folder.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Short title for the note (used as the filename).",
                },
                "content": {"type": "string", "description": "The note's content."},
            },
            "required": ["title", "content"],
        },
    }
)
def add_note(title: str, content: str) -> dict:
    safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in title).strip()
    path = NOTES_DIR / f"{safe_name or 'note'}.md"
    path.write_text(content, encoding="utf-8")
    return {"status": "saved", "file": str(path)}
