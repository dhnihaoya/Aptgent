from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from aptgent.domain.enums import Step

SlashHandler = Callable[[Any, str], bool]
"""Signature: ``handler(screen, argument)`` -> ``True`` if handled."""


@dataclass(frozen=True)
class SlashCommand:
    name: str
    description: str


@dataclass(frozen=True)
class ThemePreset:
    label: str
    theme_name: str
    description: str


RESUME_COMMAND = SlashCommand(
    name="/resume",
    description="Resume a saved workflow",
)

QUIT_COMMAND = SlashCommand(
    name="/quit",
    description="Open the quit confirmation dialog",
)

EXPORT_COMMAND = SlashCommand(
    name="/export",
    description="Export the final report JSON",
)

FINISH_COMMAND = SlashCommand(
    name="/finish",
    description="Mark the workflow complete and exit",
)

THEME_COMMAND = SlashCommand(
    name="/theme",
    description="Choose from the available UI themes",
)

THEME_PRESETS = (
    ThemePreset(
        label="Clear Lanes",
        theme_name="clear-lanes",
        description="Serious dark theme with strong left and right chat separation.",
    ),
    ThemePreset(
        label="Clean Minimal Light",
        theme_name="clean-minimal-light",
        description="Bright low-noise light theme tuned for long sessions.",
    ),
    ThemePreset(
        label="Warm Industrial",
        theme_name="warm-industrial",
        description="Warm instrument-like dark theme with amber and teal accents.",
    ),
)

DEFAULT_SLASH_COMMANDS = (
    RESUME_COMMAND,
    QUIT_COMMAND,
    THEME_COMMAND,
)


def commands_for_step(step: Step | None) -> tuple[SlashCommand, ...]:
    commands = [RESUME_COMMAND, QUIT_COMMAND]
    if step == Step.FINAL_REPORT:
        commands.extend((EXPORT_COMMAND, FINISH_COMMAND))
    commands.append(THEME_COMMAND)
    return tuple(commands)


def get_theme_preset(theme_name: str) -> ThemePreset | None:
    for preset in THEME_PRESETS:
        if preset.theme_name == theme_name:
            return preset
    return None


class SlashCommandRegistry:
    """Central dispatcher for chat ``/commands``.

    Keeps command wiring out of :class:`ChatScreen` so new commands can
    be added by registering a handler rather than editing a large
    if/elif chain. Handlers return ``True`` when they fully handled the
    input; otherwise the caller treats the text as a regular message.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, SlashHandler] = {}

    def register(self, name: str, handler: SlashHandler) -> None:
        if not name.startswith("/"):
            raise ValueError(f"Slash command must start with '/': {name!r}")
        self._handlers[name] = handler

    def dispatch(self, screen: Any, raw_text: str) -> bool | None:
        """Dispatch ``raw_text`` on behalf of ``screen``.

        Returns:
            - ``True`` if a handler consumed the input.
            - ``False`` if ``raw_text`` looks like an unknown slash
              command (caller should render an error).
            - ``None`` if ``raw_text`` is not a slash command.
        """
        if not raw_text.startswith("/"):
            return None
        command, _, argument = raw_text.partition(" ")
        handler = self._handlers.get(command)
        if handler is None:
            return False
        return bool(handler(screen, argument))
