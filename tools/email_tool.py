"""Gmail tool — free (your own Google account).

Reads unread mail and creates drafts only. Jarvis never calls a "send"
endpoint — every draft requires the human to open Gmail and click send.
"""

from __future__ import annotations

import base64
from email.mime.text import MIMEText

from googleapiclient.discovery import build

from google_auth import get_credentials

from . import tool


def _service():
    return build("gmail", "v1", credentials=get_credentials())


@tool(
    {
        "name": "get_unread_emails",
        "description": "List recent unread emails (sender and subject only).",
        "parameters": {
            "type": "object",
            "properties": {
                "max_results": {
                    "type": ["integer", "null"],
                    "description": "Maximum number of emails to return (default 5).",
                }
            },
        },
    }
)
def get_unread_emails(max_results: int = 5) -> dict:
    service = _service()
    listing = (
        service.users()
        .messages()
        .list(userId="me", labelIds=["UNREAD", "INBOX"], maxResults=max_results)
        .execute()
    )

    unread = []
    for item in listing.get("messages", []):
        msg = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=item["id"],
                format="metadata",
                metadataHeaders=["From", "Subject"],
            )
            .execute()
        )
        headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
        unread.append(
            {"from": headers.get("From", ""), "subject": headers.get("Subject", "")}
        )
    return {"unread": unread}


@tool(
    {
        "name": "create_email_draft",
        "description": (
            "Create a draft email in Gmail. This does NOT send it — the user "
            "must open Gmail and click send themselves."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address."},
                "subject": {"type": "string", "description": "Email subject line."},
                "body": {"type": "string", "description": "Email body text."},
            },
            "required": ["to", "subject", "body"],
        },
    }
)
def create_email_draft(to: str, subject: str, body: str) -> dict:
    service = _service()
    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    draft = (
        service.users()
        .drafts()
        .create(userId="me", body={"message": {"raw": raw}})
        .execute()
    )
    return {"status": "draft_created_not_sent", "draft_id": draft["id"]}
