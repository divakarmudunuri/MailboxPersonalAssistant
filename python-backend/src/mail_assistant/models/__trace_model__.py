from dataclasses import dataclass


@dataclass(slots=True)
class TraceEntry:
    """One graph step as written to the trace file; the email fields are empty for the briefing and the memory chat."""

    at: str  # ISO timestamp, UTC
    step: str  # manual_user_input | pre_triage | triage | inbox_manager | inbox_report | memory_chat
    email_id: str
    sender: str
    subject: str
    category: str  # the category after this step
    rule: str  # the rule applied by this step, or ""
    reason: str
    duration_ms: int
    action_taken: str = ""  # what the step did, one id from the vocabulary in db/__trace_store__.py
