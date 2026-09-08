"""The inbox manager: acts on one triaged email with the tools its category allows, guided by long-term memory.

START -> recall -> act -+- get_thread / search_threads / now      (both categories)
                        +- invite_details / find_calendar_events   (agentrespond: read)
                        +- create_reminder / respond_to_invite     (agentrespond: write)
                        +- save_draft                              (agentdraftonly: the only write)
                        +- unknown_tool / repeat                   --> back to act
                        +- (no tool calls) -> END

agentrespond may change the calendar; agentdraftonly may only store a draft. Neither can send mail. What was done is
written to the email's `action`, saved, and traced.
"""

import json
import logging
import time
from dataclasses import replace
from functools import cache

from langchain_core.messages import SystemMessage, ToolMessage
from langgraph.graph import END, START, MessagesState, StateGraph

from mail_assistant.agents.llm.__structured_llm__ import chat_model
from mail_assistant.agents.skills import __skills__ as skills
from mail_assistant.agents.tools import __calendar_tools__ as calendar_tools
from mail_assistant.agents.tools import __gmail_tools__ as gmail_tools
from mail_assistant.db import __email_store__ as email_store
from mail_assistant.db import __memory_store__ as memory_store
from mail_assistant.db import __trace_store__ as trace_store
from mail_assistant.models.__email_message_model__ import Category, EmailMessage

log = logging.getLogger(__name__)

NAME = "manage"
SKILL = skills.load("inbox-manager")
HANDLED_CATEGORIES = (Category.AGENT_RESPOND, Category.AGENT_DRAFT_ONLY)
MAX_ROUNDS = 6
TOOL_RESULT_CHARS = 8_000

READ = [gmail_tools.get_thread, gmail_tools.search_threads, gmail_tools.now]
TOOLS_BY_CATEGORY = {
    Category.AGENT_RESPOND: [*READ, *calendar_tools.CALENDAR_TOOLS],
    Category.AGENT_DRAFT_ONLY: [*READ, gmail_tools.save_draft],
}
WRITE_TOOLS = {"create_reminder", "respond_to_invite", "save_draft"}
ALL_TOOLS = {t.name: t for tools in TOOLS_BY_CATEGORY.values() for t in tools}
UNKNOWN_TOOL = f"{NAME}__unknown_tool"
REPEAT = f"{NAME}__repeat"

SYSTEM_PROMPT = """You are the inbox manager for {name}.

{skill}

# Long-term memory

{memory}"""

TASK = """Category: {category}
Sender memory: {sender_memory}

The email:
From: {sender}
Subject: {subject}
Received: {received}
Message id: {message_id}
Thread id: {thread_id}

{body}

Act according to the skill for this category, then finish with one sentence saying what you did."""


def node_name(tool: str) -> str:
    return f"{NAME}__{tool}"


class ManagerState(MessagesState):
    """The email being handled, the memory block for the prompt, the round count, and the tools this run may use."""

    message: EmailMessage
    memory: str
    rounds: int
    allowed: list[str]


def recall(state: ManagerState) -> dict:
    """Load memory and describe the email; nothing here calls the model."""
    m = state["message"]
    pref = memory_store.get(m.sender)
    sender_memory = f"last decision {pref.category} (seen {pref.count}): {pref.reason}" if pref else "nothing yet"
    task = TASK.format(
        category=m.category.value,
        sender_memory=sender_memory,
        sender=m.sender,
        subject=m.subject,
        received=m.received_at.isoformat(timespec="minutes"),
        message_id=m.id,
        thread_id=m.thread_id,
        body=(m.body_text or m.snippet)[:4000],
    )
    return {
        "memory": memory_store.preferences_text(),
        "rounds": 0,
        "allowed": [t.name for t in TOOLS_BY_CATEGORY[m.category]],
        "messages": [{"role": "user", "content": task}],
    }


def act(state: ManagerState) -> dict:
    """One model call with the category's tools bound."""
    tools = TOOLS_BY_CATEGORY[state["message"].category]
    name = gmail_tools._mailbox().profile_email()
    prompt = SystemMessage(SYSTEM_PROMPT.format(name=name, skill=SKILL.body, memory=state["memory"]))
    message = chat_model().bind_tools(tools).invoke([prompt, *state["messages"]])
    calls = message.tool_calls or []
    wants = "wants " + ", ".join(c["name"] for c in calls) if calls else "done"
    log.info("Manager round %d: %s", state["rounds"] + 1, wants)
    return {"messages": [message], "rounds": state["rounds"] + 1}


def make_tool_node(tool):
    def run(state: ManagerState) -> dict:
        produced = []
        for call in getattr(state["messages"][-1], "tool_calls", None) or []:
            if call["name"] != tool.name:
                continue
            try:
                result = str(tool.invoke(call["args"]))
            except Exception as exc:
                result = f"{tool.name} failed: {exc}"
            produced.append(ToolMessage(content=result[:TOOL_RESULT_CHARS], tool_call_id=call["id"], name=tool.name))
        return {"messages": produced}

    return run


def _answer_calls(state: ManagerState, name: str, text) -> dict:
    """Reply to every pending tool call so the conversation stays well formed; `name` marks it as not a real result."""
    calls = getattr(state["messages"][-1], "tool_calls", None) or []
    return {"messages": [ToolMessage(content=text(c), tool_call_id=c["id"], name=name) for c in calls]}


def unknown_tool(state: ManagerState) -> dict:
    """Also answers calls to tools that exist but are not allowed for this category."""
    allowed = ", ".join(sorted(state["allowed"]))
    return _answer_calls(state, "unknown_tool", lambda c: f"{c['name']} is not available here. Available: {allowed}")


def repeat(state: ManagerState) -> dict:
    """Answer tool calls identical to earlier ones without running them again; small models loop otherwise."""
    return _answer_calls(state, "repeat", lambda c: f"{c['name']} was already called with these arguments; see above.")


def _call_key(call: dict) -> tuple[str, str]:
    return call["name"], json.dumps(call.get("args", {}), sort_keys=True)


def route(state: ManagerState):
    calls = getattr(state["messages"][-1], "tool_calls", None) or []
    if not calls or state["rounds"] >= MAX_ROUNDS:
        return END
    earlier = {_call_key(c) for m in state["messages"][:-1] for c in (getattr(m, "tool_calls", None) or [])}
    if all(_call_key(c) in earlier for c in calls):
        return REPEAT
    allowed = set(state["allowed"])
    return list(dict.fromkeys(node_name(c["name"]) if c["name"] in allowed else UNKNOWN_TOOL for c in calls))


_graph = StateGraph(ManagerState)
_graph.add_node("recall", recall)
_graph.add_node(NAME, act)
_graph.add_node(UNKNOWN_TOOL, unknown_tool)
_graph.add_node(REPEAT, repeat)
for _tool in ALL_TOOLS.values():
    _graph.add_node(node_name(_tool.name), make_tool_node(_tool))
    _graph.add_edge(node_name(_tool.name), NAME)
_graph.add_edge(START, "recall")
_graph.add_edge("recall", NAME)
_graph.add_edge(UNKNOWN_TOOL, NAME)
_graph.add_edge(REPEAT, NAME)
_graph.add_conditional_edges(NAME, route, [*(node_name(n) for n in ALL_TOOLS), UNKNOWN_TOOL, REPEAT, END])


@cache
def inbox_manager_agent():
    """Compiled once, with no checkpointer."""
    return _graph.compile()


def _outcome(messages: list) -> tuple[str, str]:
    """(what was done, tools used): the write tools' results if any, else the model's closing sentence."""
    used = [m.name for m in messages if isinstance(m, ToolMessage)]
    writes = [f"{m.name}: {m.content[:160]}" for m in messages if isinstance(m, ToolMessage) and m.name in WRITE_TOOLS]
    if writes:
        return "; ".join(writes), ",".join(dict.fromkeys(used))
    replies = (str(m.content).strip() for m in reversed(messages) if getattr(m, "type", "") == "ai")
    said = next((r for r in replies if r), "")
    return f"no action: {said[:200]}" if said else "no action", ",".join(dict.fromkeys(used))


def handle(message: EmailMessage) -> EmailMessage:
    """Run the manager on one email, record what it did on the email, save it, and write a trace line."""
    if message.category not in HANDLED_CATEGORIES:
        return message
    started = time.monotonic()
    try:
        config = {"recursion_limit": 4 + MAX_ROUNDS * 3}
        final = inbox_manager_agent().invoke({"message": message, "messages": []}, config=config)
        message.action, tools_used = _outcome(final["messages"])
    except Exception as exc:
        log.exception("Inbox manager failed for %s", message.id)
        message.action, tools_used = f"failed: {exc}", ""
    log.info("Inbox manager for %s: %s", message.id, message.action)
    email_store.save(message)
    traced = replace(message, reason=message.action, applied_rule=tools_used or "none")
    trace_store.record("inbox_manager", traced, int((time.monotonic() - started) * 1000))
    return message
