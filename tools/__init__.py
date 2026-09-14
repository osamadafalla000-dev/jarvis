"""Tool registry for the Jarvis LLM tool-calling loop."""

_TOOLS: dict[str, dict] = {}


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
    try:
        return _TOOLS[name]["func"](**arguments)
    except Exception as exc:  # noqa: BLE001 - surface any tool failure to the LLM
        return {"error": str(exc)}


# Import tool modules so their @tool decorators register on package import.
from . import basic  # noqa: E402,F401
from . import calendar_tool  # noqa: E402,F401
from . import email_tool  # noqa: E402,F401
from . import notes  # noqa: E402,F401
from . import web_search  # noqa: E402,F401
