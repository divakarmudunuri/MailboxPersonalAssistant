"""Mailbox tools for agents, all over IMAP. READ_TOOLS cannot change anything; WRITE_TOOLS can, and no agent binds them.

Every tool returns text (JSON for structured results). Message and thread ids are the hex ids Gmail shows.
"""

import json
import threading
from datetime import UTC, datetime

from langchain_core.tools import tool

from mail_assistant.gmail_client import GmailImapClient

_local = threading.local()


def _mailbox() -> GmailImapClient:
    """One mailbox client per thread: IMAP connections are not thread-safe."""
    if not hasattr(_local, "mailbox"):
        _local.mailbox = GmailImapClient()
    return _local.mailbox


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1)


# --- reading ------------------------------------------------------------------------------------


@tool
def search_threads(query: str = "in:inbox newer_than:30d", limit: int = 10, unanswered: bool = False) -> str:
    """Search mail with a Gmail query (anything the Gmail search box accepts). Returns one row per thread: the latest
    message's headers, the message count, and whether any message is unread. No bodies. With unanswered=true, threads
    the person has replied in are left out."""
    return _dump(_mailbox().search_threads(query, limit, unanswered))


@tool
def count_threads(query: str, unanswered: bool = False) -> str:
    """How many threads match a Gmail query, without fetching them (exact up to 1000). With unanswered=true, threads
    the person has replied in are left out."""
    return str(_mailbox().count_threads(query, unanswered=unanswered))


@tool
def search_messages(query: str, limit: int = 20) -> str:
    """Search individual messages with a Gmail query, newest first: headers, flags, labels, and ids. No bodies."""
    return _dump(_mailbox().search_messages(query, limit))


@tool
def get_thread(thread_id: str) -> str:
    """Read one thread in full: every message with its body, including earlier messages and the person's own replies.
    Deadlines and action items live in bodies, not snippets."""
    return _dump(_mailbox().get_thread(thread_id))


@tool
def preview_message(message_id: str, chars: int = 300) -> str:
    """The first `chars` bytes of one message's body, without downloading the rest."""
    return _mailbox().preview(message_id, chars)


@tool
def list_parts(message_id: str) -> str:
    """The MIME parts of one message with index, content type, filename, size, and whether each is an attachment."""
    return _dump(_mailbox().list_parts(message_id))


@tool
def get_part(message_id: str, index: int) -> str:
    """One MIME part by index from list_parts: text parts return their text, binary parts their size only."""
    return _dump(_mailbox().get_part(message_id, index))


@tool
def list_folder(folder: str = "INBOX", offset: int = 0, limit: int = 20) -> str:
    """One page of a folder or Gmail label, newest first. Use list_folders for the names."""
    return _dump(_mailbox().list_folder(folder, offset, limit))


@tool
def list_folders() -> str:
    """Every folder: the system folders plus one per Gmail label."""
    return _dump(_mailbox().list_folders())


@tool
def folder_counts(folder: str = "INBOX") -> str:
    """Total and unread message counts of a folder, without fetching any message."""
    return _dump(_mailbox().folder_counts(folder))


@tool
def message_labels(message_id: str) -> str:
    """The Gmail labels on one message."""
    return _dump(_mailbox().labels_of(message_id))


@tool
def list_drafts() -> str:
    """Replies already started. Match thread_id before calling a thread unanswered."""
    return _dump(_mailbox().list_drafts())


@tool
def unread_count() -> str:
    """How many unread messages are in the inbox, without fetching any."""
    return str(_mailbox().unread_count())


@tool
def now() -> str:
    """The current UTC time, for judging what counts as today and what is overdue."""
    return datetime.now(UTC).isoformat(timespec="minutes")


# --- changing state -------------------------------------------------------------------------------


@tool
def mark_read(message_id: str, read: bool = True) -> str:
    """Mark one message read, or unread with read=false."""
    return "ok" if _mailbox().mark_read(message_id, read) else "no such message"


@tool
def star(message_id: str, starred: bool = True) -> str:
    """Star one message, or unstar with starred=false."""
    return "ok" if _mailbox().star(message_id, starred) else "no such message"


@tool
def add_label(message_id: str, label: str) -> str:
    """Apply a Gmail label to one message, creating the label if needed."""
    return "ok" if _mailbox().add_label(message_id, label) else "no such message"


@tool
def remove_label(message_id: str, label: str) -> str:
    """Remove a Gmail label from one message."""
    return "ok" if _mailbox().remove_label(message_id, label) else "no such message"


@tool
def archive(message_id: str) -> str:
    """Remove one message from the inbox. It stays in All Mail."""
    return "ok" if _mailbox().archive(message_id) else "no such message"


@tool
def trash(message_id: str) -> str:
    """Move one message to Trash, where Gmail deletes it after 30 days."""
    return "ok" if _mailbox().trash(message_id) else "no such message"


@tool
def mark_spam(message_id: str) -> str:
    """Move one message to Spam."""
    return "ok" if _mailbox().mark_spam(message_id) else "no such message"


@tool
def delete_permanently(message_id: str) -> str:
    """Irreversibly delete a message that is already in Trash. Refuses messages anywhere else."""
    return "ok" if _mailbox().delete_permanently(message_id) else "not in Trash"


@tool
def save_draft(to: str, subject: str, body: str, thread_id: str = "") -> str:
    """Save a draft in Gmail's Drafts folder. With a thread_id it is threaded as a reply to that thread. Never sends."""
    return f"draft saved, Message-ID {_mailbox().save_draft(to, subject, body, thread_id)}"


READ_TOOLS = [
    search_threads,
    count_threads,
    search_messages,
    get_thread,
    preview_message,
    list_parts,
    get_part,
    list_folder,
    list_folders,
    folder_counts,
    message_labels,
    list_drafts,
    unread_count,
    now,
]
WRITE_TOOLS = [mark_read, star, add_label, remove_label, archive, trash, mark_spam, delete_permanently, save_draft]
