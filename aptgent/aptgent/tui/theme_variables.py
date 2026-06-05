"""Single source of truth for chat theme variable defaults.

Both :mod:`aptgent.tui.app` (which merges these into every Textual theme) and
:mod:`aptgent.tui.widgets.chat_widgets` (which uses them as a last-resort
fallback when theme lookup fails) import this dict, so the palette only needs
to be maintained in one place. This module intentionally has no imports to
avoid any circular-dependency risk.
"""
from __future__ import annotations

THEME_VARIABLE_DEFAULTS: dict[str, str] = {
    "button-color-foreground": "#071018",
    "input-selection-background": "#5D95D633",
    "chat-system-background": "#121922",
    "chat-system-foreground": "#DFE7F0",
    "chat-system-accent": "#5D95D6",
    "chat-stream-background": "#18212C",
    "chat-stream-foreground": "#E6EDF7",
    "chat-stream-accent": "#78B7F2",
    "chat-tool-background": "#10161E",
    "chat-tool-foreground": "#AFBDCD",
    "chat-tool-accent": "#4F667F",
    "chat-user-background": "#102238",
    "chat-user-foreground": "#EEF4FB",
    "chat-user-accent": "#78B7F2",
    "chat-thinking-background": "#10161E",
    "chat-thinking-foreground": "#AEBBCB",
    "chat-thinking-accent": "#D3A751",
    "chat-thinking-label": "#A9BAD1",
    "chat-thinking-frame-muted": "#718198",
    "chat-thinking-frame-soft": "#9BAABD",
    "chat-thinking-frame-bright": "#D7E2EE",
    "chat-thinking-frame-hot": "#F1C15B",
    "chat-activity-background": "#111821",
    "chat-activity-foreground": "#D5DEE9",
    "chat-activity-accent": "#F1C15B",
    "chat-activity-label": "#A9BAD1",
    "chat-activity-frame-muted": "#5F6B7A",
    "chat-activity-frame-soft": "#8795A7",
    "chat-activity-frame-bright": "#D7DEEA",
    "chat-activity-frame-hot": "#F1C15B",
    "chat-activity-final-icon": "#F1C15B",
    "chat-progress-background": "#0D131B",
    "chat-progress-foreground": "#9AACBF",
    "chat-progress-border": "#254A72",
    "chat-status-background": "#10161D",
    "chat-status-foreground": "#8B9EB0",
    "chat-status-border": "#1A314A",
    "chat-divider-color": "#84BCF3",
    "chat-markdown-code": "#8EC5FF",
}
