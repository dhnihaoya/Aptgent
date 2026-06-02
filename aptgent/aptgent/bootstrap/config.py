from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomli

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"

# Matches ${VAR} or ${VAR:-default}
_ENV_PATTERN = re.compile(r"\$\{([^}]+)\}")


def expand_env(value: str) -> str:
    """Expand ``${VAR}`` and ``${VAR:-default}`` placeholders in *value*.

    Also expands ``~`` to the user's home directory.
    """

    def _replace(match: re.Match[str]) -> str:
        inner = match.group(1)
        if ":-" in inner:
            var, default = inner.split(":-", 1)
            return os.environ.get(var) or default
        return os.environ.get(inner, match.group(0))

    expanded = _ENV_PATTERN.sub(_replace, value)
    return os.path.expanduser(expanded)


def _expand_config(config: dict[str, Any]) -> dict[str, Any]:
    """Recursively expand env-var placeholders in string values."""
    result: dict[str, Any] = {}
    for key, val in config.items():
        if isinstance(val, str):
            result[key] = expand_env(val)
        elif isinstance(val, dict):
            result[key] = _expand_config(val)
        elif isinstance(val, list):
            result[key] = [
                expand_env(v) if isinstance(v, str) else v for v in val
            ]
        else:
            result[key] = val
    return result


@dataclass(frozen=True)
class AppConfigBundle:
    workflow: dict[str, Any]
    tools: dict[str, Any]
    llm: dict[str, Any]


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        return tomli.load(handle)


def _apply_local_overrides(raw_llm: dict[str, Any], base_dir: Path) -> dict[str, Any]:
    """Merge ``aptgent.local.toml`` (project root) into the bundled LLM config.

    The user's local file lives at the project root, three levels above the
    bundled ``config`` directory. Without this merge the ``api_key`` set in
    ``aptgent.local.toml`` never reaches the LLM client built via
    :func:`load_config`, producing an empty ``Bearer`` auth header.
    """
    project_root = base_dir.parent.parent.parent
    local = project_root / "aptgent.local.toml"
    if not local.is_file():
        return raw_llm
    local_data = _load_toml(local)
    overrides = local_data.get("provider", {}).get("openai", {})
    if not overrides:
        return raw_llm
    merged = dict(raw_llm)
    provider = dict(merged.get("provider", {}))
    openai = dict(provider.get("openai", {}))
    openai.update(overrides)
    provider["openai"] = openai
    merged["provider"] = provider
    return merged


def load_config(config_dir: Path | None = None) -> AppConfigBundle:
    base_dir = config_dir or CONFIG_DIR
    raw_workflow = _load_toml(base_dir / "workflow.toml")
    raw_tools = _load_toml(base_dir / "tools.toml")
    raw_llm = _apply_local_overrides(_load_toml(base_dir / "llm.toml"), base_dir)
    return AppConfigBundle(
        workflow=_expand_config(raw_workflow),
        tools=_expand_config(raw_tools),
        llm=_expand_config(raw_llm),
    )
