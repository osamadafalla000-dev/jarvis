"""Google Calendar tool — free (your own Google account), read-only."""

from __future__ import annotations

import datetime

from googleapiclient.discovery import build

from google_auth import get_credentials

from . import tool


@tool(
    {
        "name": "get_calendar_events",
        "description": "List the user's upcoming Google Calendar events.",
        "parameters": {
            "type": "object",
            "properties": {
                "days_ahead": {
                    "type": "integer",
                    "description": "How many days ahead to look, starting now (default 1).",
                }
            },
        },
    }
)
def get_calendar_events(days_ahead: int = 1) -> dict:
    creds = get_credentials()
    service = build("calendar", "v3", credentials=creds)

    now = datetime.datetime.utcnow()
    time_min = now.isoformat() + "Z"
    time_max = (now + datetime.timedelta(days=days_ahead)).isoformat() + "Z"

    result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    events = [
        {
            "summary": event.get("summary", "(no title)"),
            "start": event["start"].get("dateTime", event["start"].get("date")),
        }
        for event in result.get("items", [])
    ]
    return {"events": events}
