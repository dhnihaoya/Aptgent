"""Probe the local environment and report tool availability."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

_CONDA_ROOTS = [
    Path.home() / ".conda" / "envs",
    Path.home() / "miniconda3" / "envs",
    Path.home() / "anaconda3" / "envs",
    Path("/opt/miniconda3/envs"),
    Path("/opt/anaconda3/envs"),
]

_TOOL_ENVS = ["aptgent", "aptgent-tools"]


def _search_conda_binary(name: str) -> str | None:
    """Search for *name* in known conda environment bin directories."""
    for root in _CONDA_ROOTS:
        if not root.is_dir():
            continue
        for env_name in _TOOL_ENVS:
            candidate = root / env_name / "bin" / name
            if candidate.is_file():
                return str(candidate)
    return None


def _check_binary(name: str) -> dict[str, Any]:
    path = shutil.which(name)
    # Also check the bin directory of the running Python (covers
    # non-activated conda envs invoked via full path).
    if path is None:
        import sys
        env_bin = Path(sys.executable).resolve().parent
        candidate = env_bin / name
        if candidate.is_file():
            path = str(candidate)
    hint = None
    if path is None:
        conda_path = _search_conda_binary(name)
        if conda_path:
            hint = (
                f"Found at {conda_path} but not in current PATH. "
                f"Make sure you activated the aptgent conda environment: "
                f"conda activate aptgent"
            )
        else:
            hint = (
                f"Not found. Install via: conda env update -f environment.yml "
                f"(or set APTGENT_{name.upper().replace('-', '_')}=/path/to/{name})"
            )
        return {"status": "missing", "path": None, "version": None, "hint": hint}
    version = None
    try:
        result = subprocess.run(
            [path, "--version"],
            capture_output=True, text=True, timeout=10,
        )
        output = (result.stdout or result.stderr).strip()
        version = output.split("\n")[0] if output else None
    except Exception:
        pass
    return {"status": "ok", "path": path, "version": version}


def _check_predictor(model_dir: str | None) -> dict[str, Any]:
    if model_dir is None:
        return {"status": "not_configured", "model_dir": None, "model_count": 0}
    p = Path(model_dir)
    if not p.is_dir():
        return {"status": "missing_dir", "model_dir": str(p), "model_count": 0}
    pkl_files = list(p.glob("*.pkl"))
    return {
        "status": "ok",
        "model_dir": str(p),
        "model_count": len(pkl_files),
        "models": [f.name for f in sorted(pkl_files)],
    }


def _check_llm(llm_config: dict[str, Any]) -> dict[str, Any]:
    provider_cfg = llm_config.get("provider", {}).get("openai", {})
    api_key_env = provider_cfg.get("api_key_env", "GLM_API_KEY")
    has_key = bool(os.environ.get(api_key_env) or provider_cfg.get("api_key"))
    return {
        "provider": llm_config.get("default_provider", "openai"),
        "model": provider_cfg.get("model", "unknown"),
        "api_key_env": api_key_env,
        "api_key_set": has_key,
        "status": "ok" if has_key else "missing_key",
    }


def _check_predictor_deps() -> dict[str, Any]:
    """Check whether the heavy predictor dependencies are importable."""
    missing: list[str] = []
    found: list[str] = []
    for mod, label in [
        ("rdkit", "RDKit"),
        ("torch", "PyTorch"),
        ("xgboost", "XGBoost"),
        ("sklearn", "scikit-learn"),
    ]:
        try:
            __import__(mod)
            found.append(label)
        except ImportError:
            missing.append(label)
    if missing:
        return {
            "status": "missing",
            "available": found,
            "missing": missing,
            "hint": (
                "Install via: conda env update -f environment.yml  "
                "(or pip install rdkit torch xgboost scikit-learn)"
            ),
        }
    return {"status": "ok", "available": found}


def _check_url(url: str) -> dict[str, Any]:
    """Check if a URL is reachable via a HEAD request."""
    import urllib.request
    import urllib.error
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return {"status": "ok", "url": url, "http_status": resp.status}
    except Exception as exc:
        return {
            "status": "unreachable",
            "url": url,
            "hint": f"Could not reach {url}: {exc}",
        }


def _check_env_vars() -> dict[str, str | None]:
    keys = [
        "APTGENT_RUNS_DIR",
        "APTGENT_MODEL_DIR",
        "APTGENT_RNAFOLD",
        "APTGENT_VINA",
        "APTGENT_CONDA_ENV",
        "APTGENT_CONDA_PYTHON",
    ]
    return {k: os.environ.get(k) for k in keys}


def run_doctor() -> int:
    from aptgent.bootstrap.config import load_config
    from aptgent.predictor_runtime.paths import default_model_dir

    bundle = load_config()
    tools = bundle.tools
    llm = bundle.llm

    # Resolve model_dir default if not set
    pred_cfg = tools.setdefault("predictor", {})
    if not pred_cfg.get("model_dir"):
        pred_cfg["model_dir"] = str(default_model_dir())

    checks: list[tuple[str, dict[str, Any]]] = []

    # RNAfold
    rna_cmd = tools.get("rna_fold", {}).get("command", "RNAfold")
    checks.append(("RNAfold", _check_binary(rna_cmd)))

    # Vina
    vina_cmd = tools.get("docking", {}).get("command", "vina")
    checks.append(("AutoDock Vina", _check_binary(vina_cmd)))

    # Open Babel (receptor prep)
    obabel_cmd = tools.get("receptor_prep", {}).get("obabel", "obabel")
    checks.append(("Open Babel", _check_binary(obabel_cmd)))

    # wget (PDB download fallback)
    wget_cmd = tools.get("pdb_analysis", {}).get("command", "wget")
    checks.append(("wget (PDB download)", _check_binary(wget_cmd)))

    # RNAComposer reachability
    rnacomposer_url = tools.get("rnacomposer", {}).get(
        "base_url", "https://rnacomposer.cs.put.poznan.pl"
    )
    checks.append(("RNAComposer", _check_url(rnacomposer_url)))

    # Predictor models
    model_dir = tools.get("predictor", {}).get("model_dir")
    checks.append(("Predictor models", _check_predictor(model_dir)))

    # Predictor runtime dependencies
    checks.append(("Predictor runtime", _check_predictor_deps()))

    # LLM
    checks.append(("LLM client", _check_llm(llm)))

    # Runs dir
    runs_dir = bundle.workflow.get("paths", {}).get("runs_dir", "./runs")
    runs_path = Path(runs_dir)
    checks.append(("Runs directory", {
        "status": "ok" if runs_path.is_dir() else "will_create",
        "path": str(runs_path),
    }))

    # Env vars
    env_vars = _check_env_vars()
    set_vars = {k: v for k, v in env_vars.items() if v is not None}

    # Print report
    print("=" * 60)
    print("  aptgent doctor - environment diagnostics")
    print("=" * 60)
    print()

    all_ok = True
    for label, result in checks:
        status = result.get("status", "unknown")
        icon = {
            "ok": "+", "missing": "!", "missing_dir": "!",
            "not_configured": "-", "missing_key": "!", "will_create": "~",
        }.get(status, "?")
        if status not in ("ok", "will_create", "not_configured"):
            all_ok = False
        print(f"  [{icon}] {label}")
        for k, v in result.items():
            if k == "status":
                continue
            print(f"      {k}: {v}")
        print()

    if set_vars:
        print("  Environment overrides:")
        for k, v in set_vars.items():
            print(f"    {k}={v}")
        print()

    print("=" * 60)
    if all_ok:
        print("  All checks passed. Ready to run.")
    else:
        print("  Some checks need attention. See hints above.")
    print("=" * 60)

    return 0 if all_ok else 1
