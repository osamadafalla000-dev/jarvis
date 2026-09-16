"""Tool registry for the Jarvis LLM tool-calling loop."""

import importlib
import sys

_TOOLS: dict[str, dict] = {}

# Modules whose import failed (e.g. tools/desktop.py's pyautogui needs a real
# display, which a headless always-on cloud/server deployment won't have) --
# populated by the import loop at the bottom of this file. llm.py reads this
# to tell the model plainly which capabilities aren't available from this
# particular instance, instead of it guessing or pretending.
UNAVAILABLE_MODULES: dict[str, str] = {}


def tool(schema: dict):
    """Decorator that registers a function as an LLM-callable tool.

    `schema` is the OpenAI/Groq-style function schema (name, description,
    parameters). The decorated function's return value is JSON-serialized
    and sent back to the model as the tool result.
    """

    def decorator(func):
        _TOOLS[schema["name"]] = {"schema": schema, "func": func}
        return func

    return decorator


def get_tool_schemas() -> list[dict]:
    return [{"type": "function", "function": t["schema"]} for t in _TOOLS.values()]


def call_tool(name: str, arguments: dict):
    if name not in _TOOLS:
        return {"error": f"unknown tool: {name}"}
    # Models sometimes emit `null` for an omitted optional argument instead of
    # leaving it out entirely — drop those so the function's own default applies.
    arguments = {k: v for k, v in arguments.items() if v is not None}
    try:
        return _TOOLS[name]["func"](**arguments)
    except Exception as exc:  # noqa: BLE001 - surface any tool failure to the LLM
        return {"error": str(exc)}


# Import tool modules so their @tool decorators register on package import.
# Each one is guarded individually: a module whose import needs something
# this host doesn't have (desktop.py's pyautogui needs a real display,
# browser.py/tabs.py's playwright is only useful with a real Chrome to
# connect to) shouldn't take down every other tool with it -- that would
# mean a headless cloud deployment can't even answer plain chat. A failed
# module's tools are simply absent from get_tool_schemas(), so the model
# never sees or tries to call them.
for _module_name in (
    "basic",
    "browser",
    "calendar_tool",
    "desktop",
    "email_tool",
    "laptop_status",
    "notes",
    "tabs",
    "vision",
    "web_search",
):
    try:
        importlib.import_module(f".{_module_name}", package=__name__)
    except Exception as exc:  # noqa: BLE001 - any missing optional dependency
        UNAVAILABLE_MODULES[_module_name] = str(exc)
        print(
            f"[tools] {_module_name}.py unavailable on this host, its tools "
            f"are disabled: {exc}",
            file=sys.stderr,
        )
