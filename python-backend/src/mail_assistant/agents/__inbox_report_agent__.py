"""The inbox report agent: the Quick Overview. Code gathers, the model writes once.

START -> gather -> (unchanged since the last build? END : write) -> END

`gather` reads the stored mail from SQLite and makes three external calls: the inbox unread count and the Sent folder
over IMAP, and the next two weeks of the calendar. It builds one snapshot with exact counts, the candidate threads with
their bodies under a fixed budget, and the ids reported last time. `write` is a single structured model call; the
markdown is rendered here from the returned object, so nothing has to be repaired afterwards. Every item names an email
id from the snapshot, and the UI links it to the Inbox tab.
"""

import json
import logging
import time
from datetime import UTC, datetime, timedelta
from functools import cache
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from mail_assistant.agents.llm.__structured_llm__ import ask
from mail_assistant.agents.skills import __skills__ as skills
from mail_assistant.agents.tools import __calendar_tools__ as calendar_tools
from mail_assistant.agents.tools import __gmail_tools__ as gmail_tools
from mail_assistant.config.__app_config__ import REPORT_FILE, REPORT_LLM
from mail_assistant.db import __email_store__ as email_store
from mail_assistant.db import __memory_store__ as memory_store
from mail_assistant.db import __trace_store__ as trace_store
from mail_assistant.models.__email_message_model__ import Category, EmailMessage

log = logging.getLogger(__name__)

SKILL = skills.load("inbox-report")
MAIL_WINDOW_DAYS = 30
STALE_DAYS = 5  # a thread is "waiting on them" when the person's message has had no answer this long
CALENDAR_DAYS = 14
BODY_CHARS = 1200  # per candidate thread
BODY_BUDGET_CHARS = 40_000  # all bodies together, so the prompt fits a local model's context
LIST_LIMIT = 20
REVIEW_ROWS = 5  # rows shown per section on the Home tab
REVIEW_LABELS = ("UNREAD", "\\Important", "\\Starred")
DO_NOT_REPLY = ("noreply", "no-reply", "donotreply", "do-not-reply", "do_not_reply")
MONEY_WORDS = (
    "invoice", "bill", "payment", "past due", "balance", "renewal", "renew", "receipt", "statement", "security alert",
    "sign-in", "sign in", "password", "verify", "suspicious", "charge",
)  # fmt: skip
SKIPPED_CATEGORIES = (Category.IGNORE, Category.USER_REPLY_COMPLETE)

SYSTEM_PROMPT = """You are the inbox reporting agent for {name}, writing the Quick Overview.

{skill}

# Long-term memory

{memory}"""


class Item(BaseModel):
    """One line of the overview about one email."""

    email_id: str  # an id from the snapshot, or "" when the line is not about one email
    line: str


class CalendarNote(BaseModel):
    title: str
    when: str
    prep: str


class Deadline(BaseModel):
    date: str
    email_id: str
    line: str
    on_calendar: bool


class Overview(BaseModel):
    """What the model returns; the counts are not here because the app measured them."""

    calendar: list[CalendarNote]
    waiting_on_you: list[Item]
    waiting_on_them: list[Item]
    deadlines: list[Deadline]
    money: list[Item]
    first_thing: str
    suppressed: str = ""


class ReportState(TypedDict):
    force: bool
    snapshot: dict
    overview: Overview | None


# --- gather -----------------------------------------------------------------------------------


def _human(sender: str) -> bool:
    return not any(word in sender.lower() for word in DO_NOT_REPLY)


def _newest_per_thread(messages: list[EmailMessage]) -> list[EmailMessage]:
    """Keep the newest message of each thread, in the order given (newest first)."""
    seen: set[str] = set()
    return [m for m in messages if not (m.thread_id in seen or seen.add(m.thread_id))]


def _snapshot() -> dict:
    """Everything the overview is written from: SQLite plus three external calls."""
    mailbox, calendar = gmail_tools._mailbox(), calendar_tools._calendar()
    now = datetime.now(UTC)
    rows = email_store.recent(MAIL_WINDOW_DAYS, limit=5000)
    sent = mailbox.sent_threads()  # thread id -> the person's latest send time
    unread = mailbox.unread_count()
    events = calendar.find_events(days=CALENDAR_DAYS)

    def replied(m: EmailMessage) -> bool:
        return m.thread_id in sent and sent[m.thread_id] >= m.received_at

    live = _newest_per_thread([m for m in rows if m.category not in SKIPPED_CATEGORIES and not replied(m)])
    needs_review = [m for m in live if any(lbl in m.label_ids for lbl in REVIEW_LABELS) and _human(m.sender)]
    money = [m for m in live if any(w in f"{m.subject} {m.sender}".lower() for w in MONEY_WORDS)]
    latest_received: dict[str, datetime] = {}
    for m in rows:
        latest_received[m.thread_id] = max(latest_received.get(m.thread_id, m.received_at), m.received_at)
    by_thread = {m.thread_id: m for m in _newest_per_thread(rows)}
    stale = [
        by_thread[t]
        for t, when in sorted(sent.items(), key=lambda kv: kv[1])
        if t in by_thread and when > latest_received[t] and now - when > timedelta(days=STALE_DAYS)
    ]
    tomorrow_end = (now + timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)
    today = [e for e in events if e["start"][:19] < tomorrow_end.isoformat()[:19]]
    invites = [e for e in events if e["my_response"] == "needsAction"]
    event_threads = [m for e in today if e["summary"] for m in live[:200] if e["summary"].lower() in m.subject.lower()]
    drafted = {m.thread_id for m in rows if m.action.startswith("save_draft")}

    acted = [m for m in live if m.category in (Category.AUTO_SCHEDULE, Category.AUTO_DRAFT)]
    candidates, used = [], 0
    for m in _newest_per_thread([*event_threads, *acted, *needs_review[:10], *money[:5], *stale[:5]]):
        body = " ".join((m.body_text or m.snippet).split())[:BODY_CHARS]
        if used + len(body) > BODY_BUDGET_CHARS:
            break
        candidates.append((m, body))
        used += len(body)

    cached = load_cached() or {}
    newest = max((m.received_at for m in rows), default=now).isoformat(timespec="seconds")
    return {
        "now": now.isoformat(timespec="minutes"),
        "unread": unread,
        "needs_review": needs_review[:LIST_LIMIT],
        "needs_review_count": len(needs_review),
        "stale": stale[:LIST_LIMIT],
        "today": today,
        "invites": invites,
        "money": money[:LIST_LIMIT],
        "candidates": candidates,
        "drafted": drafted,
        "previous_ids": set(cached.get("item_ids", [])),
        "fingerprint": f"{newest}|{len(sent)}|{unread}|{len(events)}|{len(invites)}",
    }


def _name(sender: str) -> str:
    """ "Sam Lee <sam@x.com>" -> "Sam Lee"; a bare address stays as it is."""
    name, _, rest = sender.partition("<")
    return name.strip().strip('"') or rest.rstrip(">").strip()


def _when(now: str, e: dict) -> str:
    """An event's time as a person would say it: "Today 7:00 PM to 8:00 PM", "Tomorrow all day", "Fri Sep 12
    9:30 AM"."""
    start = datetime.fromisoformat(e["start"])
    all_day = "T" not in e["start"]
    local_now = datetime.fromisoformat(now).astimezone(start.tzinfo) if start.tzinfo else datetime.fromisoformat(now)
    delta = (start.date() - local_now.date()).days
    day = "Today" if delta == 0 else "Tomorrow" if delta == 1 else start.strftime("%a %b %-d")
    if all_day:
        return f"{day} all day"
    end = datetime.fromisoformat(e["end"]) if e.get("end") and "T" in e["end"] else None
    clock = lambda d: d.strftime("%-I:%M %p")  # noqa: E731
    return f"{day} {clock(start)}" + (f" to {clock(end)}" if end else "")


def _age(now: str, m: EmailMessage) -> str:
    days = (datetime.fromisoformat(now) - m.received_at).days
    return "today" if days < 1 else f"{days} d ago"


def _snapshot_text(snap: dict) -> str:
    """The snapshot as the model sees it."""
    now = snap["now"]

    def row(m: EmailMessage, extra: str = "") -> str:
        subject = " ".join(m.subject.split())  # folded header lines become one line
        return f"- [{m.id}] {_age(now, m)} | {' '.join(m.sender.split())} | {subject}{extra}"

    def review_row(m: EmailMessage) -> str:
        draft = " | draft started" if m.thread_id in snap["drafted"] else ""
        return row(m, f" | triage: {m.category} ({m.applied_rule or 'no rule'}){draft}")

    def event_row(e: dict) -> str:
        you = e["my_response"] or "n/a"
        return f"- {e['start']} to {e['end']} | {e['summary']} | organizer {e['organizer']} | you: {you}"

    lines = [
        f"Now: {now} (UTC)",
        f"Unread in inbox: {snap['unread']}",
        f"Needs review (last {MAIL_WINDOW_DAYS} days, unread or important or starred, unanswered, human senders): "
        f"{snap['needs_review_count']} threads",
        "",
        "## Calendar, today and tomorrow",
        *([event_row(e) for e in snap["today"]] or ["(nothing scheduled)"]),
        "",
        "## Invitations awaiting your answer",
        *([event_row(e) for e in snap["invites"]] or ["(none)"]),
        "",
        f"## Needs review, newest {len(snap['needs_review'])}",
        *([review_row(m) for m in snap["needs_review"]] or ["(none)"]),
        "",
        f"## Waiting on them: your message was the last one, quiet for {STALE_DAYS}+ days",
        *([row(m) for m in snap["stale"]] or ["(none)"]),
        "",
        "## Money and accounts",
        *([row(m) for m in snap["money"]] or ["(none)"]),
        "",
        "## Reported last time (ids)",
        ", ".join(sorted(snap["previous_ids"])) or "(first overview)",
        "",
        "## Thread bodies (latest message of each, trimmed)",
    ]
    for m, body in snap["candidates"]:
        truncated = " (truncated)" if len(m.body_text or "") > BODY_CHARS else ""
        when = m.received_at.isoformat(timespec="minutes")
        lines += [f"### [{m.id}] {m.sender} | {m.subject} | {when}{truncated}", body, ""]
    return "\n".join(lines)


def gather(state: ReportState) -> dict:
    """Build the snapshot: stored mail plus the unread count, the Sent folder, and the calendar. No model call."""
    snap = _snapshot()
    log.info(
        "Overview gather: unread %d, needs review %d, today %d, invites %d, candidates %d",
        snap["unread"], snap["needs_review_count"], len(snap["today"]), len(snap["invites"]), len(snap["candidates"]),
    )  # fmt: skip
    return {"snapshot": snap}


def unchanged(state: ReportState) -> Literal["write", "__end__"]:
    """Skip the model when nothing moved since the last build, unless a rebuild was asked for."""
    cached = load_cached()
    if not state["force"] and cached and cached.get("fingerprint") == state["snapshot"]["fingerprint"]:
        log.info("Overview unchanged since %s; not rebuilt", cached["generated_at"])
        return END
    return "write"


def write(state: ReportState) -> dict:
    """One structured model call; a failure is retried once."""
    memory = memory_store.preferences_text()
    system = SYSTEM_PROMPT.format(name=gmail_tools._mailbox().profile_email(), skill=SKILL.body, memory=memory)
    text = _snapshot_text(state["snapshot"])
    for attempt in (1, 2):
        try:
            overview = ask(Overview, system, text, run_name="inbox_report_write", llm=REPORT_LLM)
            break
        except Exception:
            if attempt == 2:
                raise
            log.exception("Overview model call failed; retrying once")
    return {"overview": overview}


_graph = StateGraph(ReportState)
_graph.add_node("gather", gather)
_graph.add_node("write", write)
_graph.add_edge(START, "gather")
_graph.add_conditional_edges("gather", unchanged, ["write", END])
_graph.add_edge("write", END)


@cache
def inbox_report_agent():
    """Compiled once, with no checkpointer: an overview is one short run that never suspends."""
    return _graph.compile()


# --- render -------------------------------------------------------------------------------------


def _render(snap: dict, ov: Overview) -> tuple[str, list[str]]:
    """The overview as markdown, plus the email ids it names. An id that is not in the snapshot, does not match its
    line, or was already linked is dropped, not linked."""
    known = {m.id: m for m, _ in snap["candidates"]}
    known |= {m.id: m for key in ("needs_review", "stale", "money") for m in snap[key]}
    ids: list[str] = []

    def matches(m: EmailMessage, line: str) -> bool:
        """A small model sometimes pastes the wrong id: only link when the line names the sender or subject."""
        words = {w for w in f"{m.sender} {m.subject}".lower().replace("<", " ").replace(">", " ").split() if len(w) > 3}
        return any(w in line.lower() for w in words)

    def items(entries: list) -> list[str]:
        """One section's rows; an id repeated within the section is linked only the first time."""
        rows, seen = [], set()
        for email_id, line in entries:
            line = line.strip()
            if "organizer " in line or "needsAction" in line:
                continue  # a pasted calendar row; the app lists invitations itself
            if " | " in line:  # a pasted snapshot row: say it as sender and subject, or not at all
                if email_id not in known:
                    continue
                m = known[email_id]
                line = f"{_name(m.sender)}: {' '.join(m.subject.split())}"
            if email_id in known and email_id not in seen and matches(known[email_id], line):
                seen.add(email_id)
                ids.append(email_id)
                new = "New: " if email_id not in snap["previous_ids"] else ""
                rows.append(f"- {new}{line} [open](#inbox/{email_id})")
            else:
                rows.append(f"- {line}")
        return rows

    def section(title: str, rows: list[str], keep_when_empty: bool = False) -> list[str]:
        if not rows and not keep_when_empty:
            return []
        return [f"**{title}:** " + ("" if rows else "none"), *rows[:REVIEW_ROWS], ""]

    def invite_row(e: dict) -> str:
        link = f" [open in calendar]({e['link']})" if e.get("link", "").startswith("https://") else ""
        when = _when(snap["now"], e)
        return f"- **{e['summary']}**, {when}, invitation from {e['organizer']} awaiting your answer{link}"

    def calendar_row(e: dict) -> str:
        """Time and title from the calendar itself; the model's prep note only when it says something."""
        note = next((n.prep.strip() for n in ov.calendar if n.title.strip().lower() in e["summary"].lower()), "")
        empty = note.lower().rstrip(".") in ("", "none", "no prep", "no prep specified")
        prep = "" if empty else f": {note.rstrip('.')}."
        return f"- {_when(snap['now'], e)}: **{e['summary']}**{prep}"

    def review_row(m: EmailMessage) -> str:
        ids.append(m.id)
        subject = " ".join(m.subject.split()) or "(no subject)"
        return f"- {_name(m.sender)}: {subject}, {_age(snap['now'], m)} [open](#inbox/{m.id})"

    calendar = [calendar_row(e) for e in snap["today"]]
    review = [review_row(m) for m in snap["needs_review"][:REVIEW_ROWS]]
    if snap["needs_review_count"] > REVIEW_ROWS:
        review.append(f"- and {snap['needs_review_count'] - REVIEW_ROWS} more in the Inbox tab")
    waiting = items([(i.email_id, i.line) for i in ov.waiting_on_you]) + [invite_row(e) for e in snap["invites"]]
    flag = lambda d: "" if d.on_calendar else " (not on your calendar)"  # noqa: E731
    deadlines = items([(d.email_id, f"{d.date}: {d.line}{flag(d)}") for d in ov.deadlines])
    lines = [
        f"**Unread email:** {snap['unread']}",
        "",
        f"**Needs review:** {snap['needs_review_count']}",
        *review,
        "",
        *section("Today's calendar", calendar, keep_when_empty=True),
        *section(f"Waiting on you ({len(waiting)})", waiting),
        *section("Waiting on them", items([(i.email_id, i.line) for i in ov.waiting_on_them])),
        *section("Deadlines named in email", deadlines),
        *section("Money and accounts", items([(i.email_id, i.line) for i in ov.money])),
        f"**First thing:** {ov.first_thing.strip() or 'nothing needs you today.'}",
    ]
    if ov.suppressed.strip():
        lines += ["", f"Left out by your rules: {ov.suppressed.strip()}"]
    return "\n".join(lines), list(dict.fromkeys(ids))


def generate(force: bool = False) -> dict:
    """Build the overview and cache it in REPORT_FILE; return the cached one when nothing changed and not `force`."""
    started = time.monotonic()
    state = {"force": force, "snapshot": {}, "overview": None}
    final = inbox_report_agent().invoke(state, config={"run_name": "inbox_report"})
    snap, elapsed = final["snapshot"], int((time.monotonic() - started) * 1000)
    if final["overview"] is None:
        trace_store.record_run("inbox_report", "Quick Overview", "unchanged", "nothing new since last build", elapsed)
        return load_cached()
    briefing, item_ids = _render(snap, final["overview"])
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "counts": {
            "unread": snap["unread"],
            "needs_review": snap["needs_review_count"],
            "events_today": len(snap["today"]),
            "pending_invites": len(snap["invites"]),
            "candidates": len(snap["candidates"]),
        },
        "fingerprint": snap["fingerprint"],
        "item_ids": item_ids,
        "briefing": briefing,
    }
    REPORT_FILE.write_text(json.dumps(report, indent=2))
    summary = f"{len(item_ids)} items from {len(snap['candidates'])} threads: {final['overview'].first_thing[:140]}"
    trace_store.record_run("inbox_report", "Quick Overview", "write", summary, elapsed)
    return report


def load_cached() -> dict | None:
    """The last overview, or None if one has never been generated."""
    return json.loads(REPORT_FILE.read_text()) if REPORT_FILE.exists() else None
