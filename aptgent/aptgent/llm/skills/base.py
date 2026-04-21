"""Base classes for directory-style LLM skills.

Each skill lives in its own subpackage under ``aptgent.llm.skills`` with the
following layout::

    <skill_name>/
        SKILL.md       # YAML frontmatter + prose description
        system.md      # system prompt for JSON-mode calls
        display.md     # optional: system prompt for streamed explanations
        schema.py      # pydantic InputModel / OutputModel
        skill.py       # subclass of BaseSkill
        __init__.py    # re-export the skill class

``BaseSkill`` wires those artifacts together and exposes a small, stable
interface (``invoke`` / ``invoke_stream`` / ``explain_stream``) that the
workflow layer can call. The LLM is treated as an advisor only — the
``trust_level`` metadata surfaces the contract explicitly.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Generator, Iterable, Mapping

from pydantic import BaseModel

from aptgent.llm.client import LLMClient


@dataclass(frozen=True)
class SkillMetadata:
    """Structured metadata for a skill, parsed from ``SKILL.md``."""

    id: str
    name: str
    description: str
    when_to_use: str
    version: str
    trust_level: str
    tags: tuple[str, ...] = field(default_factory=tuple)
    inputs: tuple[str, ...] = field(default_factory=tuple)
    outputs: tuple[str, ...] = field(default_factory=tuple)

    _VALID_TRUST_LEVELS: ClassVar[frozenset[str]] = frozenset(
        {"nlu_only", "advisory", "deterministic_wrapper"}
    )

    def __post_init__(self) -> None:
        if self.trust_level not in self._VALID_TRUST_LEVELS:
            raise ValueError(
                f"Skill {self.id!r}: invalid trust_level {self.trust_level!r}. "
                f"Expected one of {sorted(self._VALID_TRUST_LEVELS)}."
            )


def _parse_frontmatter(text: str) -> dict[str, Any]:
    """Parse simple ``key: value`` YAML frontmatter between ``---`` fences.

    This avoids a hard PyYAML dependency and only supports the flat schema the
    skill loader actually uses (strings plus one-line inline lists).
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("SKILL.md must start with '---' frontmatter fence.")
    end = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end = idx
            break
    if end is None:
        raise ValueError("SKILL.md frontmatter fence not closed.")

    data: dict[str, Any] = {}
    for raw in lines[1:end]:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if ":" not in raw:
            continue
        key, _, value = raw.partition(":")
        key = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            if not inner:
                data[key] = []
            else:
                data[key] = [
                    part.strip().strip('"').strip("'")
                    for part in inner.split(",")
                    if part.strip()
                ]
        else:
            if (value.startswith('"') and value.endswith('"')) or (
                value.startswith("'") and value.endswith("'")
            ):
                value = value[1:-1]
            data[key] = value
    return data


def load_skill_metadata(skill_dir: Path) -> SkillMetadata:
    md_path = skill_dir / "SKILL.md"
    text = md_path.read_text(encoding="utf-8")
    raw = _parse_frontmatter(text)
    tags = raw.get("tags") or []
    inputs = raw.get("inputs") or []
    outputs = raw.get("outputs") or []
    return SkillMetadata(
        id=str(raw["id"]),
        name=str(raw["name"]),
        description=str(raw.get("description", "")),
        when_to_use=str(raw.get("when_to_use", "")),
        version=str(raw.get("version", "0.0.0")),
        trust_level=str(raw.get("trust_level", "advisory")),
        tags=tuple(tags),
        inputs=tuple(inputs),
        outputs=tuple(outputs),
    )


def load_prompt(skill_dir: Path, name: str) -> str | None:
    path = skill_dir / name
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8").strip()


@dataclass(frozen=True)
class SkillResult:
    """Wrapper returned by :meth:`BaseSkill.invoke`."""

    raw: dict[str, Any]
    model: BaseModel | None = None

    def dict(self) -> dict[str, Any]:
        if self.model is not None:
            return self.model.model_dump()
        return dict(self.raw)


class BaseSkill:
    """Base class for directory-style skills.

    Subclasses should set the following class attributes (usually via the
    :meth:`_bind_directory` helper called from the subpackage ``__init__`` /
    ``skill.py``):

    * ``metadata``       -- parsed from ``SKILL.md``
    * ``system_prompt``  -- contents of ``system.md``
    * ``display_prompt`` -- contents of ``display.md`` (optional)
    * ``output_schema``  -- pydantic ``BaseModel`` class describing the
      JSON-mode response shape

    ``invoke()`` / ``invoke_stream()`` / ``explain_stream()`` provide the
    default behaviour; skills can override :meth:`build_user_message` to
    customise the user-prompt serialisation for their payload.
    """

    metadata: ClassVar[SkillMetadata]
    system_prompt: ClassVar[str]
    display_prompt: ClassVar[str | None] = None
    output_schema: ClassVar[type[BaseModel] | None] = None

    def __init__(self, client: LLMClient | None = None) -> None:
        self.client = client or LLMClient()

    @classmethod
    def _bind_directory(cls, skill_dir: Path) -> None:
        """Populate class-level prompts/metadata from a skill directory."""
        cls.metadata = load_skill_metadata(skill_dir)
        system = load_prompt(skill_dir, "system.md")
        if system is None:
            raise FileNotFoundError(
                f"Skill {cls.metadata.id!r} is missing required system.md"
            )
        cls.system_prompt = system
        cls.display_prompt = load_prompt(skill_dir, "display.md")

    def build_user_message(self, payload: Any) -> str:
        """Render ``payload`` as the user-visible message for the LLM.

        Strings pass through, pydantic models are JSON-dumped, dict-like
        mappings get JSON-serialised with indentation. Subclasses may
        override to add headers or schema reminders.
        """
        import json

        if payload is None:
            return ""
        if isinstance(payload, str):
            return payload
        if isinstance(payload, BaseModel):
            return payload.model_dump_json(indent=2)
        if isinstance(payload, Mapping):
            return json.dumps(dict(payload), indent=2, ensure_ascii=False)
        return str(payload)

    def invoke(self, payload: Any) -> SkillResult:
        user = self.build_user_message(payload)
        raw = self.client.chat_json(self.system_prompt, user)
        if not isinstance(raw, dict):
            raise RuntimeError(
                f"Skill {self.metadata.id!r} expected a JSON object response; "
                f"got {type(raw).__name__}."
            )
        model: BaseModel | None = None
        if self.output_schema is not None:
            model = self.output_schema.model_validate(raw)
        return SkillResult(raw=raw, model=model)

    def invoke_stream(self, payload: Any) -> Generator[str, None, None]:
        user = self.build_user_message(payload)
        yield from self.client.chat_stream(self.system_prompt, user)

    def explain_stream(self, payload: Any) -> Iterable[Any]:
        if self.display_prompt is None:
            raise RuntimeError(
                f"Skill {self.metadata.id!r} has no display prompt; "
                "explain_stream() is unavailable."
            )
        user = self.build_user_message(payload)
        return self.client.chat_text_stream(self.display_prompt, user)


class SkillRegistry:
    """Simple skill registry used for introspection (e.g. ``/skills`` UI)."""

    def __init__(self) -> None:
        self._skills: dict[str, type[BaseSkill]] = {}

    def register(self, skill_cls: type[BaseSkill]) -> type[BaseSkill]:
        if not inspect.isclass(skill_cls) or not issubclass(skill_cls, BaseSkill):
            raise TypeError("Only BaseSkill subclasses can be registered.")
        metadata = getattr(skill_cls, "metadata", None)
        if not isinstance(metadata, SkillMetadata):
            raise TypeError(
                f"{skill_cls.__name__} is missing bound SkillMetadata."
            )
        self._skills[metadata.id] = skill_cls
        return skill_cls

    def get(self, skill_id: str) -> type[BaseSkill] | None:
        return self._skills.get(skill_id)

    def all(self) -> list[type[BaseSkill]]:
        return list(self._skills.values())

    def metadata(self) -> list[SkillMetadata]:
        return [cls.metadata for cls in self._skills.values()]


__all__ = [
    "BaseSkill",
    "SkillMetadata",
    "SkillRegistry",
    "SkillResult",
    "load_prompt",
    "load_skill_metadata",
]
