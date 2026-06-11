# Aptgent

Aptgent is a Textual TUI workflow application for aptamer design. It guides a run from natural-language intake through RNA structure analysis, mutation proposal, candidate enumeration, ensemble prediction, specificity filtering, optional docking, spatial ranking, and final report export.

The repository currently contains one Python project:

- `aptgent/`: the application package, tests, bundled configuration, bundled predictor models, and internal predictor runtime.

The predictor runtime is part of the `aptgent` package, but it still runs through subprocess boundaries. In the default setup, those subprocesses use the current Python from the same conda environment. If needed, `tools.toml` can point predictor execution at a separate conda environment or Python binary.

## Current Workflow

The active workflow is defined in `aptgent/aptgent/workflow/engine.py`.

```text
1. intake
2. secondary_structure
3. site_proposal
4. candidate_enumeration
5. primary_scoring
6. docking_selection
7. docking_run
8. specificity_filter
9. spatial_rank
10. final_report
```

When docking is unavailable (Vina not installed or disabled in config), `docking_selection` skips directly to `specificity_filter` (step 6 → step 8).

The TUI uses a chat-first interface. `AptgentApp` registers the `welcome` and `chat` screens, and `ChatScreen` drives all workflow steps through handlers in `aptgent/aptgent/tui/steps/`.

LLM output is advisory. Deterministic state, scoring, ranking, persistence, and external-tool results should come from workflow, domain, adapter, or predictor-runtime code.

## Requirements

The recommended development environment is the conda environment in `aptgent/environment.yml`.

It installs:

- Python 3.10
- ViennaRNA / `RNAfold`
- AutoDock Vina / `vina`
- Open Babel / `obabel`
- RDKit
- NumPy, SciPy, pandas, scikit-learn, XGBoost, PyTorch
- Textual, Pydantic, httpx, Biopython, Meeko, psutil
- `aptgent` in editable mode

`pyproject.toml` declares `requires-python >=3.10`, and the checked-in environment file pins Python 3.10 as the safest installation path for the full workflow.

## Setup

From the repository root:

```bash
cd aptgent
conda env create -f environment.yml
conda activate aptgent
aptgent doctor
```

For an existing environment:

```bash
cd aptgent
conda env update -f environment.yml
conda activate aptgent
aptgent doctor
```

The editable install is included in `environment.yml`. If you install manually instead:

```bash
cd aptgent
pip install -e .
```

Install predictor extras manually only when you are not using `environment.yml`:

```bash
pip install -e ".[predictor]"
```

## Running

Launch the TUI:

```bash
aptgent
```

Equivalent module entrypoint:

```bash
python -m aptgent
```

Run environment diagnostics:

```bash
aptgent doctor
```

Run a detached workflow job directly:

```bash
aptgent run-job <run_id> <step>
```

Supported detached job steps are:

- `candidate_enumeration`
- `specificity_filter`
- `docking_run`

## User Flow

1. Start a new run from the welcome screen or resume a saved run.
2. Describe the aptamer, target, optional analogs, modification region, and time budget.
3. If a PDB ID is provided, intake enters an internal PDB branch that downloads and analyzes the structure, asks for chain or ligand confirmation when needed, and uses the `pdb_review` LLM skill as a review gate.
4. RNAfold predicts the secondary structure.
5. The LLM proposes 3 alternative mutation-site plans (conservative → aggressive → LLM-selected direction) based on structural context. The user picks one, or enters custom sites.
6. Candidate enumeration scores the mutation space. The accelerated path uses `predict_mutation_batch()` when available and writes positives-only hits to `scored_candidates.jsonl`.
7. Primary scoring ranks enumerated candidates by prediction probability and applies the top-k cutoff.
8. Docking selection proposes docking parameters. Values are clamped before use.
9. Docking runs through AutoDock Vina when configured and accepted.
10. Specificity filtering checks affinity top-y candidates against target analogs.
11. Spatial ranking reorders candidates using `spatial_interaction_matrix.csv`.
12. Final report can be exported to Markdown and the run can be completed.

## Slash Commands

Available commands depend on the active step:

- `/resume [run_id]`: resume a saved workflow.
- `/quit`: open the quit confirmation dialog.
- `/theme`: choose a TUI theme.
- `/back`: jump back to an earlier workflow step.
- `/cancel`: cancel an active detached enumeration, specificity, or docking job.
- `/export`: export the final report Markdown from the final-report step.
- `/finish`: mark the workflow completed from the final-report step.

## Configuration

Configuration files live in `aptgent/aptgent/config/`.

### `workflow.toml`

Controls workflow behavior and persistence.

Important defaults:

```toml
[enumeration]
top_k_keep = 500
sub_batch_size = 65536
progress_every = 10000
mutation_batch_timeout_seconds = 0

[docking]
enabled = true
per_ligand_timeout_seconds = 1800

[paths]
runs_dir = "${APTGENT_RUNS_DIR:-./runs}"
```

`mutation_batch_timeout_seconds = 0` means no wall-clock timeout. `runs_dir` is relative by default, so run data is written relative to the process working directory unless `APTGENT_RUNS_DIR` is set.

### `tools.toml`

External tool and predictor settings.

Useful overrides:

```bash
export APTGENT_RNAFOLD=/path/to/RNAfold
export APTGENT_VINA=/path/to/vina
export APTGENT_MODEL_DIR=/path/to/predictor_models
export APTGENT_CONDA_ENV=aptgent-predictor
export APTGENT_CONDA_PYTHON=/path/to/python
```

By default, `predictor.model_dir` resolves to bundled models in `aptgent/aptgent/resources/predictor_models/`. Leave `APTGENT_CONDA_ENV` and `APTGENT_CONDA_PYTHON` unset for the default single-environment setup.

### `llm.toml`

The default provider is OpenAI-compatible and points at Zhipu GLM:

```toml
[provider.openai]
base_url = "https://open.bigmodel.cn/api/paas/v4"
model = "glm-5.1"
fast_model = "glm-5.1"
api_key_env = "GLM_API_KEY"
temperature = 1
max_tokens = 65536
max_reasoning_tokens = 16384
```

`LLMClient` uses `glm-5.1` for both text output and structured JSON calls.

**API key setup** — two options:

1. **Config file (recommended):** copy `aptgent.local.toml.example` to `aptgent.local.toml` in the project root and fill in `api_key`. This file is gitignored.

```bash
cp aptgent.local.toml.example aptgent.local.toml
# edit aptgent.local.toml → set api_key
```

2. **Environment variable:**

```bash
export GLM_API_KEY=...
```

Key resolution order: `GLM_API_KEY` env var > `aptgent.local.toml` > bundled `llm.toml` (no key).

## Predictor Runtime

Main files:

- `aptgent/aptgent/adapters/predictor.py`: subprocess adapter used by workflow steps.
- `aptgent/aptgent/predictor_runtime/runner.py`: CLI runner for batch prediction and mutation-batch prediction.
- `aptgent/aptgent/predictor_runtime/predictor.py`: ensemble predictor implementation.
- `aptgent/aptgent/predictor_runtime/features.py`: feature construction.
- `aptgent/aptgent/predictor_runtime/cuda.py`: CUDA device selection.
- `aptgent/aptgent/predictor_runtime/paths.py`: bundled model path resolution.

The ensemble rule is strict: the ensemble label is `1` only when all models predict `1`. The reported probability is the average of individual model probabilities.

The accelerated mutation-batch path uses a line-delimited JSON protocol on subprocess stdout:

- `ready`
- `progress`
- `hit`
- `done`
- `error`

The subprocess accepts `cancel` on stdin for cooperative cancellation.

## Persistence and Artifacts

Runs are stored under the configured `runs_dir`.

```text
runs/
  <run_id>/
    state.json
    run_card.json
    artifacts/
      final_report.md
      final_report.json
      scored_candidates.jsonl
      specificity_results.jsonl
    docking/
      *.pdbqt
    jobs/
      candidate_enumeration/
        pid
        events.jsonl
        cmd.jsonl
        status
      specificity_filter/
        pid
        events.jsonl
        cmd.jsonl
        status
      docking_run/
        pid
        events.jsonl
        cmd.jsonl
        status
    logs/
      workflow.jsonl
      llm_calls.jsonl
      job_<step>.log
```

`run_card.json` is written when the workflow completes. It records reproducibility metadata such as app version, git commit, predictor model hashes, tool versions, LLM model, docking parameters, and step timestamps.

LLM call logs go to `logs/llm_calls.jsonl`. User prompts are redacted by default with SHA-256. Set `APTGENT_LLM_REDACT=0` only when full prompt logging is intentional.

## Project Map

```text
aptgent/
  aptgent/
    adapters/             External tools and subprocess boundaries
    bootstrap/            Config loading and runtime assembly
    cli/                  aptgent doctor
    config/               workflow.toml, tools.toml, llm.toml, matrices
    domain/               Pydantic models and enums
    jobs/                 Detached job runner, events, PID helpers
    llm/                  OpenAI-compatible client and LLM skills
    predictor_runtime/    Internal ML runtime and mutation-batch CLI
    resources/            Bundled predictor models
    tui/                  Textual app, screens, steps, widgets, styles
    workflow/             State machine, persistence, run card
  tests/
  environment.yml
  pyproject.toml
```

## Development

Run the test suite from the Python project directory:

```bash
cd aptgent
pytest
```

Targeted tests by area:

- Workflow and persistence: `tests/test_workflow_engine.py`, `tests/test_workflow.py`, `tests/test_persistence.py`
- LLM client and skills: `tests/test_llm_client_retry.py`, `tests/test_llm_client_payloads.py`, `tests/test_llm_result_validation.py`, `tests/test_skills.py`
- Workflow context helpers: `tests/test_workflow_context_helpers.py`
- Predictor and mutation acceleration: `tests/test_predictor_adapter.py`, `tests/test_predictor_adapter_mutation_protocol_success.py`, `tests/test_predictor_adapter_mutation_protocol_cancel.py`, `tests/test_predictor_adapter_mutation_protocol_errors.py`, `tests/test_predictor_feature_matrix_batch.py`, `tests/test_predictor_mutation_batch_runtime.py`, `tests/test_tui_enumeration_acceleration.py`, `tests/test_feature_matrix.py`
- TUI behavior: `tests/test_tui_*.py`, `tests/test_tui_markdown_theme.py`, `tests/test_enumeration_ui.py`
- PDB analysis: `tests/test_pdb_analysis.py`
- Spatial ranking: `tests/test_spatial_rank.py`
- Detached jobs: `tests/test_jobs_*.py`, `tests/test_tui_job_mixin.py`

## Architecture Rules

- Keep external commands in `aptgent/aptgent/adapters/` or `aptgent/aptgent/jobs/`; do not add direct subprocess calls in TUI step handlers unless they are routed through the existing job boundary.
- Keep workflow order and allowed transitions in `workflow/engine.py`.
- Reuse domain models from `domain/models.py` for cross-layer data.
- Treat LLM output as advisory. Clamp or validate LLM suggestions before storing operational values.
- Keep secrets in environment variables.

## Troubleshooting

Run:

```bash
aptgent doctor
```

Common issues:

- `RNAfold` missing: install/update the conda environment or set `APTGENT_RNAFOLD`.
- `vina` missing: install/update the conda environment or set `APTGENT_VINA`.
- Predictor dependencies missing: use `environment.yml` or install the `predictor` optional dependencies plus RDKit.
- LLM key missing: set `GLM_API_KEY`.
- Runs appear missing: check the current working directory and `APTGENT_RUNS_DIR`.
- Detached job cannot reattach: inspect `runs/<run_id>/jobs/<step>/events.jsonl`, `pid`, and `logs/job_<step>.log`.

## License

MIT
