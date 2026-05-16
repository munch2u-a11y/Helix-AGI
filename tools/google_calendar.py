"""
Helix — Google Calendar API Tools

Provides Google Calendar operations via action tags:
  [CALENDAR_CREATE:] title | start_time | end_time | description
  [CALENDAR_LIST:] days
  [CALENDAR_DELETE:] event_id

All operations use the shared Google OAuth2 credentials
from tools/google_auth.py.
"""

import logging
from datetime import datetime, timedelta

logger = logging.getLogger("helix.tools.google_calendar")


def calendar_create(title: str, start_time: str, end_time: str = "",
                    description: str = "", location: str = "") -> str:
    """Create a Google Calendar event."""
    from tools.google_auth import get_calendar_service

    service = get_calendar_service()
    if not service:
        return "Google Calendar not configured. Run google_auth.py first."

    if not title or not start_time:
        return "Title and start_time required."

    try:
        start = datetime.fromisoformat(start_time)
    except ValueError:
        return f"Invalid start_time format: {start_time}. Use ISO format like '2026-04-15T14:00:00'."

    if end_time:
        try:
            end = datetime.fromisoformat(end_time)
        except ValueError:
            end = start + timedelta(hours=1)
    else:
        end = start + timedelta(hours=1)

    try:
        event = {
            "summary": title,
            "description": description,
            "location": location,
            "start": {"dateTime": start.isoformat(), "timeZone": "America/New_York"},
            "end": {"dateTime": end.isoformat(), "timeZone": "America/New_York"},
        }

        result = service.events().insert(
            calendarId="primary", body=event
        ).execute()

        return (
            f"Event created: {title}\n"
            f"  ID: {result['id']}\n"
            f"  When: {start.strftime('%Y-%m-%d %H:%M')} — {end.strftime('%H:%M')}\n"
            f"  Location: {location or 'none'}\n"
            f"  Link: {result.get('htmlLink', '')}"
        )
    except Exception as e:
        return f"Calendar event creation failed: {e}"


def calendar_list(days_ahead: int = 7, count: int = 10) -> str:
    """List upcoming Google Calendar events."""
    from tools.google_auth import get_calendar_service

    service = get_calendar_service()
    if not service:
        return "Google Calendar not configured."

    try:
        now = datetime.utcnow()
        time_min = now.isoformat() + "Z"
        time_max = (now + timedelta(days=days_ahead)).isoformat() + "Z"

        response = service.events().list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            maxResults=count,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        events = response.get("items", [])
        if not events:
            return f"No events in the next {days_ahead} days."

        lines = [f"Upcoming events ({len(events)}):"]
        for e in events:
            start = e["start"].get("dateTime", e["start"].get("date", ""))
            lines.append(
                f"  [{e['id'][:12]}] {start[:16]} — {e.get('summary', '(untitled)')}"
                + (f" @ {e['location']}" if e.get("location") else "")
            )

        return "\n".join(lines)
    except Exception as e:
        return f"Calendar list failed: {e}"


def calendar_delete(event_id: str) -> str:
    """Delete a Google Calendar event by ID."""
    from tools.google_auth import get_calendar_service

    service = get_calendar_service()
    if not service:
        return "Google Calendar not configured."

    if not event_id:
        return "event_id required."

    try:
        service.events().delete(
            calendarId="primary", eventId=event_id
        ).execute()
        return f"Event '{event_id}' deleted."
    except Exception as e:
        return f"Calendar delete failed: {e}"
