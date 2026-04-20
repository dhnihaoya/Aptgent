# Mutation Batch Prediction Protocol

## Overview

The `mutation-batch` subcommand in `runner.py` provides an accelerated pipeline for enumerating and scoring all mutants at selected sites. It uses subprocess isolation so heavy dependencies (RDKit, PyTorch, XGBoost) only need to be installed in the predictor runtime environment.

## Invocation

```
python -m aptgent.predictor_runtime.runner mutation-batch \
    --base-sequence ATGCGATC \
    --smiles "c1ccccc1" \
    --sites 1,3,5 \
    --progress-every 10000 \
    --sub-batch-size 65536
```

Sites can also be provided via `--sites-json path.json` (a JSON array of 0-indexed positions).

## Line-JSON Protocol

The subprocess emits one JSON object per line on stdout:

### ready
```json
{"type": "ready", "model_order": ["(1mer)...pkl", ...], "device": "cpu"}
```
Emitted once after models are loaded and CUDA is configured.

### progress
```json
{"type": "progress", "done": 10000, "total": 65536}
```
Emitted at intervals determined by `--progress-every`.

### hit
```json
{"type": "hit", "sequence": "ATGCTAGC", "mean_probability": 0.93, "model_probabilities": [0.92, 0.94, ...]}
```
Emitted for each positive hit (all 9 models predict binding).

### done
```json
{"type": "done", "total": 65536, "hits": 42}
```
Emitted when enumeration completes. May include `"cancelled": true`.

### error
```json
{"type": "error", "message": "..."}
```
Emitted on fatal error.

## Cancel

Write `cancel\n` to the subprocess stdin to abort enumeration early.

## Acceleration Techniques

1. **Descriptor hoisting**: 209 RDKit descriptors computed once for the target SMILES, tiled across all mutants.
2. **Vectorized k-mer**: Base-4 encoding + offset bincount produces `(N, 4^k)` frequency matrix in one NumPy call.
3. **Calibration**: Sample ≤64 mutants through all 9 models, sort by ascending positive count (most selective first).
4. **Cascade early exit**: Sequential filtering — each model only sees survivors from the previous.
5. **Chunked enumeration**: Fixed-size blocks (default 65,536) with in-place byte mutation via NumPy.
6. **CUDA**: PyTorch models moved to GPU at load time; XGBoost uses `DMatrix(device="cuda")`.

## Ensemble Rule

Strict: **all 9 models must predict binding** for ensemble_label == 1. The cascade naturally enforces this — any single model vetoing eliminates the candidate.
