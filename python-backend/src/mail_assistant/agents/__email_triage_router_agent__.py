"""LangGraph StateGraph that triages a new email with the configured LLM, stores it, and routes it onward.

START -> check_source -> (saved by the user in the UI) -> save
                         (new mail from the watcher)  -> pre_triage
pre_triage -> (already replied, or ignored by a Gmail label) -> save
              (otherwise)                                     -> recall -> triage -> save
save -> remember -> (auto_schedule | auto_draft) -> inbox_manager -> END
                    (anything else)                 -> END

`recall` loads the preferences (base rules from code plus learned ones from the memory file) and what is remembered
about the sender; `triage` puts the preferences in the system prompt and the sender fact in the user turn;
`remember` writes the decision back to long-term memory.
"""

import logging
import re
import time
from functools import cache
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from mail_assistant.agents import __inbox_manager_agent__ as inbox_manager
from mail_assistant.agents.__inbox_manager_agent__ import HANDLED_CATEGORIES
from mail_assistant.agents.llm.__structured_llm__ import ask
from mail_assistant.config.__app_config__ import PRE_TRIAGE_IGNORE_LABELS
from mail_assistant.db import __email_store__ as email_store
from mail_assistant.db import __memory_store__ as memory_store
from mail_assistant.db import __pre_triage_ignore_store__ as ignore_list
from mail_assistant.db import __trace_store__ as trace_store
from mail_assistant.gmail_client import GmailImapClient
from mail_assistant.models.__email_message_model__ import Category, EmailMessage

log = logging.getLogger(__name__)

# Mail Gmail has already sorted away from the primary inbox is ignored in pre_triage without a model call.
# Rule name -> Gmail search term. `category:updates` is left out on purpose: receipts and notifications live there.
IGNORE_BY_GMAIL: dict[str, str] = {
    "gmail_promotions": "category:promotions",
    "gmail_social": "category:social",
    "gmail_forums": "category:forums",
    "gmail_spam": "in:spam",
    "gmail_muted": "is:muted",
}

SYSTEM_PROMPT = """You triage a personal inbox so the assistant does not waste time on low-value mail.
Classify the email as exactly one of:
- ignore: a base or learned rule says it is not worth responding to or knowing about.
- notify: the default for everything else. The person should know about it and the assistant will not reply.
  Also use notify when you cannot tell which category applies; then set `rule` to `none`.
- auto_schedule or auto_draft: only when a learned rule says the assistant should act on this sender or this
  kind of email. Never choose either without such a rule, even if the email asks a question. When several learned
  rules cover the same sender, apply the one whose kind of mail matches this email (a rule about calendar
  invitations beats a rule about that sender's mail in general). Choose auto_schedule
  when the action is on the calendar: a reminder to create or a meeting invitation to answer. Choose auto_draft
  when a written reply is wanted; the assistant drafts it and the person reviews it before anything is sent.
Guardrail: once a learned rule has called for an action, choose auto_draft rather than auto_schedule if the email
mentions money, prices, contracts, leases, offers, deadlines with consequences, or asks the person to decide,
agree, or negotiate anything, or whenever you are unsure. If no learned rule calls for a reply, the answer is
ignore or notify, nothing else. A learned rule that names an email address or domain applies only to senders at
that address or domain.
The preferences below describe this person's inbox: follow them, and when a learned rule conflicts with a base
rule, the learned rule wins. Stay consistent with what is remembered about the sender unless this email is
clearly different.
Give a one-sentence reason. In `rule`, give only the name of the single rule that most determined your decision:
a base rule name, a learned rule name, or `none`. For a reply, always name the learned rule that called for it.
No other words."""


class TriageDecision(BaseModel):
    """Structured output the model must return."""

    category: Literal["ignore", "notify", "auto_schedule", "auto_draft"]
    reason: str
    rule: str  # name of the rule applied, or "none"


_ADDRESS_OR_DOMAIN = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+|\b[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}\b", re.IGNORECASE)


def _reply_allowed(rule: str, learned_rules: dict[str, str], sender: str) -> bool:
    """A reply must rest on a named learned rule; a rule that names addresses or domains must match the sender."""
    if rule not in learned_rules:
        return False
    scopes = [s.lower() for s in _ADDRESS_OR_DOMAIN.findall(learned_rules[rule])]
    address = memory_store.address(sender)
    return not scopes or any(address == s or address.endswith("@" + s) or address.endswith("." + s) for s in scopes)


def _rule_name(raw: str) -> str:
    """Reduce the model's `rule` to a bare name: first token, without backticks or a trailing colon."""
    return raw.strip().split()[0].strip("`:") if raw.strip() else "none"


class State(TypedDict, total=False):
    """The one email flowing through the graph, where it came from, and what long-term memory contributes."""

    message: EmailMessage
    source: Literal["cron", "user"]  # "user" when the category was set by hand in the UI
    preferences: str  # base rules + learned preferences, for the system prompt
    learned_rules: dict[str, str]  # learned rules by name; only these can unlock a reply


@cache
def _gmail() -> GmailImapClient:
    """One mailbox client for the reply check, created on first use."""
    return GmailImapClient()


def check_source(state: State) -> State:
    """Note when the decision was made by the user (trace step `manual_user_input`); such messages are stored as-is
    without triage."""
    if state.get("source") == "user":
        m = state["message"]
        log.info("User set %s to %s; skipping triage", m.id, m.category)
        trace_store.record("manual_user_input", m, 0)
    return state


def route_by_source(state: State) -> Literal["save", "pre_triage"]:
    """User decisions go straight to save; new mail from the poller is checked and triaged."""
    return "save" if state.get("source") == "user" else "pre_triage"


def _ignore_rule(m: EmailMessage) -> str | None:
    """The rule that ignores this email without a model call, or None: your labels, Gmail's tabs, the ignore list."""
    labels = {lbl.lstrip("\\").lower() for lbl in m.label_ids}  # Gmail's IMAP names: \\Sent, \\Draft, \\Important, ...
    for label in PRE_TRIAGE_IGNORE_LABELS:
        if label.lower() in labels:
            return f"label_{label.lower()}"
    for rule, query in IGNORE_BY_GMAIL.items():
        if _gmail().matches(m.id, query):
            return rule
    if reason := ignore_list.label_for(memory_store.address(m.sender)):
        return f"ignore_list_{reason}"
    return None


def pre_triage(state: State) -> State:
    """Decide without the model where possible: already replied, or sorted away from the inbox by a Gmail label."""
    m = state["message"]
    started = time.monotonic()
    try:
        if _gmail().has_been_replied_to(m):
            m.category, m.applied_rule = Category.USER_REPLY_COMPLETE, "pre_triage"
            m.reason = "You already replied in this thread."
            log.info("Skipping triage for %s: already replied", m.id)
        elif rule := _ignore_rule(m):
            m.category, m.applied_rule = Category.IGNORE, rule
            m.reason = (
                f"Sender is on the pre-triage ignore list as {rule.removeprefix('ignore_list_')}."
                if rule.startswith("ignore_list_")
                else f"Gmail label rule {rule}: sorted away from the primary inbox, so not worth triaging."
            )
            log.info("Skipping triage for %s: %s", m.id, rule)
    except Exception:
        log.exception("Pre-triage check failed for %s; triaging anyway", m.id)
    trace_store.record("pre_triage", m, int((time.monotonic() - started) * 1000))
    return state


def route_after_pre_triage(state: State) -> Literal["save", "recall"]:
    """Emails pre_triage already decided skip the model; everything else consults memory first."""
    decided = (Category.USER_REPLY_COMPLETE, Category.IGNORE)
    return "save" if state["message"].category in decided else "recall"


def recall(state: State) -> State:
    """Load the preferences block: base rules from code plus the learned rules."""
    return {"preferences": memory_store.preferences_text(), "learned_rules": memory_store.learned_rules()}


def _prompt_text(m: EmailMessage) -> str:
    return f"From: {m.sender}\nSubject: {m.subject}\n\n{m.body_text or m.snippet}"


def triage(state: State) -> State:
    """Ask the model for a category and reason; on any failure leave the email pending with the error as reason."""
    m = state["message"]
    log.info("Triaging mail from %s: %r", m.sender, m.subject)
    log.debug("%s\n%s\n%s", "-" * 80, m, "-" * 80)
    text = _prompt_text(m)
    system = f"{SYSTEM_PROMPT}\n\n{state.get('preferences') or memory_store.preferences_text()}"
    started = time.monotonic()
    try:
        decision = ask(TriageDecision, system, text, run_name="triage_decision")
        m.category, m.reason, m.applied_rule = Category(decision.category), decision.reason, _rule_name(decision.rule)
        allowed = _reply_allowed(m.applied_rule, state.get("learned_rules", {}), m.sender)
        if m.category in HANDLED_CATEGORIES and not allowed:
            log.info("No learned rule behind %s for %s; downgrading to notify", m.category, m.id)
            m.category, m.applied_rule = Category.NOTIFY, "none"
    except Exception as exc:
        log.exception("Triage failed for %s; leaving it pending", m.id)
        m.category, m.reason, m.applied_rule = Category.PENDING, f"triage failed: {exc}", ""
    log.info("Categorized %s as %s (rule %s): %s", m.id, m.category, m.applied_rule or "none", m.reason)
    trace_store.record("triage", m, int((time.monotonic() - started) * 1000))
    return state


def remember(state: State) -> State:
    """File a sender-stable ignore on the pre-triage ignore list; no other decision leaves anything behind."""
    m = state["message"]
    if m.category is Category.IGNORE and (reason := ignore_list.reason_for(m.applied_rule, m.reason)):
        ignore_list.add(memory_store.address(m.sender), reason)
    return state


def manage(state: State) -> State:
    """Hand a reply-category email to the inbox manager, which records its action on the email."""
    inbox_manager.handle(state["message"])
    return state


def save(state: State) -> State:
    """Persist the triaged email so it is visible in the UI before any agent acts on it."""
    email_store.save(state["message"])
    return state


def route_by_category(state: State) -> Literal["inbox_manager", "__end__"]:
    """Send auto_schedule and auto_draft emails to the inbox manager; everything else is done."""
    return "inbox_manager" if state["message"].category in HANDLED_CATEGORIES else END


_graph = StateGraph(State)
_graph.add_node("check_source", check_source)
_graph.add_node("pre_triage", pre_triage)
_graph.add_node("recall", recall)
_graph.add_node("triage", triage)
_graph.add_node("remember", remember)
_graph.add_node("save", save)
_graph.add_node("inbox_manager", manage)
_graph.add_edge(START, "check_source")
_graph.add_conditional_edges("check_source", route_by_source)
_graph.add_conditional_edges("pre_triage", route_after_pre_triage)
_graph.add_edge("recall", "triage")
_graph.add_edge("triage", "save")
_graph.add_edge("save", "remember")
_graph.add_conditional_edges("remember", route_by_category)
_graph.add_edge("inbox_manager", END)
email_triage_router_agent = _graph.compile()


def triage_new_email(message: EmailMessage, source: Literal["cron", "user"] = "cron") -> EmailMessage:
    """Run the graph on one email and return it with category and reason filled in."""
    run = {
        "run_name": "email_triage_router",
        "tags": [source],
        "metadata": {
            "email_id": message.id,
            "thread_id": message.thread_id,
            "sender": memory_store.address(message.sender),
        },
    }
    return email_triage_router_agent.invoke({"message": message, "source": source}, config=run)["message"]
