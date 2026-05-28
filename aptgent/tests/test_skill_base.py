"""Tests for BaseSkill streaming validation."""
from __future__ import annotations

from typing import Any, ClassVar
from unittest.mock import MagicMock

from pydantic import BaseModel

from aptgent.llm.skills.base import BaseSkill, SkillMetadata


class _DummyOutput(BaseModel):
    name: str
    count: int


class _DummySkill(BaseSkill):
    metadata = SkillMetadata(
        id="test", name="Test", description="", when_to_use="",
        version="0.0.1", trust_level="advisory",
    )
    system_prompt = "sys"
    output_schema = _DummyOutput


def _make_client(events: list[dict[str, Any]]) -> MagicMock:
    client = MagicMock()
    client.chat_json_events.return_value = iter(events)
    return client


def test_validated_event_after_result():
    """On valid JSON, yield result then validated."""
    skill = _DummySkill()
    skill.client = _make_client([
        {"type": "content", "text": '{"name": "foo", "count": 3}'},
        {"type": "result", "value": {"name": "foo", "count": 3}},
    ])
    events = list(skill.invoke_json_events("payload"))
    types = [e["type"] for e in events]
    assert "result" in types
    assert "validated" in types
    validated = next(e for e in events if e["type"] == "validated")
    assert isinstance(validated["value"], _DummyOutput)
    assert validated["value"].name == "foo"


def test_no_schema_yields_raw_result():
    """Without output_schema, result passes through unchanged."""

    class _NoSchemaSkill(BaseSkill):
        metadata = SkillMetadata(
            id="noschema", name="NoSchema", description="", when_to_use="",
            version="0.0.1", trust_level="advisory",
        )
        system_prompt = "sys"
        output_schema = None

    skill = _NoSchemaSkill()
    skill.client = _make_client([
        {"type": "result", "value": {"anything": "goes"}},
    ])
    events = list(skill.invoke_json_events("payload"))
    types = [e["type"] for e in events]
    assert types == ["result"]
    assert "validated" not in types


def test_invalid_schema_does_not_yield_result():
    """If model_validate fails, result is NOT yielded — prevents leaking unvalidated data."""
    skill = _DummySkill()
    skill.client = _make_client([
        {"type": "result", "value": {"wrong_field": 1}},
    ])
    events: list[dict] = []
    raised = False
    try:
        for e in skill.invoke_json_events("payload"):
            events.append(e)
    except Exception:
        raised = True
    # Result must NOT have been yielded
    assert not any(e["type"] == "result" for e in events)
    assert not any(e["type"] == "validated" for e in events)
    assert raised
