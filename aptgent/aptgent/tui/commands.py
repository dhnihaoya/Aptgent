from __future__ import annotations

from dataclasses import dataclass

from aptgent.domain.enums import Step


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
        label="Tokyo Night",
        theme_name="tokyo-night",
        description="Deep blue-black panels with higher contrast accents.",
    ),
    ThemePreset(
        label="Gruvbox",
        theme_name="gruvbox",
        description="Warmer earthy contrast with muted amber highlights.",
    ),
    ThemePreset(
        label="Rose Pine Dawn",
        theme_name="rose-pine-dawn",
        description="Soft light mode with muted borders and less glare.",
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
