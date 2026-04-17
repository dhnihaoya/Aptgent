# Aptgent — Aptamer Design Assistant

This repository centers on one Python project:

- `aptgent/`: the Textual-based TUI workflow application.

The aptamer-small molecule predictor is now integrated inside `aptgent` as an internal runtime that is still launched via subprocess to keep the ML dependency stack isolated from the main TUI environment.

`aptgent` drives a chat-first workflow from natural-language intake to ranked candidate recommendations, combining RNA structure prediction, deterministic scoring, specificity filtering, molecular docking, and spatial interaction ranking.

## Pipeline

```
Natural language input
        |
        v
  1. Intake (LLM extraction)
        |
        v
  2. RNA secondary structure (ViennaRNA RNAfold)
        |
        v
  3. Mutation site proposal (LLM-assisted)
        |
        v
  4. Candidate enumeration (combinatorial)
        |
        v
  5. Primary scoring (9-model ensemble)
        |
        v
  6. Specificity filter (cross-prediction vs analogs)
        |
        v
  7. Docking selection (LLM top-k planning)
        |
        v
  8. Molecular docking (AutoDock Vina)
        |
        v
  9. Spatial interaction rank (base-group matrix)
        |
        v
  10. Final report (ranked recommendations + JSON export)
```

## Prerequisites

| Tool | Purpose | Install |
|------|---------|---------|
| **Python >= 3.9** | Runtime | System package manager |
| **RDKit** | SMILES parsing, molecular descriptors | `conda install -c conda-forge rdkit` |
| **ViennaRNA** | RNA secondary structure prediction | See below |
| **AutoDock Vina** | Molecular docking | See below |
| **LLM API key** | LLM-powered features (intake, site proposal, etc.) | Set environment variable |

> **Note:** RDKit must be installed via conda, not pip.

## Setup

### 1. Use the repository layout as-is

```
/path/to/Aptgent/
  └── aptgent/              # TUI app package + internal predictor runtime
```

```bash
cd /path/to/Aptgent
```

### 2. Create a conda environment

```bash
conda create -n aptgent python=3.9 -y
conda deactivate  # if base is activated
conda activate aptgent
```

### 3. Install RDKit

```bash
conda install -c conda-forge rdkit=2023.9 -y
```

### 4. Install ViennaRNA

**macOS (Homebrew):**
```bash
brew install viennarna
```

**Linux (conda):**
```bash
conda install -c bioconda viennarna -y
```

**From source:** https://www.tbi.univie.ac.at/RNA/

Verify:
```bash
RNAfold --version
```

### 5. Install AutoDock Vina

**macOS (Homebrew):**
```bash
brew install autodock-vina
```

**Linux (conda):**
```bash
conda install -c conda-forge autodock-vina -y
```

**Pre-built binaries:** https://github.com/ccsb-scripps/AutoDock-Vina/releases

Verify:
```bash
vina --version
```

### 6. Install Python dependencies

```bash
cd aptgent
pip install -e .
```

This installs the `aptgent` app dependencies listed in `pyproject.toml` (Textual, Pydantic, httpx, numpy, psutil, meeko). The heavier predictor stack remains isolated in a separate runtime environment.

### 7. Install the predictor runtime environment

```bash
conda create -n aptamer-predictor python=3.9 -y
conda activate aptamer-predictor
conda install -c conda-forge rdkit=2023.9 -y
pip install numpy pandas scikit-learn xgboost torch matplotlib
```

`aptgent` calls its internal predictor runtime through a subprocess adapter. Keep that environment separate if you want to avoid installing the full ML stack into the TUI environment.

### 8. Configure LLM API key

Aptgent uses an OpenAI-compatible LLM API for several workflow steps.

Preferred setup:
```bash
export KIMI_API_KEY="your-api-key-here"
```

`aptgent/aptgent/config/llm.toml` keeps provider settings and an empty fallback field. Do not commit real keys there.

> The default configuration points to Moonshot (Kimi) API. You can edit `aptgent/aptgent/config/llm.toml` to use any OpenAI-compatible endpoint.

### 9. Configure tool paths

Review `aptgent/aptgent/config/tools.toml` before running the full workflow. The committed paths are machine-specific examples and are not portable defaults.

At minimum, verify:

- `rna_fold.command`
- `docking.command`
- `predictor.model_dir`
- `predictor.conda_python` or `predictor.conda_env`

### 10. Verify installation

```bash
cd /path/to/Aptgent/aptgent
python -m aptgent
```

This should launch the TUI application.

## Usage

### Launch the application

```bash
python -m aptgent
```

Or after `pip install -e .`:

```bash
aptgent
```

### Workflow walkthrough

1. **Welcome** — Create a new run or resume an existing one.
2. **Intake** — Describe your aptamer and target in natural language (e.g., "I have a 20-nt aptamer GGGAAACCC targeting benzene C1=CC=CC=C1"). The LLM extracts the sequence, target molecule, and optional constraints.
3. **Structure** — RNAfold predicts the secondary structure (dot-bracket + MFE).
4. **Site Proposal** — The LLM suggests mutation sites based on loop/stem analysis. You confirm or manually specify sites.
5. **Enumeration** — All possible single-base mutations at confirmed sites are enumerated. Capped at 5,000 candidates.
6. **Scoring** — Each candidate is scored by the 9-model ensemble predictor. The reported probability is averaged across model outputs, but the ensemble label is `1` only when every model predicts `1`.
7. **Specificity Filter** — LLM suggests structural analogs of the target. Candidates that bind analogs are removed.
8. **Docking Selection** — Hardware profile is detected. LLM recommends how many top candidates to dock.
9. **Docking Run** — AutoDock Vina scores the top-k candidates.
10. **Spatial Rank** — Candidates are re-ranked using a base-functional-group interaction matrix (4 bases x 24 groups).
11. **Report** — Final ranked table with all phase data. Export to JSON.

### State persistence

All workflow state is saved to `runs/<run_id>/`:

```
runs/
  └── my_run/
      ├── state.json          # Full RunState snapshot
      ├── artifacts/
      │   └── final_report.json
      └── logs/
          └── workflow.jsonl   # Transition event log
```

You can close the TUI and resume later from the Welcome screen.

## Project Structure

```
.
├── aptgent/
│   ├── aptgent/
│   │   ├── adapters/
│   │   │   ├── predictor.py
│   │   ├── predictor_runtime/
│   │   ├── resources/
│   │   │   └── predictor_models/
│   │   ├── tui/
│   │   ├── workflow/
│   │   ├── llm/
│   │   ├── domain/
│   │   └── config/
│   ├── tests/
│   ├── pyproject.toml
│   └── README.md
```

The current UI is chat-first: `AptgentApp` registers `welcome` and `chat`, and the per-step workflow logic lives in `aptgent/aptgent/tui/widgets/step_handlers.py`.

## Configuration

### LLM provider (`aptgent/aptgent/config/llm.toml`)

```toml
[provider.openai]
base_url = "https://api.moonshot.cn/v1"
model = "kimi-k2.5"
api_key = ""
api_key_env = "KIMI_API_KEY"
temperature = 1
max_tokens = 4096
```

Change `base_url` and `model` to use any OpenAI-compatible API.

Keep secrets in environment variables instead of committing them into this file.

### Workflow parameters (`aptgent/aptgent/config/workflow.toml`)

```toml
[enumeration]
max_candidates = 5000
default_edit_ratio_threshold = 0.3

[docking]
enabled = false
top_k_strategy = "auto"
```

## Tested Dependency Versions

These are the app-side dependencies for `aptgent`. The predictor runtime still needs RDKit, scikit-learn, xgboost, torch, and related scientific packages in its own environment.

| Package      | Version    |
|--------------|------------|
| Python       | 3.9        |
| Textual      | 8.2.3      |
| Pydantic     | 2.13.0     |
| RDKit        | 2023.09.5  |
| NumPy        | 1.24.x     |
| ViennaRNA    | 2.6+       |

## License

MIT
