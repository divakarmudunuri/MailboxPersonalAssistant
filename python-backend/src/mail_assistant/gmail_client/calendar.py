"""Google Calendar over the Calendar API, on the same OAuth token as the mailbox. Only the primary calendar is used."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from googleapiclient.discovery import build

from mail_assistant.config.__app_config__ import GMAIL_ADDRESS

from .auth import load_credentials

log = logging.getLogger(__name__)
CALENDAR = "primary"


class GoogleCalendarClient:
    """Reads and writes events on the primary calendar."""

    def __init__(self) -> None:
        self._service = build("calendar", "v3", credentials=load_credentials(), cache_discovery=False)

    def _events(self):
        return self._service.events()

    @staticmethod
    def _summarize(event: dict[str, Any]) -> dict[str, Any]:
        me = (GMAIL_ADDRESS or "").lower()
        mine = next((a for a in event.get("attendees", []) if a.get("email", "").lower() == me), {})
        return {
            "event_id": event.get("id", ""),
            "ical_uid": event.get("iCalUID", ""),
            "summary": event.get("summary", ""),
            "start": event.get("start", {}).get("dateTime") or event.get("start", {}).get("date", ""),
            "end": event.get("end", {}).get("dateTime") or event.get("end", {}).get("date", ""),
            "organizer": event.get("organizer", {}).get("email", ""),
            "my_response": mine.get("responseStatus", ""),
            "link": event.get("htmlLink", ""),
        }

    def find_events(self, query: str = "", days: int = 14) -> list[dict[str, Any]]:
        """Events from now to `days` ahead, optionally matching a free-text query, earliest first."""
        now = datetime.now(UTC)
        listed = (
            self._events()
            .list(
                calendarId=CALENDAR,
                timeMin=now.isoformat(),
                timeMax=(now + timedelta(days=days)).isoformat(),
                q=query or None,
                singleEvents=True,
                orderBy="startTime",
                maxResults=50,
            )
            .execute()
        )
        return [self._summarize(e) for e in listed.get("items", [])]

    def find_by_ical_uid(self, ical_uid: str) -> dict[str, Any] | None:
        """The calendar's copy of an emailed invitation, matched by the invitation's UID."""
        listed = self._events().list(calendarId=CALENDAR, iCalUID=ical_uid, maxResults=1).execute()
        items = listed.get("items", [])
        return self._summarize(items[0]) if items else None

    def create_event(
        self, summary: str, start: str, end: str, description: str = "", reminder_minutes: int = 30
    ) -> dict[str, Any]:
        """Create an event; `start` and `end` are ISO-8601 with a UTC offset. A popup reminder is attached."""
        body = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start},
            "end": {"dateTime": end},
            "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": reminder_minutes}]},
        }
        return self._summarize(self._events().insert(calendarId=CALENDAR, body=body).execute())

    def respond(self, event_id: str, response: str) -> dict[str, Any]:
        """Set this account's RSVP on an event: accepted, declined, or tentative. Sends the update to the organizer."""
        event = self._events().get(calendarId=CALENDAR, eventId=event_id).execute()
        me = (GMAIL_ADDRESS or "").lower()
        attendees = event.get("attendees", [])
        for attendee in attendees:
            if attendee.get("email", "").lower() == me:
                attendee["responseStatus"] = response
                break
        else:
            attendees.append({"email": GMAIL_ADDRESS, "responseStatus": response})
        updated = (
            self._events()
            .patch(calendarId=CALENDAR, eventId=event_id, body={"attendees": attendees}, sendUpdates="all")
            .execute()
        )
        return self._summarize(updated)
