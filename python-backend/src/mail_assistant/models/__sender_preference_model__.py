from dataclasses import dataclass

from mail_assistant.models.__email_message_model__ import Category


@dataclass(slots=True)
class SenderPreference:
    """Long-term memory about one sender: the latest triage decision, why, and how often they have been seen."""

    sender: str  # email address only, lowercased
    category: Category
    reason: str
    count: int = 1
