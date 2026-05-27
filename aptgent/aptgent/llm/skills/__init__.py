"""Directory-style LLM skills.

Each skill lives in its own subpackage with ``SKILL.md`` + ``system.md``
+ ``schema.py`` + ``skill.py``. The default :data:`registry` holds every
built-in skill so the TUI (or a ``/skills`` slash command) can enumerate
them along with their trust level.

All legacy class names from the previous ``skills.py`` single-file module
are re-exported here, so callers (``tui/steps/*``, ``tui/app.py``,
existing tests) keep working unchanged.
"""

from __future__ import annotations

from aptgent.llm.skills.analog_parse import (
    AnalogParseInput,
    AnalogParseOutput,
    AnalogParseSkill,
)
from aptgent.llm.skills.analog_suggestion import (
    AnalogEntry,
    AnalogSuggestionInput,
    AnalogSuggestionOutput,
    AnalogSuggestionSkill,
)
from aptgent.llm.skills.base import (
    BaseSkill,
    SkillMetadata,
    SkillRegistry,
    SkillResult,
    load_prompt,
    load_skill_metadata,
)
from aptgent.llm.skills.docking_params_parse import (
    DockingParamsParseInput,
    DockingParamsParseOutput,
    DockingParamsParseSkill,
)
from aptgent.llm.skills.docking_planner import (
    DockingPlannerInput,
    DockingPlannerOutput,
    DockingPlannerSkill,
)
from aptgent.llm.skills.intake import IntakeInput, IntakeOutput, IntakeSkill
from aptgent.llm.skills.pdb_review import (
    PdbReviewInput,
    PdbReviewOutput,
    PdbReviewSkill,
)
from aptgent.llm.skills.report import ReportInput, ReportOutput, ReportSkill
from aptgent.llm.skills.site_proposal import (
    SiteProposalInput,
    SiteProposalOutput,
    SiteProposalSkill,
    SiteRegionAssessment,
)

registry = SkillRegistry()
registry.register(IntakeSkill)
registry.register(PdbReviewSkill)
registry.register(SiteProposalSkill)
registry.register(AnalogSuggestionSkill)
registry.register(AnalogParseSkill)
registry.register(DockingPlannerSkill)
registry.register(DockingParamsParseSkill)
registry.register(ReportSkill)


def get_registry() -> SkillRegistry:
    """Return the default skill registry."""
    return registry


__all__ = [
    "AnalogParseInput",
    "AnalogParseOutput",
    "AnalogParseSkill",
    "AnalogEntry",
    "AnalogSuggestionInput",
    "AnalogSuggestionOutput",
    "AnalogSuggestionSkill",
    "BaseSkill",
    "DockingParamsParseInput",
    "DockingParamsParseOutput",
    "DockingParamsParseSkill",
    "DockingPlannerInput",
    "DockingPlannerOutput",
    "DockingPlannerSkill",
    "IntakeInput",
    "IntakeOutput",
    "IntakeSkill",
    "PdbReviewInput",
    "PdbReviewOutput",
    "PdbReviewSkill",
    "ReportInput",
    "ReportOutput",
    "ReportSkill",
    "SiteProposalInput",
    "SiteProposalOutput",
    "SiteRegionAssessment",
    "SiteProposalSkill",
    "SkillMetadata",
    "SkillRegistry",
    "SkillResult",
    "get_registry",
    "load_prompt",
    "load_skill_metadata",
    "registry",
]
