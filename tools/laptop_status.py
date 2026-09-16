"""Reports whether the laptop's own Jarvis has checked in recently, via the
heartbeat file heartbeat_server.py writes when running as the cloud relay.
Lets Jarvis answer "is my laptop on?" with a real, specific answer instead
of a guess, and give actual timing ("hasn't checked in for 42 minutes")
whenever a screen-control request can't be done from this instance.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from . import tool

STATE_PATH = Path(__file__).parent.parent / "laptop_heartbeat.json"

# How stale a heartbeat can be before the laptop counts as "off" rather than
# just running a bit slow -- comfortably more than heartbeat_client.py's own
# send interval (2 minutes by default) so one missed beat from a brief
# network blip doesn't falsely read as "dead".
STALE_AFTER_SECONDS = 6 * 60


@tool(
    {
        "name": "get_laptop_status",
        "description": (
            "Check whether the laptop's own Jarvis instance has checked in "
            "recently (it heartbeats every couple minutes while it's on and "
            "connected). Use this whenever the user asks if their laptop "
            "is on/off/reachable, and whenever a screen-control request "
            "can't be done from this instance -- it gives a real, specific "
            "answer ('checked in 3 minutes ago' vs 'hasn't checked in for "
            "2 hours') instead of a vague guess. Only meaningful on the "
            "cloud relay with a laptop heartbeat sender configured; returns "
            "status 'unknown' otherwise (e.g. running directly on the "
            "laptop, or the heartbeat isn't set up)."
        ),
        "parameters": {"type": "object", "properties": {}},
    }
)
def get_laptop_status() -> dict:
    if not STATE_PATH.exists():
        return {
            "status": "unknown",
            "detail": (
                "no heartbeat has ever been recorded -- either the laptop's "
                "heartbeat sender isn't configured, or this isn't running "
                "as the cloud relay"
            ),
        }
    try:
        last_seen = json.loads(STATE_PATH.read_text())["last_seen"]
    except (json.JSONDecodeError, KeyError, OSError) as exc:
        return {"status": "unknown", "detail": f"couldn't read heartbeat state: {exc}"}

    age_minutes = round((time.time() - last_seen) / 60, 1)
    if age_minutes * 60 <= STALE_AFTER_SECONDS:
        return {"status": "on", "detail": f"checked in {age_minutes} minute(s) ago"}
    return {
        "status": "off",
        "detail": f"hasn't checked in for {age_minutes} minute(s) -- likely off or offline",
    }
