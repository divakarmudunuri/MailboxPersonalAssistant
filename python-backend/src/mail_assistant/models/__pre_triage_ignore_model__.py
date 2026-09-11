from dataclasses import dataclass, field
from enum import StrEnum


class IgnoreReason(StrEnum):
    """Why a sender is ignored before triage. One word each, so the UI and the trace can show it."""

    PROMOTIONS = "promotions"  # marketing offers
    NEWSLETTER = "newsletter"  # recurring editorial mail and digests
    SOCIAL = "social"  # social-network mail
    FORUMS = "forums"  # mailing lists and forum digests
    SPAM = "spam"  # spam or suspicious
    SUBSCRIPTION = "subscription"  # service status and renewal recaps never acted on
    MARKETING = "marketing"  # marketing mail that is not a plain promotion
    NOTIFICATION = "notification"  # automated recaps and account notices with nothing to do
    MISCELLANEOUS = "miscellaneous"


@dataclass(slots=True)
class IgnoreEntry:
    """One reason and every sender address ignored for it."""

    ignore_reason_label: IgnoreReason
    senders: list[str] = field(default_factory=list)  # email addresses, lowercased
    added_by: dict[str, str] = field(default_factory=dict)  # sender -> "model" | "user" | "gmail" | "unknown"
