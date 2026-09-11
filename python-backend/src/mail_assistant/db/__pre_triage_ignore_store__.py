"""The pre-triage ignore list: a JSON file of senders to ignore before any model call, grouped by reason.

Kept apart from long-term memory so ignored senders never crowd the preferences the model reads.
"""

import json
import threading
from dataclasses import asdict

from mail_assistant.config.__app_config__ import PRE_TRIAGE_IGNORE_FILE
from mail_assistant.models.__pre_triage_ignore_model__ import IgnoreEntry, IgnoreReason

# Which triage rules mean "this sender is always ignorable", and the reason to file them under. Rules that judge one
# email (a meeting outside working hours, `none`) are deliberately absent: they say nothing about the sender.
RULE_TO_REASON: dict[str, IgnoreReason] = {
    "marketing_promotions": IgnoreReason.PROMOTIONS,
    "social_updates": IgnoreReason.SOCIAL,
    "forum_digests": IgnoreReason.FORUMS,
    "spam_suspicious": IgnoreReason.SPAM,
    "subscription_renewals": IgnoreReason.SUBSCRIPTION,
    "cc_fyi_threads": IgnoreReason.NEWSLETTER,
    "fyi_project_info": IgnoreReason.NOTIFICATION,
}
REASON_WORDS = [  # fallback: the first matching word in the reason text decides the label
    (("newsletter", "digest"), IgnoreReason.NEWSLETTER),
    (("subscription", "renewal"), IgnoreReason.SUBSCRIPTION),
    (("spam", "suspicious", "phishing"), IgnoreReason.SPAM),
    (("social", "linkedin", "facebook", "nextdoor", "friend request"), IgnoreReason.SOCIAL),
    (("forum", "mailing list", "discussion", "thread digest"), IgnoreReason.FORUMS),
    (("notification", "recap", "automated", "notice"), IgnoreReason.NOTIFICATION),
    (("promotion", "marketing", "advertis", "sale", "offer"), IgnoreReason.PROMOTIONS),
]


def reason_for(rule: str, reason_text: str) -> IgnoreReason | None:
    """The ignore label an `ignore` decision implies for its sender, or None when the decision was about one email."""
    if rule in RULE_TO_REASON:
        return RULE_TO_REASON[rule]
    if rule.startswith("label_") or rule in ("none", "meeting_requests_time_filter", ""):
        return None  # a label (Sent, Draft, Spam...) is about that one email, not its sender
    lowered = reason_text.lower()
    matches = (label for words, label in REASON_WORDS if any(w in lowered for w in words))
    return next(matches, IgnoreReason.MISCELLANEOUS)


def load() -> list[IgnoreEntry]:
    """Every entry in the file; an absent file is an empty list."""
    if not PRE_TRIAGE_IGNORE_FILE.exists():
        return []
    raw = json.loads(PRE_TRIAGE_IGNORE_FILE.read_text())
    return [
        IgnoreEntry(IgnoreReason(e["ignore_reason_label"]), sorted(e["senders"]), dict(e.get("added_by", {})))
        for e in raw
    ]


def save(entries: list[IgnoreEntry]) -> list[IgnoreEntry]:
    """Replace the file. Senders are lowercased, deduplicated, and appear under one label only (the last one wins)."""
    by_label: dict[IgnoreReason, list[str]] = {}
    seen: dict[str, IgnoreReason] = {}
    origin: dict[str, str] = {}
    for entry in entries:
        for sender in entry.senders:
            key = sender.strip().lower()
            seen[key] = entry.ignore_reason_label
            origin[key] = entry.added_by.get(sender, entry.added_by.get(key, origin.get(key, "unknown")))
    for sender, label in seen.items():
        if sender:
            by_label.setdefault(label, []).append(sender)
    cleaned = [
        IgnoreEntry(label, sorted(senders), {s: origin[s] for s in sorted(senders)})
        for label, senders in sorted(by_label.items())
    ]
    tmp = PRE_TRIAGE_IGNORE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps([asdict(e) for e in cleaned], indent=2))
    tmp.replace(PRE_TRIAGE_IGNORE_FILE)  # atomic: a concurrent reader sees the old file or the new one, never half
    return cleaned


def label_for(sender_address: str) -> IgnoreReason | None:
    """The reason a sender is on the list, or None."""
    address = sender_address.lower()
    return next((e.ignore_reason_label for e in load() if address in e.senders), None)


_lock = threading.Lock()  # add and remove read, change, and rewrite the file; triage workers may do so at once


def add(sender_address: str, label: IgnoreReason, added_by: str = "user") -> list[IgnoreEntry]:
    """Put a sender on the list under `label`, moving it if it was under another; `added_by` records who decided."""
    address = sender_address.lower()
    with _lock:
        entries = [
            IgnoreEntry(e.ignore_reason_label, [s for s in e.senders if s != address], e.added_by) for e in load()
        ]
        entries.append(IgnoreEntry(label, [address], {address: added_by}))
        return save(entries)


def remove(sender_address: str) -> list[IgnoreEntry]:
    """Take a sender off the list."""
    address = sender_address.lower()
    with _lock:
        kept = [IgnoreEntry(e.ignore_reason_label, [s for s in e.senders if s != address], e.added_by) for e in load()]
        return save(kept)
