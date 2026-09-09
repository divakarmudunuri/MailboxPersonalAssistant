"""The pre-triage ignore list: a JSON file of senders to ignore before any model call, grouped by reason.

Kept apart from long-term memory so ignored senders never crowd the preferences the model reads.
"""

import json
from dataclasses import asdict

from mail_assistant.config.__app_config__ import PRE_TRIAGE_IGNORE_FILE
from mail_assistant.models.__pre_triage_ignore_model__ import IgnoreEntry, IgnoreReason

# Which triage rules mean "this sender is always ignorable", and the reason to file them under. Rules that judge one
# email (a meeting outside working hours, `none`) are deliberately absent: they say nothing about the sender.
RULE_TO_REASON: dict[str, IgnoreReason] = {
    "gmail_promotions": IgnoreReason.PROMOTIONS,
    "marketing_promotions": IgnoreReason.PROMOTIONS,
    "gmail_social": IgnoreReason.SOCIAL,
    "gmail_spam": IgnoreReason.SPAM,
    "spam_suspicious": IgnoreReason.SPAM,
    "subscription_renewals": IgnoreReason.SUBSCRIPTION,
    "cc_fyi_threads": IgnoreReason.NEWSLETTER,
    "fyi_project_info": IgnoreReason.NOTIFICATION,
    "gmail_forums": IgnoreReason.SOCIAL,
}
REASON_WORDS = [  # fallback: the first matching word in the reason text decides the label
    (("newsletter", "digest"), IgnoreReason.NEWSLETTER),
    (("subscription", "renewal"), IgnoreReason.SUBSCRIPTION),
    (("spam", "suspicious", "phishing"), IgnoreReason.SPAM),
    (("notification", "recap", "automated", "notice"), IgnoreReason.NOTIFICATION),
    (("promotion", "marketing", "advertis", "sale", "offer"), IgnoreReason.PROMOTIONS),
]


def reason_for(rule: str, reason_text: str) -> IgnoreReason | None:
    """The ignore label an `ignore` decision implies for its sender, or None when the decision was about one email."""
    if rule in RULE_TO_REASON:
        return RULE_TO_REASON[rule]
    if rule.startswith("label_"):
        return IgnoreReason.MISCELLANEOUS
    if rule in ("none", "meeting_requests_time_filter", ""):
        return None
    lowered = reason_text.lower()
    matches = (label for words, label in REASON_WORDS if any(w in lowered for w in words))
    return next(matches, IgnoreReason.MISCELLANEOUS)


def load() -> list[IgnoreEntry]:
    """Every entry in the file; an absent file is an empty list."""
    if not PRE_TRIAGE_IGNORE_FILE.exists():
        return []
    raw = json.loads(PRE_TRIAGE_IGNORE_FILE.read_text())
    return [IgnoreEntry(IgnoreReason(e["ignore_reason_label"]), sorted(e["senders"])) for e in raw]


def save(entries: list[IgnoreEntry]) -> list[IgnoreEntry]:
    """Replace the file. Senders are lowercased, deduplicated, and appear under one label only (the last one wins)."""
    by_label: dict[IgnoreReason, list[str]] = {}
    seen: dict[str, IgnoreReason] = {}
    for entry in entries:
        for sender in entry.senders:
            seen[sender.strip().lower()] = entry.ignore_reason_label
    for sender, label in seen.items():
        if sender:
            by_label.setdefault(label, []).append(sender)
    cleaned = [IgnoreEntry(label, sorted(senders)) for label, senders in sorted(by_label.items())]
    PRE_TRIAGE_IGNORE_FILE.write_text(json.dumps([asdict(e) for e in cleaned], indent=2))
    return cleaned


def label_for(sender_address: str) -> IgnoreReason | None:
    """The reason a sender is on the list, or None."""
    address = sender_address.lower()
    return next((e.ignore_reason_label for e in load() if address in e.senders), None)


def add(sender_address: str, label: IgnoreReason) -> list[IgnoreEntry]:
    """Put a sender on the list under `label`, moving it if it was under another."""
    address = sender_address.lower()
    entries = [IgnoreEntry(e.ignore_reason_label, [s for s in e.senders if s != address]) for e in load()]
    entries.append(IgnoreEntry(label, [address]))
    return save(entries)


def remove(sender_address: str) -> list[IgnoreEntry]:
    """Take a sender off the list."""
    address = sender_address.lower()
    return save([IgnoreEntry(e.ignore_reason_label, [s for s in e.senders if s != address]) for e in load()])
