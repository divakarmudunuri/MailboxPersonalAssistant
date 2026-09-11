"""Long-term memory: base rules fixed in code, plus a JSON file of learned preferences."""

import json
from email.utils import parseaddr

from mail_assistant.config.__app_config__ import MEMORY_FILE
from mail_assistant.models.__long_term_memory_model__ import LongTermMemory

# The baseline the person started from: named rules, always in the prompt. Base rules only ever decide `ignore` or
# `notify`; replies (auto_schedule, auto_draft) happen only when a learned rule from chat asks for them. Chat can
# only add learned rules on top, and a learned rule wins when the two conflict.
LONG_TERM_MEMORY: list[tuple[str, str, str]] = [  # (rule name, what it covers, outcome)
    ("marketing_promotions", "Marketing newsletters and promotional emails", "ignore"),
    ("spam_suspicious", "Spam or suspicious emails", "ignore"),
    ("cc_fyi_threads", "CC'd on FYI threads with no direct questions", "ignore"),
    ("social_updates", "Social-network notifications and activity digests (LinkedIn, Nextdoor, ...)", "ignore"),
    ("forum_digests", "Mailing-list and forum digests with nothing addressed to the person", "ignore"),
    ("teammate_out", "Team member out sick or on vacation", "notify"),
    ("build_notifications", "Build system notifications or deployments", "notify"),
    ("status_updates", "Project status updates without action items", "notify"),
    ("company_announcements", "Important company announcements", "notify"),
    ("fyi_project_info", "FYI emails that contain relevant information for current projects", "notify"),
    ("hr_deadlines", "HR Department deadline reminders", "notify"),
    ("subscription_renewals", "Subscription status / renewal reminders", "notify"),
    ("bank_notices", "Bank and card statements, transaction alerts, and account notices; never spam", "notify"),
    ("github_notifications", "GitHub notifications", "notify"),
    ("team_questions", "Direct questions from team members requiring expertise", "notify"),
    ("meeting_requests", "Meeting requests requiring confirmation", "notify"),
    ("critical_bugs", "Critical bug reports related to team's projects", "notify"),
    ("management_requests", "Requests from management requiring acknowledgment", "notify"),
    ("client_inquiries", "Client inquiries about project status or features", "notify"),
    (
        "technical_questions",
        "Technical questions about documentation, code, or APIs (especially about missing endpoints or features)",
        "notify",
    ),
    ("family_reminders", "Personal reminders related to family (wife / daughter)", "notify"),
    ("self_care_reminders", "Personal reminders related to self-care (doctor appointments, etc)", "notify"),
]


def base_rules_text() -> str:
    """The base rules as prompt lines: `- name: what it covers -> outcome`."""
    return "\n".join(f"- {name}: {text} -> {outcome}" for name, text, outcome in LONG_TERM_MEMORY)


def address(sender: str) -> str:
    """'Sam Lee <Sam@Example.com>' -> 'sam@example.com'."""
    return (parseaddr(sender)[1] or sender).strip().lower()


def load() -> LongTermMemory:
    """Read the memory file; an absent file is an empty memory."""
    if not MEMORY_FILE.exists():
        return LongTermMemory()
    return LongTermMemory(learned_preferences=json.loads(MEMORY_FILE.read_text()).get("learned_preferences", ""))


def _dump(memory: LongTermMemory) -> None:
    MEMORY_FILE.write_text(json.dumps({"learned_preferences": memory.learned_preferences}, indent=2))


def preferences_text() -> str:
    """Base rules plus learned preferences, as the block the triage prompt shows the model."""
    learned = load().learned_preferences.strip() or "(none yet)"
    return (
        f"## Base rules (name: what it covers -> outcome)\n{base_rules_text()}\n\n"
        f"## Learned rules (name: rule; these win over base rules)\n{learned}"
    )


def learned_rules() -> dict[str, str]:
    """Learned rules as {name: rule text}, parsed from their `- name: rule` lines."""
    lines = load().learned_preferences.splitlines()
    pairs = (line[2:].split(":", 1) for line in lines if line.startswith("- ") and ":" in line)
    return {name.strip(): text.strip() for name, text in pairs}


def update_preferences(text: str) -> LongTermMemory:
    """Replace the learned preferences prose."""
    memory = load()
    memory.learned_preferences = text.strip()
    _dump(memory)
    return memory
