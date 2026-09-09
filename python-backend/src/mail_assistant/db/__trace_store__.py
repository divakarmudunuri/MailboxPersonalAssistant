"""Trace log: one JSON line per graph step, appended to TRACE_FILE. Most steps are about one email; the briefing
and the memory chat are not, and leave the email fields empty."""

import json
from dataclasses import asdict
from datetime import UTC, datetime

from mail_assistant.config.__app_config__ import TRACE_FILE
from mail_assistant.models.__email_message_model__ import EmailMessage
from mail_assistant.models.__trace_model__ import TraceEntry


def _append(entry: TraceEntry) -> TraceEntry:
    with TRACE_FILE.open("a") as f:
        f.write(json.dumps(asdict(entry)) + "\n")
    return entry


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def record(step: str, message: EmailMessage, duration_ms: int) -> TraceEntry:
    """Append what `step` decided for `message`."""
    entry = TraceEntry(
        at=_now(),
        step=step,
        email_id=message.id,
        sender=message.sender,
        subject=message.subject,
        category=message.category.value,
        rule=message.applied_rule,
        reason=message.reason,
        duration_ms=duration_ms,
    )
    return _append(entry)


def record_run(step: str, subject: str, rule: str, reason: str, duration_ms: int) -> TraceEntry:
    """Append a step that is not about one email (the briefing, the memory chat): `subject` says what ran on."""
    entry = TraceEntry(
        at=_now(),
        step=step,
        email_id="",
        sender="",
        subject=subject,
        category="",
        rule=rule,
        reason=reason,
        duration_ms=duration_ms,
    )
    return _append(entry)


def list_traces(q: str, page: int, page_size: int, step: str = "") -> tuple[list[TraceEntry], int]:
    """One page of trace entries, newest first, filtered by step ("" = every step) and a case-insensitive text match,
    plus the total count."""
    if not TRACE_FILE.exists():
        return [], 0
    entries = [TraceEntry(**json.loads(line)) for line in TRACE_FILE.read_text().splitlines() if line.strip()]
    q = q.lower()
    text = lambda e: f"{e.step} {e.sender} {e.subject} {e.category} {e.rule} {e.reason}".lower()  # noqa: E731
    rows = [e for e in reversed(entries) if (not step or e.step == step) and q in text(e)]
    start = (page - 1) * page_size
    return rows[start : start + page_size], len(rows)
