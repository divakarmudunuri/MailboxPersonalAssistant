"""Chat that edits the learned preferences: the model rewrites the prose per the person's message, then it is stored."""

import logging

from pydantic import BaseModel

from mail_assistant.agents.llm.__structured_llm__ import ask
from mail_assistant.db import __memory_store__ as memory_store

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You maintain a person's learned email-triage rules: a short list, one rule per line, in the form
"- rule_name: what to do". Rule names are short snake_case, unique, and must not reuse a base rule name. You are given
the base rules (fixed; you cannot change them and must not repeat them), the current learned rules, and the person's
message.
Return the complete updated learned rules: add, change, or remove lines exactly as the message asks and keep every
other line unchanged. A learned rule may override a base rule; say so in the line (for example "- ignore_github:
Ignore GitHub notifications, overriding github_notifications"). If the message is a question or not a preference,
return the learned rules unchanged.
Also return a one-sentence reply that confirms what changed, or answers the question.
Categories a rule may name: ignore, notify, agentrespond (the assistant replies alone), agentdraftonly (the assistant
drafts and the person reviews). Base rules never cause replies; a learned rule is the only way to make the assistant
reply, so a rule asking for a reply should say which sender or which kind of email it covers."""


class MemoryEdit(BaseModel):
    """Structured output: the rewritten learned preferences and a reply for the chat window."""

    learned_preferences: str
    reply: str


def chat(message: str) -> MemoryEdit:
    """Apply one chat message to the learned preferences and return the result."""
    current = memory_store.load().learned_preferences.strip() or "(none yet)"
    text = (
        f"Base rules:\n{memory_store.base_rules_text()}\n\nCurrent learned rules:\n{current}\n\n"
        f"Message from the person:\n{message}"
    )
    edit = ask(MemoryEdit, SYSTEM_PROMPT, text)
    memory_store.update_preferences(edit.learned_preferences)
    log.info("Learned preferences updated via chat: %s", edit.reply)
    return edit
