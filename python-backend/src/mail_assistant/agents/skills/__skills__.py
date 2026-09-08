"""Skills: markdown instruction files, one directory per skill holding a SKILL.md, read into system prompts."""

from dataclasses import dataclass
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True, slots=True)
class Skill:
    """One skill: its frontmatter description and the markdown body that goes into a prompt."""

    name: str
    description: str
    body: str


def load(name: str) -> Skill:
    """Read `<name>/SKILL.md` from this directory, splitting off the `---` frontmatter."""
    text = (SKILLS_DIR / name / "SKILL.md").read_text()
    description = ""
    if text.startswith("---"):
        frontmatter, _, text = text[3:].partition("---")
        for line in frontmatter.splitlines():
            key, sep, value = line.partition(":")
            if sep and key.strip() == "description":
                description = value.strip()
    return Skill(name=name, description=description, body=text.strip())
