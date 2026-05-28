from __future__ import annotations

import logging

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.message import Message
from textual.widgets import Button, OptionList, Static
from textual.widgets.option_list import Option

from aptgent.domain.enums import Step

_log = logging.getLogger(__name__)


class StructuredInputSubmitted(Message):
    """Posted by structured input panels when the user submits."""

    def __init__(self, step: Step, data: dict) -> None:
        super().__init__()
        self.step = step
        self.data = data


class StructuredActionRequested(Message):
    """Posted by structured input panels for button or option actions."""

    def __init__(self, step: Step, action: str) -> None:
        super().__init__()
        self.step = step
        self.action = action


class _BaseStructuredPanel(Vertical):
    """Shared chrome for structured input panels.

    Each panel subclass inherits this base to avoid repeating the surface/
    border/padding block and the common ``.panel-title`` / ``.panel-help``
    typography.
    """

    DEFAULT_CSS = """
    _BaseStructuredPanel {
        background: $surface-darken-2;
        border: round $primary;
        padding: 1 2;
        margin: 1 0;
        width: 95%;
        height: auto;
    }
    _BaseStructuredPanel > .panel-title {
        text-style: bold;
        margin-bottom: 1;
    }
    _BaseStructuredPanel > .panel-help {
        color: $text-muted;
        margin-bottom: 1;
    }
    """


class ActionMenuPanel(_BaseStructuredPanel):
    """Keyboard-first action chooser for a workflow step."""

    DEFAULT_CSS = """
    ActionMenuPanel > OptionList {
        height: auto;
        max-height: 10;
        border: tall $surface-lighten-1;
    }
    ActionMenuPanel.expanded-menu > OptionList {
        max-height: 22;
    }
    """

    def __init__(
        self,
        step: Step,
        title: str,
        choices: list[tuple[str, str, str]],
        *,
        help_text: str = "Use Up/Down to choose and Enter to confirm.",
        expanded: bool = False,
        **kwargs,
    ) -> None:
        if expanded:
            classes = kwargs.get("classes")
            kwargs["classes"] = (
                f"{classes} expanded-menu" if classes else "expanded-menu"
            )
        super().__init__(**kwargs)
        self.step = step
        self.title = title
        self.choices = choices
        self.help_text = help_text

    def compose(self) -> ComposeResult:
        yield Static(self.title, classes="panel-title")
        yield Static(self.help_text, classes="panel-help")
        options = [
            Option(
                f"[bold]{label}[/bold]\n[dim]{description}[/dim]",
                id=action,
            )
            for action, label, description in self.choices
        ]
        yield OptionList(*options, id="action-menu")

    def on_mount(self) -> None:
        try:
            self.query_one("#action-menu", OptionList).focus()
        except NoMatches:
            _log.debug("Focus target missing during on_mount", exc_info=True)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        option_id = event.option.id
        if option_id:
            self.post_message(StructuredActionRequested(self.step, option_id))
