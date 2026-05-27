"""Generate a reproducibility run card for each workflow run."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)


def _aptgent_version() -> str:
    try:
        return importlib.metadata.version("aptgent")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd=Path(__file__).resolve().parents[3],
        )
        if result.returncode == 0:
            return result.stdout.strip()[:12]
    except Exception:
        pass
    return None


def _model_hashes(model_dir: str | Path) -> dict[str, str]:
    p = Path(model_dir)
    if not p.is_dir():
        return {}
    hashes: dict[str, str] = {}
    for f in sorted(p.glob("*.pkl")):
        h = hashlib.sha256()
        with f.open("rb") as fh:
            for chunk in iter(lambda: fh.read(8192), b""):
                h.update(chunk)
        hashes[f.name] = h.hexdigest()[:16]
    return hashes


def _tool_version(executable: str) -> str | None:
    try:
        result = subprocess.run(
            [executable, "--version"],
            capture_output=True, text=True, timeout=10,
        )
        output = (result.stdout or result.stderr).strip()
        return output.split("\n")[0] if output else None
    except Exception:
        return None


def _compute_step_durations(step_timestamps: dict[str, str]) -> dict[str, float]:
    """Compute wall-clock seconds between consecutive step timestamps."""
    if not step_timestamps:
        return {}
    steps = sorted(step_timestamps.keys(), key=lambda k: step_timestamps[k])
    durations: dict[str, float] = {}
    for i in range(len(steps) - 1):
        try:
            t0 = datetime.fromisoformat(step_timestamps[steps[i]])
            t1 = datetime.fromisoformat(step_timestamps[steps[i + 1]])
            durations[steps[i]] = round((t1 - t0).total_seconds(), 2)
        except Exception:
            pass
    return durations


def write_run_card(
    state: Any,
    persistence: Any,
    tools_config: dict[str, Any] | None = None,
    llm_config: dict[str, Any] | None = None,
) -> Path:
    """Write ``run_card.json`` into the run directory.

    Parameters
    ----------
    state : RunState
        The completed (or current) run state.
    persistence : Persistence
        Used to resolve the run directory and artifact paths.
    tools_config : dict, optional
        The tools section of the config (already env-expanded).
    llm_config : dict, optional
        The llm section of the config (already env-expanded).

    Returns
    -------
    Path to the written ``run_card.json``.
    """
    run_dir = persistence.run_dir(state.run_id)
    tools_config = tools_config or {}
    llm_config = llm_config or {}

    # --- Version info ---
    card: dict[str, Any] = {
        "run_id": state.run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "aptgent_version": _aptgent_version(),
        "git_commit": _git_commit(),
    }

    # --- Predictor model hashes ---
    pred_cfg = tools_config.get("predictor", {})
    model_dir = pred_cfg.get("model_dir")
    if model_dir:
        card["predictor_model_hashes"] = _model_hashes(model_dir)

    # --- Tool versions ---
    tool_versions: dict[str, str | None] = {}
    rna_fold_cmd = tools_config.get("rna_fold", {}).get("command", "RNAfold")
    vina_cmd = tools_config.get("docking", {}).get("command", "vina")
    rna_ver = _tool_version(rna_fold_cmd)
    vina_ver = _tool_version(vina_cmd)
    if rna_ver:
        tool_versions["rnafold"] = rna_ver
    if vina_ver:
        tool_versions["vina"] = vina_ver
    card["tool_versions"] = tool_versions

    # --- LLM info ---
    llm_info: dict[str, Any] = {
        "provider": llm_config.get("default_provider", "openai"),
    }
    provider_cfg = llm_config.get("provider", {}).get("openai", {})
    if provider_cfg.get("model"):
        llm_info["model"] = provider_cfg["model"]
    card["llm"] = llm_info

    # --- Enumeration parameters ---
    enum_params: dict[str, Any] = {}
    if state.confirmed_mutation_sites:
        enum_params["mutation_sites"] = state.confirmed_mutation_sites
    enum_params["total_candidates"] = len(state.candidates)
    enum_params["total_predictions"] = len(state.predictions)
    card["enumeration"] = enum_params

    # --- Docking parameters ---
    docking_params: dict[str, Any] = {}
    dp = state.docking_plan
    if dp:
        docking_params["top_k"] = dp.recommended_top_k
        docking_params["seed"] = dp.seed
        docking_params["exhaustiveness"] = dp.exhaustiveness
        docking_params["grid_size"] = dp.grid_size
        docking_params["grid_center"] = dp.grid_center
    docking_params["total_docking_results"] = len(state.docking_results)
    card["docking"] = docking_params

    # --- Step timing ---
    step_ts = {}
    if hasattr(state, "step_timestamps"):
        step_ts = state.step_timestamps or {}
    card["step_timestamps"] = step_ts
    card["step_durations_seconds"] = _compute_step_durations(step_ts)

    # --- Write ---
    path = run_dir / "run_card.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(card, f, indent=2, ensure_ascii=False)

    _log.info("Run card written to %s", path)
    return path
