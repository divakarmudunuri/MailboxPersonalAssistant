"""Turns the person's feedback on one email into standing preferences, then triages the email again.

The feedback is prose ("never ignore mail from x", "this is spam", "invites from her: accept them"). One structured
model call reads it with the email and the current learned rules and returns what it means: keep or ignore the
sender, and optionally a learned rule. Code applies those to the keep list, the ignore list, and long-term memory
(through the memory chat's own merge, so nothing unrelated changes), then the triage graph runs on the email again.
"""

import logging
import time
from dataclasses import replace

from pydantic import BaseModel

from mail_assistant.agents import __memory_chat_agent__ as memory_chat
from mail_assistant.agents.__email_triage_router_agent__ import triage_new_email
from mail_assistant.agents.llm.__structured_llm__ import ask
from mail_assistant.config.__app_config__ import MEMORY_CHAT_LLM
from mail_assistant.db import __memory_store__ as memory_store
from mail_assistant.db import __pre_triage_ignore_store__ as ignore_list
from mail_assistant.db import __pre_triage_keep_store__ as keep_list
from mail_assistant.db import __trace_store__ as trace_store
from mail_assistant.models.__email_message_model__ import Category, EmailMessage
from mail_assistant.models.__pre_triage_ignore_model__ import IgnoreReason

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You read a person's feedback about one email and turn it into standing preferences for their
inbox assistant. You are given the email's sender and subject, the current learned rules, and the feedback.
Decide:
- keep_sender: true when the feedback says mail from this sender must never be ignored, blocked, or filtered
  out (words like never ignore, always show, don't block, important, keep).
- ignore_sender: true when the feedback says mail from this sender is not worth seeing (ignore, block, spam,
  junk, unsubscribe, stop showing). Then set ignore_reason to one of: promotions, newsletter, social, forums, spam,
  subscription, marketing, notification, miscellaneous.
- rule: a learned rule only when the feedback states a standing preference beyond keep or ignore, such as what
  the assistant should do with this sender's mail (notify, auto_draft a reply, auto_schedule invitations) or a
  condition (time window, kind of mail). Give it a short snake_case name that includes the sender's domain or
  name, and text that names the sender's address. Leave it empty when keep or ignore already says everything, or
  when an existing learned rule already covers this sender the same way.
Never set both keep_sender and ignore_sender. Feedback about this one email only ("not this time") sets neither
and adds no rule. Also return a one-sentence reply that says what will change."""


class Feedback(BaseModel):
    """What the person's feedback means for the sender, plus a reply for the UI."""

    keep_sender: bool
    ignore_sender: bool
    ignore_reason: str = ""
    rule_name: str = ""
    rule_text: str = ""
    reply: str


def _apply_rule(name: str, text: str, feedback: str) -> bool:
    """Add the learned rule through the memory chat's merge; True when the rules changed."""
    before = memory_store.learned_rules()
    edit = memory_chat.MemoryEdit(add=[memory_chat.Rule(name=name, text=text)], remove=[], reply="")
    after = memory_chat._apply(before, edit, feedback)
    if after != before:
        memory_store.update_preferences("\n".join(f"- {n}: {t}" for n, t in after.items()))
    return after != before


def retriage(message: EmailMessage, feedback: str) -> tuple[EmailMessage, dict]:
    """Apply the feedback to the lists and memory, trace it, run the triage graph again, and return the email plus a
    summary of what changed: {reply, kept, ignored, rule_added}."""
    started = time.monotonic()
    address = memory_store.address(message.sender)
    text = (
        f"Email from: {message.sender}\nSubject: {message.subject}\n\n"
        f"Current learned rules:\n{memory_store.load().learned_preferences.strip() or '(none yet)'}\n\n"
        f"Feedback from the person:\n{feedback}"
    )
    fb = ask(Feedback, SYSTEM_PROMPT, text, run_name="feedback", llm=MEMORY_CHAT_LLM)
    changed = {"reply": fb.reply, "kept": False, "ignored": "", "rule_added": ""}
    learn = lambda action, subject: trace_store.record_learning(action, subject, "feedback", feedback, message)  # noqa: E731
    if fb.keep_sender and not fb.ignore_sender:
        if not keep_list.covers(address):
            keep_list.add(address)
            learn("keep_list_added", address)
        if was := ignore_list.label_for(address):
            ignore_list.remove(address)
            learn("ignore_list_removed", f"{address} (was {was.value})")
        changed["kept"] = True
    elif fb.ignore_sender:
        label = fb.ignore_reason if fb.ignore_reason in IgnoreReason.__members__.values() else "miscellaneous"
        if keep_list.covers(address) == address:
            keep_list.remove(address)
            learn("keep_list_removed", address)
        if ignore_list.label_for(address) != IgnoreReason(label):
            ignore_list.add(address, IgnoreReason(label), "user")
            learn("ignore_list_added", f"{address} -> {label}")
        changed["ignored"] = label
    if fb.rule_name.strip() and fb.rule_text.strip() and _apply_rule(fb.rule_name, fb.rule_text, feedback):
        changed["rule_added"] = fb.rule_name.strip().lower().replace(" ", "_")
        learn("learned_rule_added", f"{changed['rule_added']}: {fb.rule_text.strip()}"[:200])
    log.info("Feedback on %s: %s", message.id, changed)
    traced = replace(message, reason=feedback, applied_rule="feedback")
    trace_store.record("manual_user_input", traced, int((time.monotonic() - started) * 1000), "user_requested_retriage")
    message.category, message.reason, message.applied_rule, message.action = Category.PENDING, "", "", ""
    return triage_new_email(message), changed
