"""Regression tests for the directory-style LLM skill system."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from aptgent.llm.skills import (
    AnalogParseSkill,
    AnalogSuggestionSkill,
    BaseSkill,
    DockingParamsParseOutput,
    DockingParamsParseSkill,
    DockingPlannerSkill,
    IntakeSkill,
    PdbReviewSkill,
    ReportSkill,
    SiteProposalSkill,
    SkillMetadata,
    SkillRegistry,
    SkillResult,
    get_registry,
)
from aptgent.llm.skills.base import _parse_frontmatter


# Every built-in skill registered in the default registry.
ALL_SKILL_CLASSES = [
    IntakeSkill,
    PdbReviewSkill,
    SiteProposalSkill,
    AnalogSuggestionSkill,
    AnalogParseSkill,
    DockingPlannerSkill,
    DockingParamsParseSkill,
    ReportSkill,
]


@pytest.mark.parametrize("skill_cls", ALL_SKILL_CLASSES)
def test_skill_has_bound_metadata_and_prompt(skill_cls):
    metadata = skill_cls.metadata
    assert isinstance(metadata, SkillMetadata)
    assert metadata.id
    assert metadata.trust_level in {"nlu_only", "advisory", "deterministic_wrapper"}
    assert skill_cls.system_prompt
    if skill_cls.output_schema is not None:
        assert issubclass(skill_cls.output_schema, BaseModel)


def test_registry_contains_every_builtin_skill():
    registry = get_registry()
    registered_ids = {cls.metadata.id for cls in registry.all()}
    expected_ids = {cls.metadata.id for cls in ALL_SKILL_CLASSES}
    assert expected_ids.issubset(registered_ids)


def test_registry_rejects_non_skill_classes():
    registry = SkillRegistry()

    class NotASkill:
        pass

    with pytest.raises(TypeError):
        registry.register(NotASkill)  # type: ignore[arg-type]


def test_skill_metadata_rejects_invalid_trust_level():
    with pytest.raises(ValueError):
        SkillMetadata(
            id="bad",
            name="Bad",
            description="",
            when_to_use="",
            version="0.0.0",
            trust_level="totally_trusted",
        )


def test_parse_frontmatter_round_trip():
    text = (
        "---\n"
        "id: demo\n"
        "name: Demo\n"
        "trust_level: advisory\n"
        "tags: [a, b, c]\n"
        "---\n"
        "body text\n"
    )
    data = _parse_frontmatter(text)
    assert data["id"] == "demo"
    assert data["trust_level"] == "advisory"
    assert data["tags"] == ["a", "b", "c"]


def test_parse_frontmatter_requires_closing_fence():
    with pytest.raises(ValueError):
        _parse_frontmatter("---\nid: demo\n")


class _StubClient:
    def __init__(self, response):
        self._response = response

    def chat_json(self, system_prompt: str, user_prompt: str):
        return self._response


class _Echo(BaseModel):
    value: str


class _EchoSkill(BaseSkill):
    metadata = SkillMetadata(
        id="test.echo",
        name="Echo",
        description="",
        when_to_use="",
        version="0.1.0",
        trust_level="advisory",
    )
    system_prompt = "system"
    output_schema = _Echo


def test_base_skill_invoke_validates_output_schema():
    skill = _EchoSkill(client=_StubClient({"value": "hi"}))
    result = skill.invoke("ignored")
    assert isinstance(result, SkillResult)
    assert result.model is not None
    assert result.model.value == "hi"  # type: ignore[attr-defined]


def test_base_skill_invoke_rejects_non_dict_response():
    skill = _EchoSkill(client=_StubClient("not a dict"))
    with pytest.raises(RuntimeError):
        skill.invoke("ignored")


def test_docking_params_parse_output_accepts_partial_payload():
    output = DockingParamsParseOutput.model_validate(
        {"top_k": 8, "exhaustiveness": 32, "seed": 42}
    )
    assert output.top_k == 8
    assert output.exhaustiveness == 32
    assert output.seed == 42
    assert output.num_modes is None
    assert output.action is None


def test_docking_params_parse_output_accepts_action_only():
    output = DockingParamsParseOutput.model_validate({"action": "use_defaults"})
    assert output.action == "use_defaults"
    assert output.top_k is None


def test_docking_params_parse_output_rejects_bad_action():
    with pytest.raises(Exception):
        DockingParamsParseOutput.model_validate({"action": "yolo"})


def test_docking_params_parse_skill_metadata_is_nlu_only():
    assert DockingParamsParseSkill.metadata.trust_level == "nlu_only"
    assert DockingParamsParseSkill.metadata.id == "docking_params_parse"
