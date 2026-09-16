"""Best-effort periodic heartbeat from the laptop to the cloud relay's
heartbeat_server.py, so the cloud instance can tell the user honestly
whether this laptop's own Jarvis is actually up right now, instead of
guessing from a failed tool call.

Entirely opt-in: no-ops completely if JARVIS_HEARTBEAT_URL isn't set, which
is the case for anyone not running the cloud relay -- nothing changes for
them.
"""

from __future__ import annotations

import os
import threading
import time

import requests

HEARTBEAT_URL = os.environ.get("JARVIS_HEARTBEAT_URL")
HEARTBEAT_TOKEN = os.environ.get("JARVIS_HEARTBEAT_TOKEN")
# Must be comfortably shorter than tools/laptop_status.py's STALE_AFTER_SECONDS
# so one missed beat (a brief network blip) doesn't already read as "off".
HEARTBEAT_INTERVAL_SECONDS = float(os.environ.get("JARVIS_HEARTBEAT_INTERVAL_SECONDS", "120"))


def _loop() -> None:
    while True:
        try:
            requests.post(HEARTBEAT_URL, params={"token": HEARTBEAT_TOKEN}, timeout=10)
        except Exception:  # noqa: BLE001 - best-effort by design: a missed beat
            # just means the cloud relay reports "off" a little early if asked
            # right now, never a reason to crash the actual voice loop over a
            # network blip.
            pass
        time.sleep(HEARTBEAT_INTERVAL_SECONDS)


def start_if_configured() -> None:
    """Call once at startup (main.py's run_loop()). Starts a daemon thread
    that posts a heartbeat every HEARTBEAT_INTERVAL_SECONDS; does nothing at
    all if JARVIS_HEARTBEAT_URL isn't set."""
    if not HEARTBEAT_URL:
        return
    threading.Thread(target=_loop, daemon=True).start()
