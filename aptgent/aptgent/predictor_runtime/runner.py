"""Internal subprocess entrypoint for workflow batch prediction."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import threading
from pathlib import Path

from aptgent.predictor_runtime.paths import default_model_dir
from aptgent.protocol.cancel import StdinCancelWatcher
from aptgent.protocol.line_json import JsonlEmitter


def _find_col(header_lower: list[str], candidates: list[str]) -> int | None:
    for candidate in candidates:
        for index, header in enumerate(header_lower):
            if header == candidate:
                return index
    return None


def _write_batch_results(results: list[dict], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["candidate_id", "sequence", "smiles", "ensemble_label", "individual"]
        )
        for result in results:
            writer.writerow(
                [
                    result.get("id", ""),
                    result.get("sequence", ""),
                    result.get("smiles", ""),
                    result.get("ensemble_label", ""),
                    json.dumps(result.get("individual", {})),
                ]
            )


def cmd_predict(args: argparse.Namespace) -> int:
    from aptgent.predictor_runtime.predictor import EnsemblePredictor

    input_path = Path(args.input)
    output_path = Path(args.output)
    model_dir = Path(args.model_dir) if args.model_dir else default_model_dir()

    if not input_path.is_file():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    predictor = EnsemblePredictor(model_dir)

    with input_path.open("r", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        header_lower = [value.strip().lower() for value in header]
        seq_col = _find_col(header_lower, ["aptamer", "sequence", "seq", "aptamer sequence"])
        smiles_col = _find_col(header_lower, ["smiles"])
        id_col = _find_col(header_lower, ["candidate_id", "id"])

        if seq_col is None or smiles_col is None:
            raise ValueError(
                "CSV must contain at least 'sequence' and 'smiles' columns. "
                f"Found headers: {header}"
            )

        sequences: list[str] = []
        smiles_list: list[str] = []
        ids: list[str] = []
        for row in reader:
            if len(row) <= max(seq_col, smiles_col):
                continue
            sequence = row[seq_col].strip()
            smiles = row[smiles_col].strip()
            if not sequence or not smiles:
                continue
            sequences.append(sequence)
            smiles_list.append(smiles)
            if id_col is not None and len(row) > id_col:
                ids.append(row[id_col].strip())
            else:
                ids.append("")

    predict_kwargs: dict[str, object] = {}
    if any(ids):
        predict_kwargs["ids"] = ids
    results = predictor.predict_batch(sequences, smiles_list, **predict_kwargs)
    _write_batch_results(results, output_path)
    return 0


def cmd_mutation_batch(args: argparse.Namespace) -> int:
    from aptgent.predictor_runtime.cuda import get_device
    from aptgent.predictor_runtime.predictor import (
        EnsemblePredictor,
        PredictionCancelled,
    )

    model_dir = Path(args.model_dir) if args.model_dir else default_model_dir()
    predictor = EnsemblePredictor(model_dir)

    base_seq = args.base_sequence
    smiles = args.smiles
    progress_every = args.progress_every or 10000
    sub_batch_size = args.sub_batch_size or 65536
    skip_first = args.skip_first or 0

    # Parse sites
    if args.sites_json:
        sites_path = Path(args.sites_json)
        with sites_path.open("r") as f:
            sites = json.load(f)
    elif args.sites is not None:
        sites = [int(s.strip()) for s in args.sites.split(",")]
    else:
        raise SystemExit("Either --sites or --sites-json is required.")

    device = get_device()
    model_order = [fname for _, _, fname in predictor.models]
    emitter = JsonlEmitter(sys.stdout)

    # Emit ready signal
    emitter.emit({"type": "ready", "model_order": model_order, "device": device})

    cancel_event = threading.Event()
    _watcher = StdinCancelWatcher(cancel_event)  # noqa: F841 — daemon thread; prevent GC

    def _check_stdin_cancel() -> bool:
        return cancel_event.is_set()

    def _on_progress(done: int, total: int, info: dict) -> None:
        emitter.emit({"type": "progress", "done": done, "total": total})

    def _on_result(result: dict) -> None:
        emitter.emit({
            "type": "hit",
            "sequence": result["sequence"],
            "mean_probability": result["mean_probability"],
            "model_probabilities": result["model_probabilities"],
        })

    total = 4 ** len(sites)
    hits = 0

    try:
        def _counting_callback(result: dict) -> None:
            nonlocal hits
            hits += 1
            _on_result(result)

        predictor.predict_mutation_batch(
            base_seq,
            smiles,
            sites,
            batch_size=progress_every,
            sub_batch_size=sub_batch_size,
            progress_callback=_on_progress,
            should_cancel=_check_stdin_cancel,
            result_callback=_counting_callback,
            collect_results=False,
            skip_first=skip_first,
        )

        emitter.emit({"type": "done", "total": total, "hits": hits})

    except PredictionCancelled:
        emitter.emit({"type": "done", "total": total, "hits": hits, "cancelled": True})
        return 1
    except Exception as exc:
        emitter.emit({"type": "error", "message": str(exc)})
        return 1

    return 0


def cmd_specificity_batch(args: argparse.Namespace) -> int:
    """Run cross-prediction of a candidate list against a list of targets.

    Emits a streaming, line-JSON protocol that mirrors ``mutation-batch``:

    * ``ready`` once on startup
    * ``row``    per finalized (target, candidate) prediction
    * ``progress`` every ``--progress-every`` rows (and on target switch)
    * ``done``   on completion or cooperative cancel
    * ``error``  on unrecoverable failure

    Stdin accepts a single ``cancel`` line for soft cancellation, matching
    the mutation-batch protocol.
    """
    from aptgent.predictor_runtime.cuda import get_device
    from aptgent.predictor_runtime.predictor import (
        EnsemblePredictor,
        PredictionCancelled,
    )

    model_dir = Path(args.model_dir) if args.model_dir else default_model_dir()
    emitter = JsonlEmitter(sys.stdout)

    candidates_path = Path(args.candidates_json)
    targets_path = Path(args.targets_json)
    if not candidates_path.is_file():
        emitter.emit({"type": "error", "message": f"candidates json not found: {candidates_path}"})
        return 1
    if not targets_path.is_file():
        emitter.emit({"type": "error", "message": f"targets json not found: {targets_path}"})
        return 1

    with candidates_path.open("r", encoding="utf-8") as f:
        candidates = json.load(f)
    with targets_path.open("r", encoding="utf-8") as f:
        targets = json.load(f)

    if not isinstance(candidates, list) or not isinstance(targets, list):
        emitter.emit({"type": "error", "message": "candidates and targets must be JSON arrays"})
        return 1

    skip_pairs: set[tuple[int, str]] = set()
    if args.skip_pairs_json:
        try:
            with open(args.skip_pairs_json, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, list):
                for entry in raw:
                    if (
                        isinstance(entry, list)
                        and len(entry) == 2
                        and isinstance(entry[0], int)
                    ):
                        skip_pairs.add((entry[0], str(entry[1])))
        except (OSError, json.JSONDecodeError) as exc:
            emitter.emit({"type": "error", "message": f"failed to read skip_pairs_json: {exc}"})
            return 1

    progress_every = max(1, int(args.progress_every or 1))

    cancel_event = threading.Event()
    _watcher = StdinCancelWatcher(cancel_event)  # noqa: F841 — daemon thread; prevent GC

    try:
        predictor = EnsemblePredictor(model_dir)
    except Exception as exc:
        emitter.emit({"type": "error", "message": f"failed to load models: {exc}"})
        return 1

    device = get_device()
    model_order = [fname for _, _, fname in predictor.models]

    total = len(candidates) * len(targets)
    emitter.emit({
        "type": "ready",
        "device": device,
        "model_order": model_order,
        "total": total,
    })

    done = 0
    rows_since_progress = 0

    def _check_cancel() -> bool:
        return cancel_event.is_set()

    try:
        for target_idx, target in enumerate(targets):
            if cancel_event.is_set():
                break
            target_name = str(target.get("name", "") or "")
            smiles = str(target.get("smiles", "") or "")
            if not smiles:
                emitter.emit({
                    "type": "error",
                    "message": f"target {target_idx} ({target_name}) missing smiles",
                })
                return 1

            # Emit a target-switch progress beat so the UI can update the
            # "current target" label even before any row events arrive.
            emitter.emit({
                "type": "progress",
                "done": done,
                "total": total,
                "target_idx": target_idx,
                "target_name": target_name,
            })

            pending: list[tuple[str, str]] = []
            for candidate in candidates:
                cand_id = str(candidate.get("candidate_id", "") or "")
                sequence = str(candidate.get("sequence", "") or "")
                if (target_idx, cand_id) in skip_pairs:
                    continue
                if not sequence or not cand_id:
                    continue
                pending.append((cand_id, sequence))

            if not pending:
                continue

            sequences = [seq for _, seq in pending]
            smiles_list = [smiles] * len(pending)
            ids = [cand_id for cand_id, _ in pending]

            def _on_row(sample: dict, *, _target_idx=target_idx, _target_name=target_name) -> None:
                nonlocal done, rows_since_progress
                cand_id = str(sample.get("id", ""))
                emitter.emit({
                    "type": "row",
                    "target_idx": _target_idx,
                    "target_name": _target_name,
                    "candidate_id": cand_id,
                    "label": int(sample.get("ensemble_label", 0)),
                    "probability": float(sample.get("mean_probability", 0.0)),
                })
                done += 1
                rows_since_progress += 1
                if rows_since_progress >= progress_every or done == total:
                    emitter.emit({
                        "type": "progress",
                        "done": done,
                        "total": total,
                        "target_idx": _target_idx,
                        "target_name": _target_name,
                    })
                    rows_since_progress = 0

            predictor.predict_batch(
                sequences,
                smiles_list,
                ids=ids,
                row_callback=_on_row,
                should_cancel=_check_cancel,
            )

        if rows_since_progress:
            emitter.emit({"type": "progress", "done": done, "total": total})

        emitter.emit({"type": "done", "total": total, "cancelled": cancel_event.is_set()})

    except PredictionCancelled:
        emitter.emit({"type": "done", "total": total, "cancelled": True})
        return 1
    except Exception as exc:
        emitter.emit({"type": "error", "message": str(exc)})
        return 1

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m aptgent.predictor_runtime.runner",
        description="Internal predictor runner for Aptgent workflow batch scoring.",
    )
    parser.add_argument("--model-dir", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    predict = sub.add_parser("predict", help="Run batch prediction from an input CSV.")
    predict.add_argument("--input", "-i", required=True)
    predict.add_argument("--output", "-o", required=True)

    mut_batch = sub.add_parser(
        "mutation-batch",
        help="Enumerate mutants and batch-predict with cascade filtering.",
    )
    mut_batch.add_argument("--base-sequence", required=True)
    mut_batch.add_argument("--smiles", required=True)
    mut_batch.add_argument("--sites", default=None, help="Comma-separated 0-indexed sites")
    mut_batch.add_argument("--sites-json", default=None, help="JSON file with sites array")
    mut_batch.add_argument("--sub-batch-size", type=int, default=None)
    mut_batch.add_argument(
        "--progress-every",
        type=int,
        default=None,
        help="Emit a progress message after roughly this many candidates.",
    )
    mut_batch.add_argument("--skip-first", type=int, default=0,
                           help="Skip the first N candidates (for resume)")

    spec_batch = sub.add_parser(
        "specificity-batch",
        help="Stream cross-prediction of candidates against multiple targets.",
    )
    spec_batch.add_argument("--candidates-json", required=True,
                            help="Path to JSON file: [{candidate_id, sequence}, ...]")
    spec_batch.add_argument("--targets-json", required=True,
                            help="Path to JSON file: [{name, smiles}, ...]")
    spec_batch.add_argument(
        "--progress-every",
        type=int,
        default=1,
        help="Emit a progress message after this many row events.",
    )
    spec_batch.add_argument(
        "--skip-pairs-json",
        default=None,
        help="Optional JSON file with [[target_idx, candidate_id], ...] pairs to skip (resume).",
    )

    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "predict":
        return cmd_predict(args)
    if args.command == "mutation-batch":
        return cmd_mutation_batch(args)
    if args.command == "specificity-batch":
        return cmd_specificity_batch(args)
    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
