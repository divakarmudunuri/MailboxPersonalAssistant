"""Gmail over IMAP with OAuth (XOAUTH2): the one mailbox client. IDLE for new mail, Gmail search and thread
extensions for reading, flags and labels and folders for changing state, and APPEND to Drafts for saving a draft.

Ids match what Gmail shows in its web URLs and API: message ids are X-GM-MSGID in hex, thread ids X-GM-THRID in hex.
The watcher's cursor is "<UIDVALIDITY>:<last UID>" of the inbox.
"""

import email
import imaplib
import logging
import smtplib
from datetime import UTC, datetime, timedelta
from email.header import decode_header, make_header
from email.message import EmailMessage as MimeMessage
from email.message import Message
from email.utils import formatdate, make_msgid
from functools import wraps
from typing import Any

from google.auth.transport.requests import Request
from imapclient import IMAPClient
from imapclient.imapclient import ALL, DRAFTS, JUNK, SENT, TRASH

from mail_assistant.config.__app_config__ import GMAIL_ADDRESS, MAIL_BACKFILL_DAYS
from mail_assistant.models.__email_message_model__ import EmailMessage

from .auth import load_credentials

log = logging.getLogger(__name__)

HOST = "imap.gmail.com"
SMTP_HOST = "smtp.gmail.com"
IDLE_RENEW_SECONDS = 25 * 60  # Gmail drops IDLE after about 29 minutes
REPLIED_WINDOW_DAYS = 60  # how far back "the person replied in this thread" looks
SOCKET_TIMEOUT = 120  # seconds; without it a half-open connection blocks a read forever with nothing to catch
INBOX = "INBOX"
_HEADERS = b"BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE MESSAGE-ID)]"
_HEADERS_KEY = b"BODY[HEADER.FIELDS (FROM TO SUBJECT DATE MESSAGE-ID)]"


def _hex(n: int) -> str:
    return format(n, "x")


def _int(hex_id: str) -> str:
    return str(int(hex_id, 16))


def _utc(when: datetime) -> datetime:
    return when.astimezone(UTC) if when.tzinfo else when.replace(tzinfo=UTC)


def _decode(value) -> str:
    """Decode an RFC 2047 header value to text."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _text_body(msg: Message) -> str:
    """The text/plain parts of a parsed message, joined."""
    parts = msg.walk() if msg.is_multipart() else [msg]
    texts = []
    for part in parts:
        if part.get_content_type() == "text/plain" and not part.get("Content-Disposition", "").startswith("attachment"):
            payload = part.get_payload(decode=True) or b""
            texts.append(payload.decode(part.get_content_charset() or "utf-8", "replace"))
    return "\n".join(t for t in texts if t)


def _headers(raw: bytes) -> dict[str, str]:
    msg = email.message_from_bytes(raw)
    return {k.lower(): _decode(msg.get(k)) for k in ("From", "To", "Subject", "Date", "Message-ID")}


def _labels(item: dict) -> list[str]:
    return [lbl.decode() if isinstance(lbl, bytes) else str(lbl) for lbl in item.get(b"X-GM-LABELS", [])]


_DROPPED = (OSError, imaplib.IMAP4.abort, imaplib.IMAP4.error)  # what a connection Gmail closed raises


def reconnecting(method):
    """Run an IMAP operation; if the connection was dropped, reconnect once and run it again."""

    @wraps(method)
    def run(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except _DROPPED:
            log.warning("IMAP connection lost during %s; reconnecting", method.__name__)
            self._connect()
            return method(self, *args, **kwargs)

    return run


class GmailImapClient:
    """Gmail over IMAP. Folder selection reconnects and re-authenticates once if the server dropped the connection."""

    def __init__(self) -> None:
        if not GMAIL_ADDRESS:
            raise ValueError("GMAIL_ADDRESS is not set; add the mailbox address to .env (see .env.example)")
        self.address = GMAIL_ADDRESS
        self._creds = load_credentials()
        self._imap: IMAPClient | None = None
        self._folder: str | None = None
        self._specials: dict[bytes, str] = {}
        self._connect()

    def _connect(self) -> None:
        if self._creds.expired or not self._creds.token:
            self._creds.refresh(Request())
        self._imap = IMAPClient(HOST, ssl=True, timeout=SOCKET_TIMEOUT)
        self._imap.oauth2_login(self.address, self._creds.token)
        self._folder = None
        self._specials = {}
        log.info("IMAP connected as %s", self.address)

    def _select(self, folder: str, readonly: bool = True) -> dict:
        """Select a folder, re-selecting when switching between read-only and writable."""
        key = f"{folder}:{'ro' if readonly else 'rw'}"
        if self._folder != key:
            info = self._imap.select_folder(folder, readonly=readonly)
            self._folder = key
            return info
        return {}

    def _special(self, flag: bytes) -> str:
        """The folder carrying a special-use flag, looked up once per connection."""
        if flag not in self._specials:
            self._specials[flag] = self._imap.find_special_folder(flag)
        return self._specials[flag]

    def _uids_for_message(self, message_id: str, folder: str, readonly: bool = True) -> list[int]:
        self._select(folder, readonly)
        return self._imap.search(["X-GM-MSGID", _int(message_id)])

    def _uids_for_thread(self, thread_id: str, folder: str, readonly: bool = True) -> list[int]:
        self._select(folder, readonly)
        return self._imap.search(["X-GM-THRID", _int(thread_id)])

    # --- watching ---------------------------------------------------------------------------------

    def _new_uids(self, cursor: str | None) -> tuple[list[int], str]:
        """Inbox UIDs after the cursor, and the cursor to save.

        A missing or foreign cursor starts MAIL_BACKFILL_DAYS ago, so a fresh install triages recent mail first.
        """
        info = self._imap.select_folder(INBOX, readonly=True)
        self._folder = f"{INBOX}:ro"
        validity, next_uid = int(info[b"UIDVALIDITY"]), int(info[b"UIDNEXT"])
        try:
            seen_validity, last_uid = (int(x) for x in (cursor or "").split(":"))
        except ValueError:
            seen_validity, last_uid = -1, 0
        if seen_validity != validity:
            last_uid = next_uid - 1
            if MAIL_BACKFILL_DAYS:
                since = (datetime.now(UTC) - timedelta(days=MAIL_BACKFILL_DAYS)).date()
                recent = self._imap.search(["SINCE", since])
                last_uid = min(recent) - 1 if recent else last_uid
            log.info("IMAP cursor %r unusable for UIDVALIDITY %s; starting after UID %d", cursor, validity, last_uid)
        uids = self._imap.search(["UID", f"{last_uid + 1}:*"]) if next_uid > last_uid + 1 else []
        uids = sorted(u for u in uids if u > last_uid)
        return uids, f"{validity}:{max([last_uid, *uids])}"

    @reconnecting
    def wait_for_new_mail(self, cursor: str | None) -> tuple[list[str], str]:
        """Block on IDLE until mail arrives after the cursor; return the new inbox UIDs and the cursor to save."""
        uids, cursor = self._new_uids(cursor)
        while not uids:
            self._imap.idle()
            try:
                # idle_check polls the socket itself, so the socket timeout does not cut the wait short
                self._imap.idle_check(timeout=IDLE_RENEW_SECONDS)
            finally:
                self._imap.idle_done()
            uids, cursor = self._new_uids(cursor)
        return [str(u) for u in uids], cursor

    @reconnecting
    def get_message(self, uid: str) -> EmailMessage | None:
        """Fetch one inbox message by UID as the model the triage graph uses; None if it is gone."""
        self._select(INBOX)
        fields = [b"X-GM-MSGID", b"X-GM-THRID", b"X-GM-LABELS", b"FLAGS", b"INTERNALDATE", b"RFC822"]
        item = self._imap.fetch([int(uid)], fields).get(int(uid))
        if not item:
            return None
        msg = email.message_from_bytes(item[b"RFC822"])
        body = _text_body(msg)
        labels = _labels(item)
        if b"\\Seen" not in item.get(b"FLAGS", ()):
            labels.append("UNREAD")
        return EmailMessage(
            id=_hex(item[b"X-GM-MSGID"]),
            thread_id=_hex(item[b"X-GM-THRID"]),
            subject=_decode(msg.get("Subject")),
            sender=_decode(msg.get("From")),
            received_at=_utc(item[b"INTERNALDATE"]),
            snippet=" ".join(body.split())[:200],
            body_text=body,
            label_ids=[INBOX, *labels],
        )

    @reconnecting
    def has_been_replied_to(self, message: EmailMessage) -> bool:
        """True if a message in the Sent folder shares the thread and is newer than this one."""
        uids = self._uids_for_thread(message.thread_id, self._special(SENT))
        if not uids:
            return False
        dates = self._imap.fetch(uids, [b"INTERNALDATE"])
        return any(_utc(d[b"INTERNALDATE"]) > message.received_at for d in dates.values())

    # --- reading ----------------------------------------------------------------------------------

    def profile_email(self) -> str:
        return self.address

    @reconnecting
    def matches(self, message_id: str, query: str) -> bool:
        """Whether one message matches a Gmail search query, such as `category:promotions` or `is:muted`."""
        self._select(self._special(ALL))
        return bool(self._imap.search(["X-GM-MSGID", _int(message_id), "X-GM-RAW", query]))

    @reconnecting
    def list_folders(self) -> list[str]:
        """Every folder, which for Gmail means every label plus the system folders."""
        return [name for _flags, _delim, name in self._imap.list_folders()]

    @reconnecting
    def folder_counts(self, folder: str = INBOX) -> dict[str, int]:
        """Total and unread message counts without fetching anything."""
        status = self._imap.folder_status(folder, [b"MESSAGES", b"UNSEEN"])
        return {"messages": int(status[b"MESSAGES"]), "unread": int(status[b"UNSEEN"])}

    def unread_count(self) -> int:
        return self.folder_counts(INBOX)["unread"]

    def _summaries(self, uids: list[int]) -> list[dict[str, Any]]:
        """Headers, flags, labels, and ids for UIDs in the selected folder, newest first."""
        if not uids:
            return []
        fields = [_HEADERS, b"FLAGS", b"INTERNALDATE", b"X-GM-MSGID", b"X-GM-THRID", b"X-GM-LABELS"]
        data = self._imap.fetch(uids, fields)
        rows = []
        for uid in sorted(data, reverse=True):
            item = data[uid]
            headers = _headers(item[_HEADERS_KEY])
            rows.append(
                {
                    "message_id": _hex(item[b"X-GM-MSGID"]),
                    "thread_id": _hex(item[b"X-GM-THRID"]),
                    "from": headers["from"],
                    "to": headers["to"],
                    "subject": headers["subject"],
                    "date": _utc(item[b"INTERNALDATE"]).isoformat(timespec="minutes"),
                    "unread": b"\\Seen" not in item[b"FLAGS"],
                    "starred": b"\\Flagged" in item[b"FLAGS"],
                    "labels": _labels(item),
                }
            )
        return rows

    @reconnecting
    def list_folder(self, folder: str = INBOX, offset: int = 0, limit: int = 20) -> list[dict[str, Any]]:
        """One page of a folder, newest first, by UID range."""
        self._select(folder)
        uids = sorted(self._imap.search("ALL"), reverse=True)[offset : offset + limit]
        return self._summaries(uids)

    @reconnecting
    def search_messages(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Messages matching a Gmail search query over All Mail, newest first."""
        self._select(self._special(ALL))
        uids = sorted(self._imap.gmail_search(query), reverse=True)[:limit]
        return self._summaries(uids)

    def _thread_ids(self, query: str, cap: int) -> list[int]:
        """Distinct thread ids of the newest messages matching a Gmail query, newest first, from All Mail."""
        self._select(self._special(ALL))
        uids = sorted(self._imap.gmail_search(query), reverse=True)[: cap * 4]
        if not uids:
            return []
        items = self._imap.fetch(uids, [b"X-GM-THRID"])
        return list(dict.fromkeys(items[uid][b"X-GM-THRID"] for uid in uids if uid in items))

    def _replied_threads(self) -> set[int]:
        """Threads the person has sent a message in recently."""
        self._select(self._special(ALL))
        uids = self._imap.gmail_search(f"in:sent newer_than:{REPLIED_WINDOW_DAYS}d")
        return {item[b"X-GM-THRID"] for item in self._imap.fetch(uids, [b"X-GM-THRID"]).values()} if uids else set()

    @reconnecting
    def sent_threads(self, days: int = REPLIED_WINDOW_DAYS) -> dict[str, datetime]:
        """Threads the person sent a message in over the last `days` days: hex thread id -> latest send time (UTC)."""
        self._select(self._special(ALL))
        uids = self._imap.gmail_search(f"in:sent newer_than:{days}d")
        latest: dict[str, datetime] = {}
        for item in (self._imap.fetch(uids, [b"X-GM-THRID", b"INTERNALDATE"]) if uids else {}).values():
            thrid, when = _hex(item[b"X-GM-THRID"]), _utc(item[b"INTERNALDATE"])
            latest[thrid] = max(latest.get(thrid, when), when)
        return latest

    @reconnecting
    def count_threads(self, query: str, cap: int = 1000, unanswered: bool = False) -> int:
        """How many distinct threads match a Gmail query, exact up to `cap`; `unanswered` drops threads the person
        has replied in."""
        thrids = self._thread_ids(query, cap)
        if unanswered:
            replied = self._replied_threads()
            thrids = [t for t in thrids if t not in replied]
        return min(len(thrids), cap)

    @reconnecting
    def search_threads(self, query: str, limit: int = 10, unanswered: bool = False) -> list[dict[str, Any]]:
        """Threads matching a Gmail search query: the latest message of each, with message count and unread flag;
        `unanswered` drops threads the person has replied in."""
        thrids = self._thread_ids(query, limit * 4)
        if unanswered:
            replied = self._replied_threads()
            thrids = [t for t in thrids if t not in replied]
        found = []
        for thrid in thrids[:limit]:
            all_uids = self._imap.search(["X-GM-THRID", str(thrid)])
            latest = self._summaries([max(all_uids)])[0]
            data = self._imap.fetch(all_uids, [b"FLAGS"])
            latest.update(
                thread_id=_hex(thrid),
                messages=len(all_uids),
                unread=any(b"\\Seen" not in d[b"FLAGS"] for d in data.values()),
                last_from_me=self.address.lower() in latest["from"].lower(),
            )
            found.append(latest)
        return found

    @reconnecting
    def get_thread(self, thread_id: str, body_chars: int = 2500) -> dict[str, Any]:
        """Every message in one thread with bodies, oldest first, including the person's own replies."""
        uids = self._uids_for_thread(thread_id, self._special(ALL))
        data = self._imap.fetch(uids, [b"RFC822", b"X-GM-MSGID"]) if uids else {}
        messages, subject = [], ""
        for uid in sorted(data):
            msg = email.message_from_bytes(data[uid][b"RFC822"])
            body = _text_body(msg)
            subject = subject or _decode(msg.get("Subject"))
            sender = _decode(msg.get("From"))
            messages.append(
                {
                    "message_id": _hex(data[uid][b"X-GM-MSGID"]),
                    "from": sender,
                    "date": _decode(msg.get("Date")),
                    "from_me": self.address.lower() in sender.lower(),
                    "body": body[:body_chars],
                    "truncated": len(body) > body_chars,
                }
            )
        return {"thread_id": thread_id, "subject": subject, "messages": messages}

    @reconnecting
    def preview(self, message_id: str, chars: int = 300) -> str:
        """The first `chars` bytes of a message's body, fetched as a partial, without downloading the rest."""
        uids = self._uids_for_message(message_id, self._special(ALL))
        if not uids:
            return ""
        item = self._imap.fetch([uids[0]], [f"BODY.PEEK[TEXT]<0.{chars}>".encode()])[uids[0]]
        raw = next((v for k, v in item.items() if k.startswith(b"BODY[TEXT]")), b"")
        return raw.decode("utf-8", "replace")

    @reconnecting
    def list_parts(self, message_id: str) -> list[dict[str, Any]]:
        """The MIME parts of a message: index, content type, filename, and size, so one part can be fetched alone."""
        uids = self._uids_for_message(message_id, self._special(ALL))
        if not uids:
            return []
        msg = email.message_from_bytes(self._imap.fetch([uids[0]], [b"RFC822"])[uids[0]][b"RFC822"])
        parts = []
        for index, part in enumerate(msg.walk()):
            if part.is_multipart():
                continue
            payload = part.get_payload(decode=True) or b""
            parts.append(
                {
                    "index": index,
                    "content_type": part.get_content_type(),
                    "filename": part.get_filename() or "",
                    "size": len(payload),
                    "attachment": part.get("Content-Disposition", "").startswith("attachment"),
                }
            )
        return parts

    @reconnecting
    def get_part(self, message_id: str, index: int, chars: int = 8000) -> dict[str, Any]:
        """One MIME part: text parts return their text (cut to `chars`), binary parts return their size only."""
        uids = self._uids_for_message(message_id, self._special(ALL))
        if not uids:
            return {}
        msg = email.message_from_bytes(self._imap.fetch([uids[0]], [b"RFC822"])[uids[0]][b"RFC822"])
        for i, part in enumerate(msg.walk()):
            if i != index:
                continue
            payload = part.get_payload(decode=True) or b""
            is_text = part.get_content_maintype() == "text"
            text = payload.decode(part.get_content_charset() or "utf-8", "replace") if is_text else ""
            return {
                "index": index,
                "content_type": part.get_content_type(),
                "filename": part.get_filename() or "",
                "size": len(payload),
                "text": text[:chars],
            }
        return {}

    @reconnecting
    def labels_of(self, message_id: str) -> list[str]:
        """Gmail labels on one message."""
        uids = self._uids_for_message(message_id, self._special(ALL))
        return _labels(self._imap.fetch([uids[0]], [b"X-GM-LABELS"])[uids[0]]) if uids else []

    def list_drafts(self, limit: int = 50) -> list[dict[str, Any]]:
        """Drafts in progress, newest first, with the thread each one answers."""
        return self.list_folder(self._special(DRAFTS), 0, limit)

    # --- changing state ---------------------------------------------------------------------------

    @reconnecting
    def _store_flags(self, message_id: str, flags: list[bytes], add: bool) -> bool:
        uids = self._uids_for_message(message_id, self._special(ALL), readonly=False)
        if not uids:
            return False
        (self._imap.add_flags if add else self._imap.remove_flags)(uids, flags)
        return True

    def mark_read(self, message_id: str, read: bool = True) -> bool:
        return self._store_flags(message_id, [b"\\Seen"], read)

    def star(self, message_id: str, starred: bool = True) -> bool:
        return self._store_flags(message_id, [b"\\Flagged"], starred)

    @reconnecting
    def add_label(self, message_id: str, label: str) -> bool:
        """Apply a Gmail label; it is created if it does not exist."""
        uids = self._uids_for_message(message_id, self._special(ALL), readonly=False)
        if not uids:
            return False
        if label not in self.list_folders():
            self._imap.create_folder(label)
        self._imap.add_gmail_labels(uids, [label])
        return True

    @reconnecting
    def remove_label(self, message_id: str, label: str) -> bool:
        uids = self._uids_for_message(message_id, self._special(ALL), readonly=False)
        if not uids:
            return False
        self._imap.remove_gmail_labels(uids, [label])
        return True

    def archive(self, message_id: str) -> bool:
        """Remove from the inbox; the message stays in All Mail."""
        return self.remove_label(message_id, "\\Inbox")

    @reconnecting
    def _move(self, message_id: str, folder: str) -> bool:
        uids = self._uids_for_message(message_id, self._special(ALL), readonly=False)
        if not uids:
            return False
        self._imap.move(uids, folder)
        return True

    def trash(self, message_id: str) -> bool:
        return self._move(message_id, self._special(TRASH))

    def mark_spam(self, message_id: str) -> bool:
        return self._move(message_id, self._special(JUNK))

    @reconnecting
    def delete_permanently(self, message_id: str) -> bool:
        """Expunge a message that is already in Trash. Irreversible; refuses anything not in Trash."""
        uids = self._uids_for_message(message_id, self._special(TRASH), readonly=False)
        if not uids:
            return False
        self._imap.delete_messages(uids)
        self._imap.expunge(uids)
        return True

    @reconnecting
    def save_draft(self, to: str, subject: str, body: str, thread_id: str = "") -> str:
        """Append a draft to the Drafts folder; given a thread id, it replies to that thread's last message."""
        draft = MimeMessage()
        draft["From"], draft["To"], draft["Subject"] = self.address, to, subject
        draft["Date"], draft["Message-ID"] = formatdate(localtime=True), make_msgid()
        if thread_id:
            uids = self._uids_for_thread(thread_id, self._special(ALL))
            if uids:
                last = self._imap.fetch([max(uids)], [_HEADERS])[max(uids)]
                parent = _headers(last[_HEADERS_KEY])["message-id"]
                if parent:
                    draft["In-Reply-To"], draft["References"] = parent, parent
        draft.set_content(body)
        self._imap.append(self._special(DRAFTS), draft.as_bytes(), flags=[b"\\Draft"])
        return draft["Message-ID"]

    @reconnecting
    def draft_on_thread(self, thread_id: str) -> dict[str, str] | None:
        """The newest draft in Gmail's Drafts on this thread: to, subject, body, draft_message_id; None if none."""
        uids = self._uids_for_thread(thread_id, self._special(DRAFTS))
        if not uids:
            return None
        msg = email.message_from_bytes(self._imap.fetch([max(uids)], [b"RFC822"])[max(uids)][b"RFC822"])
        return {
            "to": _decode(msg.get("To")),
            "subject": _decode(msg.get("Subject")),
            "body": _text_body(msg),
            "draft_message_id": _decode(msg.get("Message-ID")),
        }

    @reconnecting
    def discard_draft(self, draft_message_id: str) -> bool:
        """Delete a draft saved by `save_draft`, by its Message-ID."""
        self._select(self._special(DRAFTS), readonly=False)
        uids = self._imap.search(["HEADER", "Message-ID", draft_message_id])
        if not uids:
            return False
        self._imap.delete_messages(uids)
        self._imap.expunge()
        return True

    @reconnecting
    def send_reply(self, message_id: str, to: str, subject: str, body: str) -> str:
        """Send a reply to the message over SMTP with the same OAuth token; Gmail files it in Sent. Its Message-ID."""
        reply = MimeMessage()
        reply["From"], reply["To"], reply["Subject"] = self.address, to, subject
        reply["Date"], reply["Message-ID"] = formatdate(localtime=True), make_msgid()
        uids = self._uids_for_message(message_id, self._special(ALL))
        if uids:
            parent = _headers(self._imap.fetch(uids, [_HEADERS])[uids[0]][_HEADERS_KEY])["message-id"]
            if parent:
                reply["In-Reply-To"], reply["References"] = parent, parent
        reply.set_content(body)
        if self._creds.expired or not self._creds.token:
            self._creds.refresh(Request())
        with smtplib.SMTP_SSL(SMTP_HOST, 465, timeout=SOCKET_TIMEOUT) as smtp:
            smtp.ehlo()
            xoauth2 = f"user={self.address}\x01auth=Bearer {self._creds.token}\x01\x01"
            smtp.auth("XOAUTH2", lambda challenge=None: xoauth2)
            smtp.send_message(reply)
        log.info("Sent reply to %s: %s", to, subject)
        return reply["Message-ID"]
