"""The inbox report agent: a start-of-day briefing written from what the model reads for itself.

START -> recall -> report -+- search_threads -+
                           +- get_thread -----+
                           +- list_drafts ----+--> back to report
                           +- unread_count ---+
                           +- now ------------+
                           +- unknown_tool ---+
                           +- repeat ---------+   (a call identical to an earlier one is answered from memory)
                           +- insist ---------+   (once, if it wrote without opening a thread)
                           +- (no tool calls) -> END

Nothing pre-digests the inbox into the prompt: a model handed a summary answers from the summary. Every fact in the
briefing has to come from a tool result the model asked for. Every tool is read-only, so this runs without asking.
"""

import json
import logging
from datetime import UTC, datetime
from functools import cache

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, MessagesState, StateGraph

from mail_assistant.agents.llm.__structured_llm__ import chat_model
from mail_assistant.agents.skills import __skills__ as skills
from mail_assistant.agents.tools import __gmail_tools__ as gmail_tools
from mail_assistant.config.__app_config__ import REPORT_FILE, REPORT_LLM_PROVIDER, REPORT_MODEL
from mail_assistant.db import __email_store__ as email_store
from mail_assistant.db import __memory_store__ as memory_store

log = logging.getLogger(__name__)

NAME = "report"
SKILL = skills.load("inbox-report")
MAIL_WINDOW_DAYS = 14  # substituted into the skill text too, so the prose and the query never disagree
TOOL_RESULT_CHARS = 8_000  # a long thread must not crowd out the rest of the conversation
MAX_ROUNDS = 8  # model calls before the agent must answer with what it has

SYSTEM_PROMPT = """You are the inbox reporting agent for {name}.

{skill}

# Long-term memory

{memory}

Memory wins over your own reading of an email: anything it marks ignore stays out of the briefing, and learned rules
override base rules. Use the triage decisions to choose which threads to open.

Write prose in the section format above, starting directly with the first section: no title, no preamble, no
remarks about what you are about to do. Never output JSON, a list of raw tool results, or anything a person would
not read over coffee: the tool output is your research, not your answer."""

# The task names the exact query: left to compose one, a small model writes Gmail syntax that does not exist.
TASK = (
    "Write today's briefing. Call now() first. Then search_threads with the query "
    f"'in:inbox newer_than:{MAIL_WINDOW_DAYS}d', then list_drafts and unread_count. Open anything actionable with "
    "get_thread, which returns the whole thread including earlier messages and the person's own replies: a date or "
    "commitment you have not read in a body does not go in the briefing."
)
REWRITE = (
    "That is research, not a briefing. Using only what the tool results above say, write the briefing now as prose "
    "in the section format, with no JSON, no code fences, and no tool output."
)
INSIST = (
    "You have not opened a single thread. A snippet is not enough to report a deadline, a request, or a suspicious "
    "message: call get_thread on every thread that looks actionable, then write the briefing from what the bodies "
    "say. If nothing looks actionable, say so in the briefing and write it anyway."
)

# The report only ever reads: it is never offered a tool it must not use.
TOOLS = [
    gmail_tools.search_threads,
    gmail_tools.get_thread,
    gmail_tools.list_drafts,
    gmail_tools.unread_count,
    gmail_tools.now,
]
TOOLS_BY_NAME = {t.name: t for t in TOOLS}
UNKNOWN_TOOL = f"{NAME}__unknown_tool"
REPEAT = f"{NAME}__repeat"


def _model():
    """The briefing's own model, which need not be the triage model."""
    return chat_model(REPORT_LLM_PROVIDER, REPORT_MODEL)


def node_name(tool: str) -> str:
    """The graph node that runs `tool`."""
    return f"{NAME}__{tool}"


class BriefingState(MessagesState):
    """Messages plus the recalled memory, the counts the UI shows, and how many model calls have been made."""

    name: str
    memory: str  # base rules, learned rules, remembered senders, and recent triage decisions, for the system prompt
    counts: dict
    rounds: int


def _memory_text() -> str:
    """Everything the assistant already knows, as the block the report prompt carries."""
    decisions = email_store.recent(MAIL_WINDOW_DAYS)
    lines = [
        f"- {m.category} ({m.applied_rule or 'no rule'}) | {m.sender} | {m.subject} | thread {m.thread_id}"
        for m in decisions
    ]
    return (
        f"{memory_store.preferences_text()}\n\n"
        f"## Remembered senders\n{memory_store.sender_facts_text()}\n\n"
        f"## Triage decisions already made (last {MAIL_WINDOW_DAYS} days, newest first)\n"
        + ("\n".join(lines) or "(none yet)")
    )


def recall(state: BriefingState) -> dict:
    """Read long-term memory and measure the counts once, before the loop starts; nothing here reaches the model."""
    mailbox = gmail_tools._mailbox()
    counts = {
        "threads": mailbox.count_threads(f"in:inbox newer_than:{MAIL_WINDOW_DAYS}d"),
        "drafts": len(mailbox.list_drafts()),
    }
    log.info("Report recall: %s", counts)
    return {
        "name": mailbox.profile_email(),
        "memory": _memory_text(),
        "counts": counts,
        "rounds": 0,
        "messages": [{"role": "user", "content": TASK}],
    }


def report(state: BriefingState) -> dict:
    """One model call. Tool calls are executed by the separate nodes below."""
    skill = SKILL.body.replace("{mail_days}", str(MAIL_WINDOW_DAYS))
    prompt = SystemMessage(SYSTEM_PROMPT.format(name=state["name"], skill=skill, memory=state["memory"]))
    message = _model().bind_tools(TOOLS).invoke([prompt, *state["messages"]])
    calls = message.tool_calls or []
    wants = "wants " + ", ".join(c["name"] for c in calls) if calls else "wrote the briefing"
    log.info("Report round %d: %s", state["rounds"] + 1, wants)
    return {"messages": [message], "rounds": state["rounds"] + 1}


def make_tool_node(tool):
    """A graph node that runs one tool, named after the tool it runs."""

    def run(state: BriefingState) -> dict:
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


def unknown_tool(state: BriefingState) -> dict:
    """Answer calls naming a tool that does not exist, rather than failing the run."""
    produced = []
    for call in getattr(state["messages"][-1], "tool_calls", None) or []:
        if call["name"] not in TOOLS_BY_NAME:
            content = f"No such tool: {call['name']}. Available: {', '.join(sorted(TOOLS_BY_NAME))}"
            produced.append(ToolMessage(content=content, tool_call_id=call["id"], name="unknown_tool"))
    return {"messages": produced}


def _call_key(call: dict) -> tuple[str, str]:
    return call["name"], json.dumps(call.get("args", {}), sort_keys=True)


def repeat(state: BriefingState) -> dict:
    """Answer tool calls identical to earlier ones without running them again; small models loop otherwise."""
    produced = []
    for call in getattr(state["messages"][-1], "tool_calls", None) or []:
        content = (
            f"{call['name']} was already called with these arguments; its result is above and has not changed. "
            "Open a thread with get_thread, or write the briefing now."
        )
        produced.append(ToolMessage(content=content, tool_call_id=call["id"], name=call["name"]))
    return {"messages": produced}


def insist(state: BriefingState) -> dict:
    """Push back, once, on a briefing written from snippets alone."""
    log.info("Report written without get_thread; sent back to open threads")
    return {"messages": [{"role": "user", "content": INSIST}]}


def route(state: BriefingState):
    """Send each tool call to its own node, insist once if no thread was opened, or finish."""
    calls = getattr(state["messages"][-1], "tool_calls", None) or []
    if calls and state["rounds"] < MAX_ROUNDS:
        earlier = {_call_key(c) for m in state["messages"][:-1] for c in (getattr(m, "tool_calls", None) or [])}
        if all(_call_key(c) in earlier for c in calls):
            return REPEAT
        return list(dict.fromkeys(node_name(c["name"]) if c["name"] in TOOLS_BY_NAME else UNKNOWN_TOOL for c in calls))
    ran = {m.name for m in state["messages"] if isinstance(m, ToolMessage)}
    insisted = any(getattr(m, "type", "") == "human" and m.content == INSIST for m in state["messages"])
    if "get_thread" not in ran and not insisted and state["rounds"] < MAX_ROUNDS:
        return "insist"
    return END


_graph = StateGraph(BriefingState)
_graph.add_node("recall", recall)
_graph.add_node(NAME, report)
_graph.add_node("insist", insist)
_graph.add_node(UNKNOWN_TOOL, unknown_tool)
_graph.add_node(REPEAT, repeat)
for _tool in TOOLS:
    _graph.add_node(node_name(_tool.name), make_tool_node(_tool))
    _graph.add_edge(node_name(_tool.name), NAME)
_graph.add_edge(START, "recall")
_graph.add_edge("recall", NAME)
_graph.add_edge(UNKNOWN_TOOL, NAME)
_graph.add_edge(REPEAT, NAME)
_graph.add_edge("insist", NAME)
_graph.add_conditional_edges(NAME, route, [*(node_name(t.name) for t in TOOLS), UNKNOWN_TOOL, REPEAT, "insist", END])


@cache
def inbox_report_agent():
    """Compiled once, with no checkpointer: a briefing is one short run that never suspends."""
    return _graph.compile()


def _looks_like_prose(text: str) -> bool:
    return bool(text.strip()) and "```" not in text and not text.lstrip().startswith(("[", "{"))


def _last_written(messages: list) -> str:
    written = (
        m.content.strip()
        for m in reversed(messages)
        if getattr(m, "type", "") == "ai" and isinstance(m.content, str) and m.content.strip()
    )
    return next(written, "")


def generate() -> dict:
    """Run the agent, cache the briefing it wrote to REPORT_FILE, and return it."""
    final = inbox_report_agent().invoke({"messages": []}, config={"recursion_limit": 4 + MAX_ROUNDS * 3})
    briefing = _last_written(final["messages"])
    if not _looks_like_prose(briefing):
        # Small models echo tool JSON, or hit the round cap mid-call: one more call, with no tools, writes the prose.
        log.info("Report was not prose; asking for a rewrite")
        skill = SKILL.body.replace("{mail_days}", str(MAIL_WINDOW_DAYS))
        prompt = SystemMessage(SYSTEM_PROMPT.format(name=final["name"], skill=skill, memory=final["memory"]))
        briefing = str(_model().invoke([prompt, *final["messages"], HumanMessage(REWRITE)]).content).strip()
    if (first := briefing.find("**")) > 0:
        briefing = briefing[first:]  # drop any title or "let me write" preamble before the first section
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "counts": final["counts"],
        "rounds": final["rounds"],
        "tool_calls": sum(1 for m in final["messages"] if isinstance(m, ToolMessage)),
        "briefing": briefing,
    }
    REPORT_FILE.write_text(json.dumps(report, indent=2))
    return report


def load_cached() -> dict | None:
    """The last briefing, or None if one has never been generated."""
    return json.loads(REPORT_FILE.read_text()) if REPORT_FILE.exists() else None
