"""Tiny always-on heartbeat receiver, meant to run on the cloud relay
alongside telegram_bot.py (see README's "Always-on cloud relay" section).

The laptop's own Jarvis (heartbeat_client.py, started from main.py's
run_loop()) posts here every couple minutes while it's actually running.
tools/laptop_status.py reads the timestamp this writes to answer "is my
laptop on?" with a real, specific answer instead of a guess.

Deliberately stdlib-only (http.server) -- this is one more small process to
keep alive on the cloud VM, not worth a whole new dependency (Flask etc.)
just for a single endpoint that writes one timestamp to a file.
"""

from __future__ import annotations

import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PORT = int(os.environ.get("JARVIS_HEARTBEAT_PORT", "8765"))
# Shared secret so a random port-scanner can't fake "the laptop's on" --
# set the same value in both this host's and the laptop's .env.
TOKEN = os.environ.get("JARVIS_HEARTBEAT_TOKEN")
STATE_PATH = Path(__file__).parent / "laptop_heartbeat.json"


def _write_heartbeat() -> None:
    STATE_PATH.write_text(json.dumps({"last_seen": time.time()}))


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - http.server's naming convention
        parsed = urlparse(self.path)
        if parsed.path != "/heartbeat":
            self.send_response(404)
            self.end_headers()
            return
        token = (parse_qs(parsed.query).get("token") or [None])[0]
        if TOKEN and token != TOKEN:
            self.send_response(403)
            self.end_headers()
            return
        _write_heartbeat()
        self.send_response(204)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass  # one line per heartbeat (every couple minutes, forever) isn't worth logging


def main() -> None:
    if not TOKEN:
        print(
            "WARNING: JARVIS_HEARTBEAT_TOKEN is not set -- anyone who finds "
            "this port open can send a fake heartbeat. Set it in .env here "
            "and pass the same value as the laptop's JARVIS_HEARTBEAT_TOKEN."
        )
    server = ThreadingHTTPServer(("0.0.0.0", PORT), _Handler)
    print(f"Heartbeat receiver listening on :{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
