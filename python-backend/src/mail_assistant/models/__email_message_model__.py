from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Category(StrEnum):
    """What the assistant decided to do with an email."""

    IGNORE = "ignore"
    NOTIFY = "notify"
    AGENT_RESPOND = "agentrespond"
    USER_REPLY_COMPLETE = "user_reply_complete"
    AGENT_DRAFT_ONLY = "agentdraftonly"
    PENDING = "pending"


@dataclass(slots=True)
class EmailMessage:
    """A Gmail message reduced to the fields the assistant needs, plus its processing decision."""

    id: str
    thread_id: str
    subject: str
    sender: str
    received_at: datetime
    snippet: str
    body_text: str
    label_ids: list[str]
    category: Category = Category.PENDING
    reason: str = ""
    applied_rule: str = ""  # name of the base or learned rule behind the decision; "pre_triage" when triage was skipped
    action: str = ""  # what the inbox manager did for agentrespond / agentdraftonly mail, in one line
