"""Tests for aptgent.domain.text_utils — clean_text."""
from __future__ import annotations

from aptgent.domain.text_utils import clean_text


def test_clean_text_normal():
    assert clean_text("  hello   world  ") == "hello world"


def test_clean_text_single_word():
    assert clean_text("word") == "word"


def test_clean_text_empty_string():
    assert clean_text("") is None


def test_clean_text_whitespace_only():
    assert clean_text("   ") is None


def test_clean_text_none():
    assert clean_text(None) is None


def test_clean_text_non_string():
    assert clean_text(42) is None
    assert clean_text([]) is None
    assert clean_text({}) is None


def test_clean_text_tabs_and_newlines():
    assert clean_text("hello\t\nworld") == "hello world"


def test_clean_text_preserves_internal_single_spaces():
    assert clean_text("a b c") == "a b c"
