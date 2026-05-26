"""Shared text normalization helpers."""

from __future__ import annotations

from typing import Any


def clean_text(value: Any) -> str | None:
    """Strip and collapse internal whitespace; return None for empty/non-string."""
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    return value or None
