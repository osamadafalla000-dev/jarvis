"""Free web search (no API key) via DDGS (formerly duckduckgo-search)."""

from __future__ import annotations

from ddgs import DDGS

from . import tool


@tool(
    {
        "name": "web_search",
        "description": "Search the web for current information not otherwise known.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query."},
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default 5).",
                },
            },
            "required": ["query"],
        },
    }
)
def web_search(query: str, max_results: int = 5) -> dict:
    with DDGS() as ddgs:
        results = list(ddgs.text(query, max_results=max_results))
    return {
        "results": [
            {
                "title": r.get("title"),
                "snippet": r.get("body"),
                "url": r.get("href"),
            }
            for r in results
        ]
    }
