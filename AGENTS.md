# AGENTS.md — Aptamer Design Assistant Project

> This file is intended for AI coding agents. It summarizes the project architecture, build steps, conventions, and critical implementation details.

---

## 1. Project Overview

This repository contains **two related Python projects** that work together:

1. **`aptgent/`** — The main **TUI (Terminal User Interface) application** for an aptamer design workflow. It guides users through: natural-language intake → RNA secondary structure prediction → mutation site proposal → candidate enumeration → ML-based scoring → final report generation.
2. **`aptamer_predictor/`** — A standalone **CLI toolkit** that provides a 9-model ensemble predictor for aptamer–small molecule binding. It is consumed by `aptgent` via a Python-path adapter (not packaged as a wheel).

The overall architecture follows a **stateful workflow engine** with deterministic adapters for all external tools. LLM calls (OpenAI-compatible provider) are restricted to natural-language understanding, explanation generation, and recommendation of mutation sites; they are **not allowed** to change scores, rankings, or any deterministic computation results.

---

## 2. Repository Structure

```
Aptgent/
├── aptgent/                          # Main TUI orchestrator
│   ├── aptgent/
│   │   ├── adapters/                 # External tool adapters (RNAfold, predictor, molecule resolver, docking)
│   │   ├── config/                   # TOML configuration files
│   │   ├── domain/                   # Pydantic models and enums
│   │   ├── llm/                      # OpenAI-compatible client + LLM skills
│   │   ├── tui/                      # Textual screens, widgets, and styles
│   │   │   ├── screens/              # One screen per workflow step
│   │   │   ├── widgets/              # Reusable TUI components
│   │   │   └── styles/main.tcss      # Textual CSS
│   │   ├── workflow/                 # Engine, persistence, and RunState
│   │   ├── __init__.py
│   │   └── __main__.py               # Entry point: python -m aptgent
│   ├── tests/                        # pytest suite
│   ├── pyproject.toml                # Package metadata & dependencies
│   └── runs/                         # Default runtime state directory
├── aptamer_predictor/                # Standalone ML prediction CLI
│   ├── aptamer_predictor/
│   │   ├── cli.py                    # Argument parsing & subcommands
│   │   ├── features.py               # k-mer + RDKit descriptor extraction
│   │   ├── predictor.py              # Model loading & ensemble prediction
│   │   ├── __init__.py
│   │   └── __main__.py               # Entry point: python -m aptamer_predictor
│   ├── models/                       # 9 pre-trained .pkl files
│   ├── data/                         # Source datasets (CSV)
│   ├── requirements.txt
│   └── README.md
├── plan.md                           # Original Chinese prototype plan
└── 基团-碱基互作矩阵.xlsx             # Spatial interaction rules (external reference)
```

---

## 3. Technology Stack

| Layer | Tech |
|-------|------|
| **Language** | Python >= 3.9 |
| **TUI Framework** | `textual>=0.50` |
| **Data Validation** | `pydantic>=2.0` |
| **HTTP Client** | `httpx>=0.25` |
| **Config Parsing** | `tomli>=2.0` |
| **ML/SciPy** | `numpy`, `pandas`, `scikit-learn`, `xgboost`, `torch`, `rdkit` |
| **External Tools** | ViennaRNA (`RNAfold`), AutoDock Vina (placeholder) |
| **LLM Provider** | OpenAI-compatible API (default config points to Moonshot/Kimi) |

---

## 4. Build and Run Commands

### Install `aptgent` (editable)
```bash
cd aptgent
pip install -e .
```

### Run the TUI app
```bash
# After pip install -e .
aptgent

# Or directly
python -m aptgent
```

### Run `aptamer_predictor` CLI
```bash
cd aptamer_predictor
# Requires separate env with rdkit + scikit-learn + xgboost + torch
python -m aptamer_predictor predict --help
```

### Run tests
```bash
cd aptgent
pytest
```

---

## 5. Code Organization & Module Divisions

### `aptgent` Layers

| Module | Responsibility |
|--------|----------------|
| `domain/` | **Single source of truth** for all data structures. `RunState`, `CandidateSequence`, `PredictionResult`, `TargetMolecule`, `SecondaryStructure`, `FinalRecommendation`, `Step`/`Status` enums. |
| `workflow/` | **Orchestration**. `WorkflowEngine` drives the step transition graph; `Persistence` serializes `RunState` to `runs/<run_id>/state.json` and manages artifacts/logs; `RunState` is a Pydantic model. |
| `adapters/` | **External tool boundaries**. Implements `StructureAdapter`, `PredictionAdapter`, `MoleculeAdapter` protocols. Current implementations: `RNAfoldAdapter`, `EnsembleAdapter` (wraps `aptamer_predictor`), `SimpleMoleculeResolver`, `DockingPrepAdapter` / `VinaAdapter` (placeholders). |
| `llm/` | **Controlled LLM access**. `LLMClient` handles OpenAI-compatible chat completions with JSON-mode. `skills.py` exposes `IntakeSkill`, `SiteProposalSkill`, `ReportSkill` — each with strict system prompts returning structured JSON. |
| `tui/` | **User interface**. One `Screen` per workflow step (`WelcomeScreen`, `IntakeScreen`, `StructureScreen`, `SiteProposalScreen`, `EnumerationScreen`, `ScoringScreen`, `ReportScreen`). `AptgentApp` ties everything together. |

### `aptamer_predictor` Layers

| Module | Responsibility |
|--------|----------------|
| `features.py` | k-mer frequency extraction + 209 RDKit molecular descriptors (Ipc excluded). `build_feature_vector()` concatenates both. |
| `predictor.py` | `EnsemblePredictor` loads 9 `.pkl` models. Supports lazy PyTorch import. Ensemble rule: label = 1 **only if all 9 models predict 1**, otherwise 0. |
| `cli.py` | Subcommands: `predict` (single/batch), `evaluate` (test metrics), `extract-aptamer`, `extract-molecule`. |

---

## 6. Adapter Pattern & Extensibility Rules

The workflow engine enforces a strict adapter boundary:

- **Never** call `subprocess` or external libraries directly from TUI screens or workflow engine.
- All external calls go through classes in `adapters/`.
- New prediction models can be added by implementing the `PredictionAdapter` protocol and swapping the instance in `AptgentApp`.
- Docking and 3D prep are intentionally **placeholders** (`DockingPrepAdapter`, `VinaAdapter`) per the prototype plan; they are meant to be replaced or bridged via subprocess / manual handoff in future iterations.

`EnsembleAdapter` accesses `aptamer_predictor` by inserting the sibling directory into `sys.path` at runtime:
```python
_APTAMER_PREDICTOR_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "aptamer_predictor")
)
```

---

## 7. Workflow & State Machine

### Defined Steps (in `domain.enums.Step`)
1. `intake`
2. `secondary_structure`
3. `site_proposal`
4. `candidate_enumeration`
5. `primary_scoring`
6. `final_report`

(Phase-2 steps — `specificity_filter`, `docking_prep`, `docking_selection`, `docking_run`, `spatial_rank` — are defined in the enum but commented out in `TRANSITIONS` and the TUI flow.)

### Transition Rules
`TRANSITIONS` in `workflow/engine.py` is a hard-coded DAG. Invalid transitions raise `ValueError`.

### Persistence Layout
Each run gets a folder under `runs/<run_id>/`:
- `state.json` — serialized `RunState`
- `artifacts/` — JSON/CSV artifacts written by screens
- `logs/workflow.jsonl` — append-only event log

### Pause / Resume
The engine supports `pause(state, reason, pending_input)` and `resume(state)`. This is used when:
- The user omits the target molecule (allowed to continue to structure, but blocked before scoring).
- Molecule resolution fails and needs manual SMILES input.

---

## 8. Configuration

Three TOML files live in `aptgent/aptgent/config/`:

| File | Purpose |
|------|---------|
| `llm.toml` | Provider URL, model name, API key env var, temperature, max tokens, timeout. |
| `tools.toml` | `RNAfold` command/args, docking engine command, predictor model directory. |
| `workflow.toml` | Candidate enumeration limit (`max_candidates = 5000`), default edit ratio threshold (`0.3`), docking enablement flag, run directory path. |

### Important Security Note
`config/llm.toml` currently stores a hard-coded API key string in the `api_key_env` field. In production or shared environments this must be rotated and replaced with an actual environment-variable name. The `LLMClient` reads the key via `os.environ.get(self.config["api_key_env"], "")`, so if a raw string is placed there it will fail to resolve from the environment.

---

## 9. Testing Strategy

Tests are located in `aptgent/tests/` and run with `pytest`.

- **`test_workflow.py`** — Unit tests for `Persistence`, `WorkflowEngine` (create/load, transition validation, pause/resume), `SimpleMoleculeResolver`, candidate enumeration logic, and `EnsembleAdapter` batch prediction.
- **`test_tui.py`** — Async integration tests using Textual's `run_test()` harness. Covers welcome→intake navigation, full screen flow traversal, and enumeration limit enforcement (continue button disabled when `4^len(sites) > max_candidates`).

### Adding Tests
- Use `tempfile.TemporaryDirectory()` when testing `Persistence` to avoid polluting the real `runs/` directory.
- TUI tests should be decorated with `@pytest.mark.anyio` and use `async with app.run_test() as pilot:`.

---

## 10. Development Conventions

- **Typing**: Use `from __future__ import annotations` in every module; type hints are encouraged.
- **Models**: All domain objects are `pydantic.BaseModel` subclasses. Serializing state uses `model_dump_json()`.
- **Naming**: English camelCase for Textual widget IDs (e.g., `#btn-continue`, `#intake-input`).
- **Screens**: Each screen yields `self.app.progress_bar` and `self.app.status_panel` at the top, followed by a `#content-area` and an `#action-bar`.
- **Error Handling**: Adapters raise domain-specific exceptions (`FileNotFoundError` for missing binaries, `RuntimeError` for tool failures). TUI screens catch these and update a status/static widget with `add_class("error-text")`.
- **LLM Guardrails**: System prompts in `llm/skills.py` enforce JSON-only output. The report skill explicitly instructs the model **not** to change ordering or scores.

---

## 11. Deployment & Environment Notes

- `aptgent` is distributed as a **source-installable Python package** via `pyproject.toml` + setuptools.
- `aptamer_predictor` is **not** published as a package; it is expected to be present as a sibling directory so the runtime `sys.path` insertion works.
- Heavy dependencies (RDKit, PyTorch, XGBoost) are isolated in the predictor environment. The main `aptgent` environment is intentionally lightweight and delegates model inference through the adapter boundary.
- Docker is **not** part of the current prototype.

---

## 12. Common Pitfalls

1. **Missing `RNAfold` binary** — `RNAfoldAdapter(lazy=True)` delays the check until `fold()` is called. If ViennaRNA is not installed, the TUI shows a user-friendly error in `StructureScreen`.
2. **NaN in feature vectors** — `features.py` replaces NaN descriptor values with `0.0` via `np.nan_to_num`. This is critical because the PyTorch RNN models propagate NaN and produce invalid outputs.
3. **EnsembleAdapter path sensitivity** — Moving `aptamer_predictor/` out of the repository root will break the relative-path resolution in `EnsembleAdapter.__init__`.
4. **Candidate explosion** — The enumeration screen blocks if `4 ** len(sites) > max_candidates` (default 5000). This is a hard safety limit, not configurable at runtime via the UI.
