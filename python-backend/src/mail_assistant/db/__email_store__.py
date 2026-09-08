"""SQLite persistence for triaged emails."""

import json
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from mail_assistant.config.__app_config__ import DB_FILE
from mail_assistant.models.__email_message_model__ import Category, EmailMessage

SCHEMA = """CREATE TABLE IF NOT EXISTS emails (
    id TEXT PRIMARY KEY, thread_id TEXT, subject TEXT, sender TEXT, received_at TEXT,
    snippet TEXT, body_text TEXT, label_ids TEXT, category TEXT, reason TEXT, applied_rule TEXT DEFAULT '',
    action TEXT DEFAULT '')"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(emails)")}
    for column in ("applied_rule", "action"):  # databases created before these columns existed
        if column not in columns:
            conn.execute(f"ALTER TABLE emails ADD COLUMN {column} TEXT DEFAULT ''")
    return conn


def _to_message(row: sqlite3.Row) -> EmailMessage:
    """Decode a database row into a message; inverse of _to_row."""
    d = dict(row)
    d["received_at"] = datetime.fromisoformat(d["received_at"])
    d["label_ids"] = json.loads(d["label_ids"])
    d["category"] = Category(d["category"])
    return EmailMessage(**d)


def _to_row(message: EmailMessage) -> dict:
    """Encode a message as column values; inverse of _to_message."""
    d = asdict(message)
    d["received_at"] = message.received_at.isoformat()
    d["label_ids"] = json.dumps(message.label_ids)
    d["category"] = message.category.value
    return d


def save(message: EmailMessage) -> None:
    """Insert or replace the message."""
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO emails VALUES (:id, :thread_id, :subject, :sender, :received_at, :snippet, "
            ":body_text, :label_ids, :category, :reason, :applied_rule, :action)",
            _to_row(message),
        )


def get(email_id: str) -> EmailMessage | None:
    """Return one email by id, or None if it is not stored."""
    with _connect() as conn:
        row = conn.execute("SELECT * FROM emails WHERE id = ?", (email_id,)).fetchone()
    return _to_message(row) if row else None


def recent(days: int, limit: int = 100) -> list[EmailMessage]:
    """Emails received in the last `days` days, newest first."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM emails WHERE received_at >= ? ORDER BY received_at DESC LIMIT ?",
            ((datetime.now(UTC) - timedelta(days=days)).isoformat(), limit),
        ).fetchall()
    return [_to_message(r) for r in rows]


WAITING = (Category.NOTIFY, Category.AGENT_DRAFT_ONLY, Category.PENDING)  # triage items still waiting on the person


def waiting_on_user(limit: int = 20) -> tuple[list[EmailMessage], int]:
    """Triaged emails still waiting on the person: to read, to review a draft for, or that triage could not decide."""
    with _connect() as conn:
        where = f"WHERE category IN ({','.join('?' * len(WAITING))})"
        params = tuple(c.value for c in WAITING)
        total = conn.execute(f"SELECT COUNT(*) FROM emails {where}", params).fetchone()[0]
        query = f"SELECT * FROM emails {where} ORDER BY received_at DESC LIMIT ?"
        rows = conn.execute(query, (*params, limit)).fetchall()
    return [_to_message(r) for r in rows], total


def with_actions(limit: int = 20) -> tuple[list[EmailMessage], int]:
    """Emails the inbox manager acted on: a reminder, an invitation answer, or a saved draft. Newest first."""
    with _connect() as conn:
        where = "WHERE action != '' AND action NOT LIKE 'no action%' AND action NOT LIKE 'failed%'"
        total = conn.execute(f"SELECT COUNT(*) FROM emails {where}").fetchone()[0]
        rows = conn.execute(f"SELECT * FROM emails {where} ORDER BY received_at DESC LIMIT ?", (limit,)).fetchall()
    return [_to_message(r) for r in rows], total


def list_emails(category: Category | None, page: int, page_size: int, q: str = "") -> tuple[list[EmailMessage], int]:
    """Return one page of emails, newest first, filtered by category and/or a text search, plus the total count."""
    clauses, params = [], []
    if category:
        clauses.append("category = ?")
        params.append(category)
    if q:
        clauses.append("(subject LIKE ? OR sender LIKE ? OR snippet LIKE ? OR body_text LIKE ?)")
        params.extend([f"%{q}%"] * 4)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM emails {where}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM emails {where} ORDER BY received_at DESC LIMIT ? OFFSET ?",
            [*params, page_size, (page - 1) * page_size],
        ).fetchall()
    return [_to_message(r) for r in rows], total
