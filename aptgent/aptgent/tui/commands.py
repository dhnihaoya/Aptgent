from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SlashCommand:
    name: str
    description: str


DEFAULT_SLASH_COMMANDS = (
    SlashCommand(
        name="/resume",
        description="Resume a saved workflow",
    ),
)
