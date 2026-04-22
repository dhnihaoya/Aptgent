from __future__ import annotations

from rich.theme import Theme as RichTheme


def build_chat_markdown_theme(code_color: str) -> RichTheme:
    """Return Rich styles used by Markdown renderables inside chat bubbles."""
    return RichTheme({"markdown.code": f"bold {code_color}"})

