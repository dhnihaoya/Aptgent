# Aptgent — Aptamer Design Assistant

An interactive TUI workflow tool that guides you through the full aptamer design pipeline: from natural language input to ranked candidate recommendations, combining RNA structure prediction, ensemble ML scoring, specificity filtering, molecular docking, and spatial interaction ranking.

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

### 1. Clone the repository alongside aptamer_predictor

```
your-project-dir/
  ├── aptamer_predictor/    # The 9-model ensemble predictor (sibling repo)
  └── aptgent/              # This repo
```

```bash
cd your-project-dir
git clone https://github.com/YOUR_USER/aptamer_predictor.git
git clone https://github.com/YOUR_USER/aptgent.git
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

This installs all Python dependencies listed in `pyproject.toml` (textual, pydantic, httpx, numpy, pandas, scikit-learn, xgboost, torch, psutil).

### 7. Configure LLM API key

Aptgent uses an OpenAI-compatible LLM API for several workflow steps. Two ways to configure:

**Option A: Environment variable (recommended for shared/public deployments)**
```bash
export KIMI_API_KEY="your-api-key-here"
```

**Option B: Config file (convenient for local use)**

Edit `aptgent/config/llm.toml` and set the `api_key` field directly.

Environment variable takes priority over config file.

> The default configuration points to Moonshot (Kimi) API. You can edit `aptgent/config/llm.toml` to use any OpenAI-compatible endpoint.

### 8. Verify installation

```bash
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
6. **Scoring** — Each candidate is scored by the 9-model ensemble predictor (soft-vote averaging).
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
aptgent/
├── aptgent/
│   ├── __init__.py
│   ├── __main__.py                  # python -m aptgent entry point
│   ├── adapters/                    # External tool interfaces
│   │   ├── base.py                  # Adapter protocol definitions
│   │   ├── molecule.py              # SMILES validation + PubChem lookup
│   │   ├── rna_fold.py              # ViennaRNA RNAfold wrapper
│   │   ├── predictor.py             # 9-model ensemble predictor adapter
│   │   ├── docking.py               # AutoDock Vina adapter (mock) + hardware probe
│   │   └── spatial_rank.py          # Base-group interaction matrix ranker
│   ├── config/
│   │   ├── workflow.toml            # Workflow parameters
│   │   ├── tools.toml               # External tool paths
│   │   ├── llm.toml                 # LLM API configuration
│   │   └── spatial_interaction_matrix.csv  # 4x24 interaction matrix
│   ├── domain/
│   │   ├── enums.py                 # Step and Status enums
│   │   └── models.py                # Pydantic v2 data models
│   ├── llm/
│   │   ├── client.py                # OpenAI-compatible API client
│   │   └── skills.py                # Structured LLM prompts (6 skills)
│   ├── tui/
│   │   ├── app.py                   # Textual App, screen registry, step wiring
│   │   ├── styles/
│   │   │   └── main.tcss            # TUI stylesheet
│   │   ├── screens/
│   │   │   ├── welcome.py           # Welcome / run selection
│   │   │   ├── intake.py            # Step 1: Natural language intake
│   │   │   ├── structure.py         # Step 2: RNA secondary structure
│   │   │   ├── site_proposal.py     # Step 3: Mutation site proposal
│   │   │   ├── enumeration.py       # Step 4: Candidate enumeration
│   │   │   ├── scoring.py           # Step 5: Ensemble scoring
│   │   │   ├── specificity_filter.py # Step 6: Specificity filter
│   │   │   ├── docking_selection.py # Step 7: Docking parameter planning
│   │   │   ├── docking_run.py       # Step 8: Docking execution
│   │   │   ├── spatial_rank.py      # Step 9: Spatial interaction ranking
│   │   │   └── report.py            # Step 10: Final report
│   │   └── widgets/
│   │       └── common.py            # StepProgressBar, StatusPanel
│   └── workflow/
│       ├── engine.py                # DAG transition engine
│       ├── persistence.py           # JSON file persistence
│       └── state.py                 # RunState model
├── tests/
│   ├── test_tui.py                  # TUI screen navigation tests
│   ├── test_workflow.py             # Workflow engine tests
│   └── test_spatial_rank.py         # Spatial rank adapter tests
├── pyproject.toml
└── README.md
```

## Configuration

### LLM provider (`aptgent/config/llm.toml`)

```toml
[provider.openai]
base_url = "https://api.moonshot.cn/v1"
model = "kimi-k2-5"
api_key_env = "KIMI_API_KEY"
temperature = 1
max_tokens = 4096
```

Change `base_url` and `model` to use any OpenAI-compatible API.

### Workflow parameters (`aptgent/config/workflow.toml`)

```toml
[enumeration]
max_candidates = 5000
default_edit_ratio_threshold = 0.3

[docking]
enabled = false
top_k_strategy = "auto"
```

## Tested Dependency Versions

| Package      | Version    |
|--------------|------------|
| Python       | 3.9        |
| Textual      | 8.2.3      |
| Pydantic     | 2.13.0     |
| RDKit        | 2023.09.5  |
| NumPy        | 1.24.x     |
| scikit-learn | 1.3+       |
| XGBoost      | 2.0+       |
| PyTorch      | 1.12+      |
| ViennaRNA    | 2.6+       |

## License

MIT
