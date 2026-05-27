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


def load_config(config_dir: Path | None = None) -> AppConfigBundle:
    base_dir = config_dir or CONFIG_DIR
    raw_workflow = _load_toml(base_dir / "workflow.toml")
    raw_tools = _load_toml(base_dir / "tools.toml")
    raw_llm = _load_toml(base_dir / "llm.toml")
    return AppConfigBundle(
        workflow=_expand_config(raw_workflow),
        tools=_expand_config(raw_tools),
        llm=_expand_config(raw_llm),
    )
