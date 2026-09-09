from dataclasses import dataclass, field
from enum import StrEnum


class IgnoreReason(StrEnum):
    """Why a sender is ignored before triage. One word each, so the UI and the trace can show it."""

    PROMOTIONS = "promotions"  # marketing offers and the Gmail Promotions tab
    NEWSLETTER = "newsletter"  # recurring editorial mail and digests
    SOCIAL = "social"  # the Gmail Social tab
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
