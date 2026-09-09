"""Chat that edits the learned preferences: the model rewrites the prose per the person's message, then it is stored."""

import logging
import re
import time

from pydantic import BaseModel

from mail_assistant.agents.llm.__structured_llm__ import ask
from mail_assistant.config.__app_config__ import MEMORY_CHAT_LLM
from mail_assistant.db import __memory_store__ as memory_store
from mail_assistant.db import __trace_store__ as trace_store

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You maintain a person's learned email-triage rules: a short list, one rule per line, in the form
"- rule_name: what to do". Rule names are short snake_case, unique, and must not reuse a base rule name. You are given
the base rules (fixed; you cannot change them and must not repeat them), the current learned rules, and the person's
message.
Return only the edits the message asks for: `add` holds new rules, each under a new name (a sender may have several
rules, for example one for calendar invitations and one for other mail; never reuse an existing name unless the
message asks to change that rule), and `remove` holds the names of rules the message asks to drop. Every rule you do
not name stays exactly as it is; never remove, replace, or fold rules unless the message explicitly asks for that.
One sender may have several rules that each cover a different kind of mail (for example calendar invitations and
everything else); they coexist and must not mention each other. A learned rule may override a base rule only; say
so in the rule (for example "Ignore GitHub notifications, overriding github_notifications") and never write
"overriding" with a learned rule's name. If the message is a question or not a preference, return no edits.
Also return a one-sentence reply that confirms what changed, or answers the question.
Categories a rule may name: ignore, notify, auto_schedule (the assistant puts a reminder on the calendar or answers
a meeting invitation by itself), auto_draft (the assistant drafts a reply and the person reviews it). Base rules
never cause actions; a learned rule is the only way to make the assistant act, so a rule asking for one should say
which sender or which kind of email it covers."""


class Rule(BaseModel):
    name: str  # snake_case, unique
    text: str  # what to do


class MemoryEdit(BaseModel):
    """Structured output: the rules to add or replace, the names to remove, and a reply for the chat window."""

    add: list[Rule]
    remove: list[str]
    reply: str


# A rule is removed or replaced only when the person's message says so; models "tidy" otherwise.
_REPLACE_WORDS = re.compile(
    r"\b(remove|delete|drop|forget|stop|no longer|instead|replace|change|update|rename|clear|reset|erase|wipe)\b", re.I
)
# "clear memory", "reset all rules", "remove everything": every learned rule goes, whatever the model returned.
_CLEAR_ALL = re.compile(
    r"\b(clear|reset|erase|wipe|remove|delete|forget)\b.*\b(memory|memort|all|everything|every rule|all rules|"
    r"all preferences|learned rules|learned preferences)\b",
    re.I,
)


def _no_learned_override(text: str, learned: set[str]) -> str:
    """Drop an "overriding <name>" clause naming a learned rule: learned rules coexist and only override base ones."""

    def keep(m: re.Match) -> str:
        return "" if m.group(1) in learned else m.group(0)

    return re.sub(r",?\s*overriding\s+([a-z0-9_]+)", keep, text, flags=re.I).strip(" ,.") + "."


def _apply(rules: dict[str, str], edit: MemoryEdit, message: str) -> dict[str, str]:
    """Apply the edit to the named rules. Nothing the edit does not name can change, and nothing is removed or
    overwritten unless the message itself asks for a removal or a change; an unasked-for overwrite becomes a new
    rule."""
    if _CLEAR_ALL.search(message):
        return {}
    may_replace = bool(_REPLACE_WORDS.search(message))
    updated = {name: text for name, text in rules.items() if not (may_replace and name in edit.remove)}
    learned = set(rules) | {r.name.strip().lower().replace(" ", "_") for r in edit.add}
    for rule in edit.add:
        name, text = rule.name.strip().lower().replace(" ", "_"), _no_learned_override(rule.text.strip(), learned)
        if not name or not text:
            continue
        if name in updated and updated[name] != text and not may_replace:
            if text in updated.values():
                continue  # already there under another name
            name = next(f"{name}_{n}" for n in range(2, 100) if f"{name}_{n}" not in updated)
        updated[name] = text
    return updated


def chat(message: str) -> MemoryEdit:
    """Apply one chat message to the learned preferences and return the result."""
    current = memory_store.load().learned_preferences.strip() or "(none yet)"
    text = (
        f"Base rules:\n{memory_store.base_rules_text()}\n\nCurrent learned rules:\n{current}\n\n"
        f"Message from the person:\n{message}"
    )
    started = time.monotonic()
    edit = ask(MemoryEdit, SYSTEM_PROMPT, text, run_name="memory_chat", llm=MEMORY_CHAT_LLM)
    before = memory_store.learned_rules()
    after = _apply(before, edit, message)
    if after != before:
        memory_store.update_preferences("\n".join(f"- {name}: {text}" for name, text in after.items()))
    if any(name in after for name in edit.remove):  # the model wanted to drop a rule the message did not ask about
        edit.reply += " Nothing was removed; to drop a rule, say remove, delete, or clear."
    log.info("Learned preferences via chat (%+d rules): %s", len(after) - len(before), edit.reply)
    rule = "rules_updated" if after != before else "rules_unchanged"
    trace_store.record_run("memory_chat", message, rule, edit.reply, int((time.monotonic() - started) * 1000))
    return edit
