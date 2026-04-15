<!-- From: /home/dh/Aptgent/AGENTS.md -->
# AGENTS.md — Aptamer Design Assistant Project

> This file is intended for AI coding agents. It summarizes the project architecture, build steps, conventions, and critical implementation details.

---

## 1. Project Overview

This repository contains **two related Python projects** that work together:

1. **`aptgent/`** — The main **TUI (Terminal User Interface) application** for an aptamer design workflow. It guides users through: natural-language intake → RNA secondary structure prediction → mutation site proposal → candidate enumeration → ML-based scoring → specificity filtering → molecular docking → spatial interaction ranking → final report generation.
2. **`aptamer_predictor/`** — A standalone **CLI toolkit** that provides a 9-model ensemble predictor for aptamer–small molecule binding. It is consumed by `aptgent` via subprocess calls (not packaged as a wheel).

The overall architecture follows a **stateful workflow engine** with deterministic adapters for all external tools. LLM calls (OpenAI-compatible provider) are restricted to natural-language understanding, explanation generation, and recommendation of mutation sites; they are **not allowed** to change scores, rankings, or any deterministic computation results.

---

## 2. Repository Structure

```
Aptgent/
├── aptgent/                          # Main TUI orchestrator
│   ├── aptgent/
│   │   ├── adapters/                 # External tool adapters (RNAfold, predictor, molecule resolver, docking, spatial rank)
│   │   ├── config/                   # TOML configuration files + spatial interaction matrix CSV
│   │   ├── domain/                   # Pydantic models and enums
│   │   ├── llm/                      # OpenAI-compatible client + LLM skills
│   │   ├── tui/                      # Textual screens, widgets, styles, and step handlers
│   │   │   ├── screens/              # Welcome, Chat, and legacy per-step screens
│   │   │   ├── widgets/              # Reusable TUI components (progress bar, chat bubbles, structured inputs, step handlers)
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
| **Docking Prep** | `meeko>=0.5.0`, `psutil>=5.9.0` |
| **External Tools** | ViennaRNA (`RNAfold`), AutoDock Vina |
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
| `domain/` | **Single source of truth** for all data structures. `RunState`, `CandidateSequence`, `PredictionResult`, `TargetMolecule`, `SecondaryStructure`, `DockingPlan`, `DockingResult`, `SpecificityResult`, `SpatialRankResult`, `FinalRecommendation`, `ArtifactRef`, `Step`/`Status` enums. |
| `workflow/` | **Orchestration**. `WorkflowEngine` drives the step transition graph; `Persistence` serializes `RunState` to `runs/<run_id>/state.json` and manages artifacts/logs; `RunState` is a Pydantic model. |
| `adapters/` | **External tool boundaries**. Implements `StructureAdapter`, `PredictionAdapter`, `MoleculeAdapter`, `SpatialRankAdapter` protocols in `base.py`. Current implementations: `RNAfoldAdapter`, `EnsembleAdapter` (subprocess wrapper around `aptamer_predictor`), `SimpleMoleculeResolver`, `VinaAdapter` (real AutoDock Vina integration via `meeko` + RDKit), `DockingPrepAdapter` (placeholder), `SpatialRankAdapter` (CSV matrix + RDKit SMARTS), `HardwareProbeAdapter`. |
| `llm/` | **Controlled LLM access**. `LLMClient` handles OpenAI-compatible chat completions with JSON-mode. `skills.py` exposes `IntakeSkill`, `SiteProposalSkill`, `AnalogSuggestionSkill`, `DockingPlannerSkill`, `ReportSkill` — each with strict system prompts returning structured JSON. |
| `tui/` | **User interface**. `AptgentApp` registers `WelcomeScreen` and `ChatScreen`. The primary UX is a **single chat screen** (`ChatScreen`) where `StepHandler` subclasses manage each workflow step as a conversational turn. Legacy per-step screens (`IntakeScreen`, `StructureScreen`, etc.) still exist in `screens/` but are not the active entry path. |

### `aptamer_predictor` Layers

| Module | Responsibility |
|--------|----------------|
| `features.py` | k-mer frequency extraction + 209 RDKit molecular descriptors (Ipc excluded). `build_feature_vector()` concatenates both and applies `np.nan_to_num(..., nan=0.0)`. |
| `predictor.py` | `EnsemblePredictor` loads 9 `.pkl` models. Supports lazy PyTorch import via `SimpleRNN` wrapper. Ensemble rule: label = 1 **only if all 9 models predict 1**, otherwise 0. |
| `cli.py` | Subcommands: `predict` (single/batch), `evaluate` (test metrics), `extract-aptamer`, `extract-molecule`. |

---

## 6. Adapter Pattern & Extensibility Rules

The workflow engine enforces a strict adapter boundary:

- **Never** call `subprocess` or external libraries directly from TUI screens or the workflow engine.
- All external calls go through classes in `adapters/`.
- New prediction models can be added by implementing the `PredictionAdapter` protocol and swapping the instance in `AptgentApp`.

`EnsembleAdapter` runs `aptamer_predictor` in a **subprocess** using a configurable conda Python interpreter (`tools.toml` → `predictor.conda_python`). It writes temp JSON files for single predictions and parses the stdout/JSON results. `PYTHONPATH` is injected so the subprocess can locate the `aptamer_predictor` package.

---

## 7. Workflow & State Machine

### Defined Steps (in `domain.enums.Step`)
1. `intake`
2. `secondary_structure`
3. `site_proposal`
4. `candidate_enumeration`
5. `primary_scoring`
6. `specificity_filter`
7. `docking_selection`
8. `docking_run`
9. `spatial_rank`
10. `final_report`

### Transition Rules
`TRANSITIONS` in `workflow/engine.py` is a hard-coded linear DAG. Invalid transitions raise `ValueError`.

### Chat-Based Step Handlers
`ChatScreen` delegates each step to a `StepHandler` subclass defined in `tui/widgets/step_handlers.py`:
- `IntakeHandler` — LLM extraction + molecule resolution
- `StructureHandler` — RNAfold execution
- `SiteProposalHandler` — LLM site suggestion + checkbox panel
- `EnumerationHandler` — combinatorial candidate generation
- `ScoringHandler` — ensemble prediction batch call
- `SpecificityHandler` — analog suggestion / cross-prediction filtering
- `DockingSelectionHandler` — hardware probe + LLM top-k recommendation + docking param panel
- `DockingRunHandler` — Vina batch docking
- `SpatialRankHandler` — base–functional-group matrix ranking
- `ReportHandler` — deterministic ranking + LLM summary + JSON export

Handlers advance steps by calling `screen.advance_to_step(next_step)`, which updates `RunState` via `WorkflowEngine.transition_to()`.

### Persistence Layout
Each run gets a folder under `runs/<run_id>/`:
- `state.json` — serialized `RunState`
- `artifacts/` — JSON/CSV artifacts written by handlers/screens
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
| `llm.toml` | Provider URL, model name, API key env var, temperature, max tokens. |
| `tools.toml` | `RNAfold` command/args, `vina` command/args, predictor model directory, predictor conda python path. |
| `workflow.toml` | Candidate enumeration limit (`max_candidates = 5000`), default edit ratio threshold (`0.3`), docking enablement flag, run directory path. |

### Spatial Interaction Matrix
`config/spatial_interaction_matrix.csv` defines a 4 × 24 scoring matrix (bases A, T/U, C, G vs. functional groups). `SpatialRankAdapter` uses RDKit SMARTS matching to detect groups in the target SMILES and scores each candidate sequence accordingly.

### Important Security Note
`config/llm.toml` currently stores a hard-coded API key in the `api_key` field as a fallback. In production or shared environments this must be removed and replaced with the environment variable `KIMI_API_KEY` only. The `LLMClient` reads the key via `os.environ.get(api_key_env, "") or config_fallback`, so the env var takes priority.

---

## 9. Testing Strategy

Tests are located in `aptgent/tests/` and run with `pytest`.

- **`test_workflow.py`** — Unit tests for `Persistence`, `WorkflowEngine` (create/load, transition validation, pause/resume), `SimpleMoleculeResolver`, candidate enumeration logic, and `EnsembleAdapter` batch prediction.
- **`test_tui.py`** — Async integration tests using Textual's `run_test()` harness. Covers welcome→intake navigation, full screen flow traversal, and enumeration limit enforcement.
- **`test_spatial_rank.py`** — Tests for `SpatialRankAdapter`: matrix loading, base mapping, sequence scoring, batch ranking, RDKit SMARTS group detection (with `skipif` guards for missing RDKit).

### Adding Tests
- Use `tempfile.TemporaryDirectory()` when testing `Persistence` to avoid polluting the real `runs/` directory.
- TUI tests should be decorated with `@pytest.mark.anyio` and use `async with app.run_test() as pilot:`.
- Use `@pytest.mark.skipif(_RDKIT_AVAILABLE, ...)` or `@pytest.mark.skipif(not _RDKIT_AVAILABLE, ...)` for RDKit-dependent spatial rank tests.

---

## 10. Development Conventions

- **Typing**: Use `from __future__ import annotations` in every module; type hints are encouraged.
- **Models**: All domain objects are `pydantic.BaseModel` subclasses. Serializing state uses `model_dump_json()`.
- **Naming**: English kebab-case for Textual widget IDs (e.g., `#btn-continue`, `#intake-input`, `#chat-log`).
- **Screens/Widgets**: CSS classes used across the app include `title`, `info-text`, `error-text`, `success-text`, `warning-text`.
- **Error Handling**: Adapters raise domain-specific exceptions (`FileNotFoundError` for missing binaries, `RuntimeError` for tool failures). Chat handlers catch these and post system messages with `error-text` styling.
- **LLM Guardrails**: System prompts in `llm/skills.py` enforce JSON-only output. The report skill explicitly instructs the model **not** to change ordering or scores.
- **Concurrency**: Long-running adapter calls inside `ChatScreen` are executed via `screen.run_worker(..., thread=True)` so the UI remains responsive. UI updates from worker threads must use `screen.app.call_from_thread(...)`.

---

## 11. Deployment & Environment Notes

- `aptgent` is distributed as a **source-installable Python package** via `pyproject.toml` + setuptools.
- `aptamer_predictor` is **not** published as a package; it is expected to be present as a sibling directory so the subprocess `PYTHONPATH` injection works.
- Heavy dependencies (RDKit, PyTorch, XGBoost) are typically isolated in a separate conda environment. `aptgent`'s `EnsembleAdapter` can invoke that environment via `tools.toml`'s `conda_python` path.
- Docker is **not** part of the current prototype.

---

## 12. Common Pitfalls

1. **Missing `RNAfold` binary** — `RNAfoldAdapter(lazy=True)` delays the check until `fold()` is called. If ViennaRNA is not installed, the chat handler shows a user-friendly error message.
2. **Missing `vina` binary** — `VinaAdapter(lazy=True)` defers the check. Docking will fail gracefully with an error message if AutoDock Vina is unavailable.
3. **NaN in feature vectors** — `features.py` replaces NaN descriptor values with `0.0` via `np.nan_to_num`. This is critical because the PyTorch RNN models propagate NaN and produce invalid outputs.
4. **EnsembleAdapter path sensitivity** — Moving `aptamer_predictor/` out of the repository root will break the relative-path resolution in `EnsembleAdapter.__init__`.
5. **Candidate explosion** — The enumeration handler blocks if `4 ** len(sites) > max_candidates` (default 5000). This is a hard safety limit, not configurable at runtime via the UI.
6. **Dual UI state** — The app currently routes users through `ChatScreen` (new chat UX). Legacy per-step screens exist but rely on `app.advance_step()`, which is no longer defined in `AptgentApp`. If modifying screen navigation, prefer updating `ChatScreen` and `StepHandler` rather than the legacy screens.
