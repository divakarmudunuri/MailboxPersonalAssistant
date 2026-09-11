"""Calendar tools for the inbox manager: read an emailed invite, look up events, create reminders, answer invites."""

import json
import re
import threading
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from langchain_core.tools import tool

from mail_assistant.agents.tools.__gmail_tools__ import _mailbox
from mail_assistant.gmail_client.calendar import GoogleCalendarClient

RESPONSES = ("accepted", "declined", "tentative")


_local = threading.local()


def _calendar() -> GoogleCalendarClient:
    """One calendar client per thread: the Google API client is not thread-safe."""
    if not hasattr(_local, "calendar"):
        _local.calendar = GoogleCalendarClient()
    return _local.calendar


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1)


def _local_tz():
    return datetime.now().astimezone().tzinfo


def _ics_datetime(value: str, params: str) -> str:
    """An iCalendar DTSTART/DTEND as ISO-8601 with an offset: `20260909T220000Z`, `TZID=...:20260909T180000`, or a
    floating time taken as local."""
    tzid = re.search(r"TZID=([^;:]+)", params or "")
    raw = value.strip()
    if raw.endswith("Z"):
        return datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC).isoformat()
    if "T" not in raw:  # an all-day date
        return raw
    when = datetime.strptime(raw, "%Y%m%dT%H%M%S")
    return when.replace(tzinfo=ZoneInfo(tzid.group(1)) if tzid else _local_tz()).isoformat()


def parse_ics(text: str) -> dict[str, str]:
    """The fields of an iCalendar invitation that matter: UID, summary, start, end (ISO-8601 with offset), organizer,
    method, location."""
    unfolded = re.sub(r"\r?\n[ \t]", "", text)  # long lines are folded with a leading space
    # Only the event block: a VTIMEZONE block carries its own DTSTART (the daylight-saving rule, often in 1970).
    event = re.search(r"BEGIN:VEVENT(.*?)END:VEVENT", unfolded, re.S)
    scope = event.group(1) if event else unfolded
    fields = {}
    for key in ("UID", "SUMMARY", "DTSTART", "DTEND", "ORGANIZER", "METHOD", "LOCATION"):
        match = re.search(rf"^{key}(;[^:\n]*)?:(.*)$", scope if key != "METHOD" else unfolded, re.MULTILINE)
        if match:
            fields[key.lower()] = match.group(2).strip()
            if key in ("DTSTART", "DTEND"):
                fields[key.lower()] = _ics_datetime(match.group(2), match.group(1) or "")
    if fields.get("organizer", "").lower().startswith("mailto:"):
        fields["organizer"] = fields["organizer"][7:]
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
    if event is None and all(ics.get(k) for k in ("uid", "dtstart", "dtend")):
        # Google only adds Google invitations by itself; any other invitation is added here so it can be answered.
        event = _calendar().import_invitation(
            ics["uid"], ics.get("summary", "(no title)"), ics["dtstart"], ics["dtend"], ics.get("organizer", "")
        )
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
    try:
        begin = datetime.fromisoformat(start.strip())
        finish = datetime.fromisoformat(end.strip()) if end.strip() else begin + timedelta(minutes=30)
    except ValueError:
        return "start and end must be ISO-8601 like 2026-09-12T10:30:00-04:00; nothing was created"
    if begin.tzinfo is None:
        begin = begin.replace(tzinfo=_local_tz())
    if finish.tzinfo is None:
        finish = finish.replace(tzinfo=begin.tzinfo)
    if finish <= begin:
        return "end must be after start; nothing was created"
    if not timedelta(days=-1) < begin - datetime.now(begin.tzinfo) < timedelta(days=366):
        return f"start {begin.isoformat()} is in the past or more than a year ahead; nothing was created"
    same = [e for e in _calendar().find_events(title, days=60) if e["summary"].strip().lower() == title.strip().lower()]
    if any(e["start"][:16] == begin.isoformat()[:16] for e in same):
        return f"already on the calendar: {_dump(same[0])}"
    return _dump(_calendar().create_event(title, begin.isoformat(), finish.isoformat(), notes, reminder_minutes))


@tool
def respond_to_invite(event_id: str, response: str) -> str:
    """Answer a meeting invitation already on the calendar: response is accepted, declined, or tentative. Use the
    event_id from invite_details. The organizer is notified."""
    if response not in RESPONSES:
        return f"response must be one of {', '.join(RESPONSES)}"
    return _dump(_calendar().respond(event_id, response))


CALENDAR_TOOLS = [invite_details, find_calendar_events, create_reminder, respond_to_invite]
