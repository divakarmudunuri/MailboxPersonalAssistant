"""Trace log: one JSON line per graph step per email, appended to TRACE_FILE."""

import json
from dataclasses import asdict
from datetime import UTC, datetime

from mail_assistant.config.__app_config__ import TRACE_FILE
from mail_assistant.models.__email_message_model__ import EmailMessage
from mail_assistant.models.__trace_model__ import TraceEntry


def record(step: str, message: EmailMessage, duration_ms: int) -> TraceEntry:
    """Append what `step` decided for `message`."""
    entry = TraceEntry(
        at=datetime.now(UTC).isoformat(timespec="seconds"),
        step=step,
        email_id=message.id,
        sender=message.sender,
        subject=message.subject,
        category=message.category.value,
        rule=message.applied_rule,
        reason=message.reason,
        duration_ms=duration_ms,
    )
    with TRACE_FILE.open("a") as f:
        f.write(json.dumps(asdict(entry)) + "\n")
    return entry


def list_traces(q: str, page: int, page_size: int) -> tuple[list[TraceEntry], int]:
    """One page of trace entries, newest first, filtered by a case-insensitive text match, plus the total count."""
    if not TRACE_FILE.exists():
        return [], 0
    entries = [TraceEntry(**json.loads(line)) for line in TRACE_FILE.read_text().splitlines() if line.strip()]
    q = q.lower()
    text = lambda e: f"{e.step} {e.sender} {e.subject} {e.category} {e.rule} {e.reason}".lower()  # noqa: E731
    rows = [e for e in reversed(entries) if q in text(e)]
    start = (page - 1) * page_size
    return rows[start : start + page_size], len(rows)
