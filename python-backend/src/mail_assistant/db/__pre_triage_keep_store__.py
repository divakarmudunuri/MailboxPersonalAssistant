"""The pre-triage keep list: senders and domains that must always reach the triage model, whatever any ignore rule or
shortcut would have decided. The person's override, edited on the Memory tab."""

import json
import threading

from mail_assistant.config.__app_config__ import PRE_TRIAGE_KEEP_FILE

_lock = threading.Lock()


def load() -> list[str]:
    """Every kept address or domain, sorted; an absent file is an empty list."""
    if not PRE_TRIAGE_KEEP_FILE.exists():
        return []
    return sorted(json.loads(PRE_TRIAGE_KEEP_FILE.read_text()).get("keep", []))


def _save(entries: list[str]) -> list[str]:
    cleaned = sorted({e.strip().lower().lstrip("@") for e in entries if e.strip()})
    tmp = PRE_TRIAGE_KEEP_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"keep": cleaned}, indent=2))
    tmp.replace(PRE_TRIAGE_KEEP_FILE)  # atomic for concurrent readers
    return cleaned


def covers(address: str) -> str | None:
    """The keep-list entry that covers a lowercased address: the address itself, or a domain it belongs to."""
    for entry in load():
        if address == entry or address.endswith("@" + entry) or address.endswith("." + entry):
            return entry
    return None


def add(entry: str) -> list[str]:
    with _lock:
        return _save([*load(), entry])


def remove(entry: str) -> list[str]:
    with _lock:
        return _save([e for e in load() if e != entry.strip().lower().lstrip("@")])
