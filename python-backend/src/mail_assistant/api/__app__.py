"""FastAPI service exposing triaged emails, long-term memory, and the triage graph to the React UI."""

import asyncio

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from mail_assistant.agents import __inbox_manager_agent__ as inbox_manager
from mail_assistant.agents import __inbox_report_agent__ as inbox_report
from mail_assistant.agents.__email_triage_router_agent__ import email_triage_router_agent, triage_new_email
from mail_assistant.agents.__memory_chat_agent__ import chat
from mail_assistant.agents.tools import __gmail_tools__ as gmail_tools
from mail_assistant.config.__app_config__ import UI_DIST_DIR, configure_logging
from mail_assistant.db import __email_store__ as email_store
from mail_assistant.db import __memory_store__ as memory_store
from mail_assistant.db import __pre_triage_ignore_store__ as ignore_list
from mail_assistant.db import __trace_store__ as trace_store
from mail_assistant.models.__email_message_model__ import Category, EmailMessage
from mail_assistant.models.__pre_triage_ignore_model__ import IgnoreEntry, IgnoreReason
from mail_assistant.models.__trace_model__ import TraceEntry

configure_logging()
app = FastAPI(title="Mail Assistant API")


class CategoryUpdate(BaseModel):
    """Body of the PATCH endpoint."""

    category: Category
    reason: str = ""


class Draft(BaseModel):
    """A reply the inbox manager drafted, for the person to edit and send."""

    to: str
    subject: str
    body: str
    draft_message_id: str  # the copy saved in Gmail's Drafts folder, discarded when the reply is sent


class SendReply(BaseModel):
    """Body of the send endpoint: the (edited) draft."""

    to: str
    subject: str
    body: str
    draft_message_id: str = ""


class EmailPage(BaseModel):
    """One page of the email list."""

    items: list[EmailMessage]
    total: int
    page: int
    page_size: int


class BaseRule(BaseModel):
    name: str
    text: str
    outcome: str


class MemoryView(BaseModel):
    """Long-term memory as the UI shows it: named base rules from code and the learned rules."""

    base_rules: list[BaseRule]
    learned_preferences: str


class HomeList(BaseModel):
    """A count plus the newest few emails behind it."""

    total: int
    items: list[EmailMessage]


class HomeView(BaseModel):
    """What the Home tab shows beside the briefing."""

    waiting: HomeList  # notify, auto_draft, and pending mail: triage items waiting on the person
    actions: HomeList  # mail the inbox manager acted on, with the action on each email


class TracePage(BaseModel):
    """One page of the trace log, newest first."""

    items: list[TraceEntry]
    total: int
    page: int
    page_size: int


class IgnoreSender(BaseModel):
    """Body for adding one sender to the pre-triage ignore list."""

    sender: str
    ignore_reason_label: IgnoreReason


class ChatMessage(BaseModel):
    message: str


class ChatReply(BaseModel):
    reply: str
    learned_preferences: str


class GraphNode(BaseModel):
    """A node of the triage graph with the docstring of the function behind it."""

    id: str
    description: str


class GraphEdge(BaseModel):
    source: str
    target: str
    conditional: bool


class GraphShape(BaseModel):
    """One agent's graph: nodes in a stable order plus edges, for drawing in the UI."""

    name: str
    description: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]


@app.get("/api/emails")
def list_emails(
    category: Category | None = None, q: str = "", page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)
) -> EmailPage:
    """Paginated email list, optionally filtered by category and a case-insensitive text search."""
    items, total = email_store.list_emails(category, page, page_size, q.strip())
    return EmailPage(items=items, total=total, page=page, page_size=page_size)


@app.get("/api/emails/{email_id}")
def get_email(email_id: str) -> EmailMessage:
    """One email by id; a row stored with an empty body (older parser, HTML-only mail) is filled from the mailbox."""
    message = _stored(email_id)
    if not message.body_text and (body := gmail_tools._mailbox().body_of(message.id)):
        message.body_text, message.snippet = body, " ".join(body.split())[:200]
        email_store.save(message)
    return message


def _stored(email_id: str) -> EmailMessage:
    message = email_store.get(email_id)
    if message is None:
        raise HTTPException(404, "email not found")
    return message


@app.patch("/api/emails/{email_id}")
def update_email(email_id: str, update: CategoryUpdate) -> EmailMessage:
    """Apply the user's category and reason, then run the graph as a user decision: saved, remembered, routed."""
    message = _stored(email_id)
    message.category, message.reason, message.applied_rule = update.category, update.reason, "manual"
    return triage_new_email(message, source="user")


@app.post("/api/emails/{email_id}/read")
def mark_read(email_id: str) -> EmailMessage:
    """Mark the email read in Gmail and drop its UNREAD label here."""
    message = _stored(email_id)
    if not gmail_tools._mailbox().mark_read(message.id):
        raise HTTPException(404, "email no longer in the mailbox")
    message.label_ids = [lbl for lbl in message.label_ids if lbl != "UNREAD"]
    email_store.save(message)
    return message


@app.get("/api/emails/{email_id}/draft")
def stored_draft(email_id: str) -> Draft:
    """The draft already in Gmail's Drafts on this email's thread, written by the manager or by hand (404 if none)."""
    draft = gmail_tools._mailbox().draft_on_thread(_stored(email_id).thread_id)
    if draft is None:
        raise HTTPException(404, "no draft on this thread")
    return Draft(**draft)


@app.post("/api/emails/{email_id}/draft")
def draft_reply(email_id: str) -> Draft:
    """Have the inbox manager draft a reply now (saved in Gmail's Drafts) and return it for editing."""
    message = _stored(email_id)
    draft = inbox_manager.draft_reply(message)
    if draft is None:
        raise HTTPException(502, f"the inbox manager wrote no draft: {message.action}")
    return Draft(**draft)


@app.post("/api/emails/{email_id}/send")
def send_reply(email_id: str, reply: SendReply) -> EmailMessage:
    """Send the edited draft as a reply on the thread, discard the Gmail draft, and file the email as replied."""
    message = _stored(email_id)
    mailbox = gmail_tools._mailbox()
    mailbox.send_reply(message.id, reply.to, reply.subject, reply.body)
    on_thread = mailbox.draft_on_thread(message.thread_id) or {}
    for draft_id in {reply.draft_message_id, on_thread.get("draft_message_id", "")} - {""}:
        mailbox.discard_draft(draft_id)
    message.category, message.applied_rule = Category.USER_REPLY_COMPLETE, "manual"
    message.reason, message.action = "Replied from the Inbox tab", f"reply sent to {reply.to}"
    return triage_new_email(message, source="user")


@app.get("/api/memory")
def get_memory() -> MemoryView:
    """Everything in long-term memory, for the Memory tab."""
    base_rules = [BaseRule(name=n, text=t, outcome=o) for n, t, o in memory_store.LONG_TERM_MEMORY]
    return MemoryView(base_rules=base_rules, learned_preferences=memory_store.load().learned_preferences)


@app.post("/api/memory/chat")
def memory_chat(body: ChatMessage) -> ChatReply:
    """Apply a chat message to the learned preferences through the model and return its reply."""
    edit = chat(body.message.strip())
    return ChatReply(reply=edit.reply, learned_preferences=memory_store.load().learned_preferences)


@app.get("/api/report")
def get_report() -> dict:
    """The last inbox briefing. `briefing` is null until one has been generated."""
    return inbox_report.load_cached() or {"generated_at": None, "counts": {}, "briefing": None}


@app.post("/api/report/refresh")
async def refresh_report() -> dict:
    """Read the inbox and write a fresh briefing. Costs several model calls; runs off the event loop."""
    try:
        return await asyncio.to_thread(inbox_report.generate, True)  # force: the person asked for a rebuild
    except Exception as exc:
        raise HTTPException(502, f"Could not build the briefing: {exc}") from exc


@app.get("/api/home")
def get_home() -> HomeView:
    """Counts for the Home tab: mail waiting on the person, and actions the inbox manager took."""
    waiting, waiting_total = email_store.waiting_on_user()
    acted, acted_total = email_store.with_actions()
    return HomeView(
        waiting=HomeList(total=waiting_total, items=waiting),
        actions=HomeList(total=acted_total, items=acted),
    )


@app.get("/api/ignore-list")
def get_ignore_list() -> list[IgnoreEntry]:
    """The pre-triage ignore list: senders grouped by reason."""
    return ignore_list.load()


@app.post("/api/ignore-list")
def add_ignored_sender(body: IgnoreSender) -> list[IgnoreEntry]:
    """Add one sender under a reason; a sender already listed moves to that reason."""
    return ignore_list.add(body.sender.strip(), body.ignore_reason_label)


@app.delete("/api/ignore-list/{sender}")
def remove_ignored_sender(sender: str) -> list[IgnoreEntry]:
    """Take one sender off the list."""
    return ignore_list.remove(sender)


@app.get("/api/traces")
def list_traces(
    q: str = "", step: str = "", page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)
) -> TracePage:
    """Paginated trace log, newest first, optionally limited to one step and filtered by a text search."""
    items, total = trace_store.list_traces(q.strip(), page, page_size, step.strip())
    return TracePage(items=items, total=total, page=page, page_size=page_size)


def _shape(name: str, description: str, compiled, tools: dict) -> GraphShape:
    """Describe one compiled graph: function nodes by docstring, tool nodes by the tool's description."""
    graph = compiled.get_graph()
    docs = {}
    for node_name, node in compiled.builder.nodes.items():
        tool = tools.get(node_name.split("__", 1)[-1]) if "__" in node_name else None
        func = getattr(node.runnable, "func", None)
        docs[node_name] = tool.description if tool else (func.__doc__ or "") if func else ""
    nodes = [GraphNode(id=n, description=" ".join(docs.get(n, "").split())) for n in graph.nodes]
    edges = [GraphEdge(source=e.source, target=e.target, conditional=bool(e.conditional)) for e in graph.edges]
    return GraphShape(name=name, description=description, nodes=nodes, edges=edges)


@app.get("/api/graph")
def get_graphs() -> list[GraphShape]:
    """Every agent graph in the app, as LangGraph draws them, for the Graph tab."""
    return [
        _shape(
            "Email triage router",
            "Runs for every new email from the watcher, and for a category saved by hand in the UI.",
            email_triage_router_agent,
            {},
        ),
        _shape(
            "Inbox manager",
            "Runs from the router's inbox_manager node for auto_schedule and auto_draft mail.",
            inbox_manager.inbox_manager_agent(),
            inbox_manager.ALL_TOOLS,
        ),
        _shape(
            "Inbox report",
            "Runs at startup, every REPORT_INTERVAL_SECONDS, and on Rebuild from the Home tab.",
            inbox_report.inbox_report_agent(),
            {},
        ),
    ]


# Serve the production UI build at / when it exists; API routes above take precedence.
if UI_DIST_DIR.is_dir():
    app.mount("/", StaticFiles(directory=UI_DIST_DIR, html=True), name="ui")
