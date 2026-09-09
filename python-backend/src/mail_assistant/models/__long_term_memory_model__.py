from dataclasses import dataclass


@dataclass(slots=True)
class LongTermMemory:
    """Everything remembered across runs: learned preferences as plain prose, one rule per line."""

    learned_preferences: str = ""  # rules the person added or changed through chat
