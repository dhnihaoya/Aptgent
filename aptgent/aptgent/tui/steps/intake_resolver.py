"""Target molecule resolution helper for the intake step.

Isolated so the intake handler stays small and so the translation
fallback can be tested without the Textual screen surface.
"""
from __future__ import annotations

from typing import Any, Callable

from aptgent.domain.models import TargetMolecule
from aptgent.tui.steps.common import clean_text

MoleculeResolver = Any  # duck-typed; exposes ``resolve(text) -> TargetMolecule``


def _contains_chinese(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _translate_molecule_name(text: str, skill_factory: Callable[[], Any]) -> str | None:
    """Best-effort translate a Chinese molecule name to English.

    Swallows any skill/LLM error and returns ``None`` so callers can
    fall back to the unresolved state.
    """
    translate_prompt = (
        "Translate the following molecule name to its standard English common name. "
        'Return ONLY a JSON object: {"english_name": "<english name>"}.'
    )
    try:
        translated = skill_factory().client.chat_json(translate_prompt, text)
    except Exception:
        return None

    if isinstance(translated, dict):
        english_name = clean_text(
            translated.get("english_name")
            or translated.get("name")
            or translated.get("translation")
        )
        if english_name is None and translated:
            english_name = clean_text(next(iter(translated.values())))
        return english_name
    if isinstance(translated, str):
        return clean_text(translated)
    return None


def resolve_target_text(
    target_text: str,
    *,
    molecule_resolver: MoleculeResolver,
    intake_skill_factory: Callable[[], Any],
) -> tuple[str, TargetMolecule | None]:
    """Resolve ``target_text`` to a :class:`TargetMolecule`.

    Returns ``(effective_text, resolved)`` where ``effective_text`` is
    the string that produced the successful resolution (possibly a
    translation) and ``resolved`` is ``None`` when resolution failed.

    When resolution fails, the last failed ``TargetMolecule`` is still
    returned (with ``resolution_status="failed"``) so callers can
    inspect ``error_detail`` for a tailored message.
    """
    resolved = molecule_resolver.resolve(target_text)
    if resolved.resolution_status == "resolved":
        return target_text, resolved

    last_failed = resolved

    if _contains_chinese(target_text):
        english_name = _translate_molecule_name(target_text, intake_skill_factory)
        if english_name:
            resolved = molecule_resolver.resolve(english_name)
            if resolved.resolution_status == "resolved":
                return english_name, resolved
            last_failed = resolved

    return target_text, last_failed
