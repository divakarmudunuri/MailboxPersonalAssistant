"""Calendar tools for the inbox manager: read an emailed invite, look up events, create reminders, answer invites."""

import json
import re
from functools import cache

from langchain_core.tools import tool

from mail_assistant.agents.tools.__gmail_tools__ import _mailbox
from mail_assistant.gmail_client.calendar import GoogleCalendarClient

RESPONSES = ("accepted", "declined", "tentative")


@cache
def _calendar() -> GoogleCalendarClient:
    return GoogleCalendarClient()


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1)


def parse_ics(text: str) -> dict[str, str]:
    """The fields of an iCalendar invitation that matter: UID, summary, start, end, organizer, method."""
    unfolded = re.sub(r"\r?\n[ \t]", "", text)  # long lines are folded with a leading space
    fields = {}
    for key in ("UID", "SUMMARY", "DTSTART", "DTEND", "ORGANIZER", "METHOD", "LOCATION"):
        match = re.search(rf"^{key}(?:;[^:\n]*)?:(.*)$", unfolded, re.MULTILINE)
        if match:
            fields[key.lower()] = match.group(1).strip()
    return fields


@tool
def invite_details(message_id: str) -> str:
    """The meeting invitation attached to an email, if any: its UID, title, start, end, and organizer, plus the
    calendar's own copy of the event with your current response. Empty when the email holds no invitation."""
    mailbox = _mailbox()
    part = next((p for p in mailbox.list_parts(message_id) if p["content_type"] == "text/calendar"), None)
    if not part:
        return _dump({})
    ics = parse_ics(mailbox.get_part(message_id, part["index"], chars=20000).get("text", ""))
    event = _calendar().find_by_ical_uid(ics["uid"]) if ics.get("uid") else None
    return _dump({"invitation": ics, "calendar_event": event})


@tool
def find_calendar_events(query: str = "", days: int = 14) -> str:
    """Events on the calendar from now to `days` ahead, optionally filtered by a free-text query. Check before
    creating a reminder so nothing is duplicated."""
    return _dump(_calendar().find_events(query, days))


@tool
def create_reminder(title: str, start: str, end: str = "", notes: str = "", reminder_minutes: int = 30) -> str:
    """Create a calendar event with a popup reminder. `start` and `end` are ISO-8601 with a UTC offset, for example
    2026-09-12T10:30:00-04:00; `end` defaults to 30 minutes after start. Put the email's sender and subject in notes."""
    if not end:
        from datetime import datetime, timedelta

        end = (datetime.fromisoformat(start) + timedelta(minutes=30)).isoformat()
    return _dump(_calendar().create_event(title, start, end, notes, reminder_minutes))


@tool
def respond_to_invite(event_id: str, response: str) -> str:
    """Answer a meeting invitation already on the calendar: response is accepted, declined, or tentative. Use the
    event_id from invite_details. The organizer is notified."""
    if response not in RESPONSES:
        return f"response must be one of {', '.join(RESPONSES)}"
    return _dump(_calendar().respond(event_id, response))


CALENDAR_TOOLS = [invite_details, find_calendar_events, create_reminder, respond_to_invite]
