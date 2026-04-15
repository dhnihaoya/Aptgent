from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomli

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


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
    return AppConfigBundle(
        workflow=_load_toml(base_dir / "workflow.toml"),
        tools=_load_toml(base_dir / "tools.toml"),
        llm=_load_toml(base_dir / "llm.toml"),
    )
