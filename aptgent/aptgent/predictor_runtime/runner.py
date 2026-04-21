"""Internal subprocess entrypoint for workflow batch prediction."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from aptgent.predictor_runtime.paths import default_model_dir


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
    else:
        sites = [int(s.strip()) for s in args.sites.split(",")]

    device = get_device()
    model_order = [fname for _, _, fname in predictor.models]

    # Emit ready signal
    _emit({"type": "ready", "model_order": model_order, "device": device})

    cancelled = False

    def _check_stdin_cancel() -> bool:
        return cancelled

    def _on_progress(done: int, total: int, info: dict) -> None:
        _emit({"type": "progress", "done": done, "total": total})

    def _on_result(result: dict) -> None:
        _emit({
            "type": "hit",
            "sequence": result["sequence"],
            "mean_probability": result["mean_probability"],
            "model_probabilities": result["model_probabilities"],
        })

    # Background thread to read cancel from stdin
    import threading

    def _stdin_reader() -> None:
        nonlocal cancelled
        try:
            for line in sys.stdin:
                if line.strip() == "cancel":
                    cancelled = True
                    break
        except Exception:
            pass

    reader_thread = threading.Thread(target=_stdin_reader, daemon=True)
    reader_thread.start()

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

        _emit({"type": "done", "total": total, "hits": hits})

    except PredictionCancelled:
        _emit({"type": "done", "total": total, "hits": hits, "cancelled": True})
        return 1
    except Exception as exc:
        _emit({"type": "error", "message": str(exc)})
        return 1

    return 0


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


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
    mut_batch.add_argument("--output", default=None, help="Optional CSV output for hits")
    mut_batch.add_argument("--skip-first", type=int, default=0,
                           help="Skip the first N candidates (for resume)")

    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "predict":
        return cmd_predict(args)
    if args.command == "mutation-batch":
        return cmd_mutation_batch(args)
    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
