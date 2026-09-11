"""Trace log: one JSON line per graph step, appended to TRACE_FILE. Most steps are about one email; the briefing
and the memory chat are not, and leave the email fields empty."""

import json
import threading
from dataclasses import asdict
from datetime import UTC, datetime

from mail_assistant.config.__app_config__ import TRACE_FILE
from mail_assistant.models.__email_message_model__ import EmailMessage
from mail_assistant.models.__trace_model__ import TraceEntry

_lock = threading.Lock()


def _append(entry: TraceEntry) -> TraceEntry:
    with _lock, TRACE_FILE.open("a") as f:
        f.write(json.dumps(asdict(entry)) + "\n")
    return entry


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# What a step did, as one stable id per line (`action_taken`):
#   manual_user_input: user_set_<category>, user_sent_reply, user_requested_retriage
#   pre_triage:        marked_user_reply_complete, ignored_by_gmail_label, ignored_by_label, ignored_by_ignore_list,
#                      notified_automated_sender, kept_for_triage, sent_to_triage
#   triage:            categorized_<category>, downgraded_to_notify, triage_failed
#   inbox_manager:     created_draft, scheduled_meeting, accepted_invitation, declined_invitation,
#                      tentative_invitation, answered_invitation, no_action, failed
#   inbox_report:      built_overview, reused_overview
#   memory_chat:       updated_rules, cleared_rules, rules_unchanged
#   memory:            every change to what pre_triage and triage learn from (who decided is in `rule`: model,
#                      user, feedback, memory_chat, scan): ignore_list_added, ignore_list_removed, keep_list_added,
#                      keep_list_removed, learned_rule_added, learned_rule_changed, learned_rule_removed,
#                      learned_rules_cleared


def record(step: str, message: EmailMessage, duration_ms: int, action_taken: str = "") -> TraceEntry:
    """Append what `step` decided for `message`; `action_taken` is the step's action id."""
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
        action_taken=action_taken,
    )
    return _append(entry)


def record_learning(
    action: str, subject: str, decided_by: str, reason: str, message: EmailMessage | None = None
) -> TraceEntry:
    """Append a `memory` line: one change to the ignore list, the keep list, or the learned rules. `subject` is the
    sender or rule name, `decided_by` who caused it, and the email fields are filled when an email was behind it."""
    entry = TraceEntry(
        at=_now(),
        step="memory",
        email_id=message.id if message else "",
        sender=message.sender if message else "",
        subject=subject,
        category=message.category.value if message else "",
        rule=decided_by,
        reason=reason,
        duration_ms=0,
        action_taken=action,
    )
    return _append(entry)


def record_run(step: str, subject: str, rule: str, reason: str, duration_ms: int, action_taken: str = "") -> TraceEntry:
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
        action_taken=action_taken,
    )
    return _append(entry)


def list_traces(q: str, page: int, page_size: int, step: str = "") -> tuple[list[TraceEntry], int]:
    """One page of trace entries, newest first, filtered by step ("" = every step) and a case-insensitive text match,
    plus the total count."""
    if not TRACE_FILE.exists():
        return [], 0
    entries = [TraceEntry(**json.loads(line)) for line in TRACE_FILE.read_text().splitlines() if line.strip()]
    q = q.lower()
    text = lambda e: f"{e.step} {e.sender} {e.subject} {e.category} {e.rule} {e.reason} {e.action_taken}".lower()  # noqa: E731
    rows = [e for e in reversed(entries) if (not step or e.step == step) and q in text(e)]
    start = (page - 1) * page_size
    return rows[start : start + page_size], len(rows)
