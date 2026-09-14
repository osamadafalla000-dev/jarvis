"""Shared Google OAuth helper for the Calendar and Gmail tools.

Free (uses the user's own Google account and a free Google Cloud project),
but requires a one-time setup — see README.md for the Cloud Console steps.
"""

from __future__ import annotations

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# gmail.compose is required to create drafts; Jarvis never calls a "send"
# endpoint in code, so drafts always require the human to open Gmail and
# click send themselves, regardless of what the OAuth scope technically permits.
SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]

_ROOT = Path(__file__).resolve().parent
CREDENTIALS_PATH = _ROOT / "credentials.json"
TOKEN_PATH = _ROOT / "token.json"


def get_credentials() -> Credentials:
    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_PATH.exists():
                raise RuntimeError(
                    "Missing credentials.json. Download OAuth client credentials "
                    "from Google Cloud Console (Desktop app type) and save them "
                    "as credentials.json in the project root — see README.md."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_PATH), SCOPES
            )
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")

    return creds
