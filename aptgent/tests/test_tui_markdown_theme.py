from __future__ import annotations

from rich.color import Color
from rich.console import Console

from aptgent.tui.rich_theme import build_chat_markdown_theme


def test_chat_markdown_theme_does_not_force_inline_code_background():
    console = Console()

    console.push_theme(build_chat_markdown_theme("#376FA8"))

    code_style = console.get_style("markdown.code")
    assert code_style.bgcolor is None
    assert code_style.color == Color.parse("#376FA8")
