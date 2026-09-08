from dataclasses import dataclass, field

from mail_assistant.models.__sender_preference_model__ import SenderPreference


@dataclass(slots=True)
class LongTermMemory:
    """Everything remembered across runs: learned preferences as plain prose, plus what was decided per sender."""

    learned_preferences: str = ""  # rules the person added or changed through chat, one per line
    senders: dict[str, SenderPreference] = field(default_factory=dict)  # keyed by lowercased email address
