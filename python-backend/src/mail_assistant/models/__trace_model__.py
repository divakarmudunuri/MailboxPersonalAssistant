from dataclasses import dataclass


@dataclass(slots=True)
class TraceEntry:
    """One step of the triage graph applied to one email, as written to the trace file."""

    at: str  # ISO timestamp, UTC
    step: str  # pre_triage | triage
    email_id: str
    sender: str
    subject: str
    category: str  # the category after this step
    rule: str  # the rule applied by this step, or ""
    reason: str
    duration_ms: int
