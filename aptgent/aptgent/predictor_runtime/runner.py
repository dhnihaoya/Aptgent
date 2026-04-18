"""Internal subprocess entrypoint for workflow batch prediction."""

from __future__ import annotations

import argparse
import csv
import json
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
        writer.writerow(["sequence", "smiles", "ensemble_label", "individual"])
        for result in results:
            writer.writerow(
                [
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

        if seq_col is None or smiles_col is None:
            raise ValueError(
                "CSV must contain at least 'sequence' and 'smiles' columns. "
                f"Found headers: {header}"
            )

        sequences: list[str] = []
        smiles_list: list[str] = []
        for row in reader:
            if len(row) <= max(seq_col, smiles_col):
                continue
            sequence = row[seq_col].strip()
            smiles = row[smiles_col].strip()
            if not sequence or not smiles:
                continue
            sequences.append(sequence)
            smiles_list.append(smiles)

    results = predictor.predict_batch(sequences, smiles_list)
    _write_batch_results(results, output_path)
    return 0


def cmd_mutation_search(args: argparse.Namespace) -> int:
    from aptgent.predictor_runtime.predictor import EnsemblePredictor

    model_dir = Path(args.model_dir) if args.model_dir else default_model_dir()
    predictor = EnsemblePredictor(model_dir)
    sites = [int(value) for value in args.sites.split(",") if value.strip()]
    results = predictor.predict_mutation_batch(
        args.sequence,
        args.smiles,
        sites,
    )
    payload = {
        "results": results[: args.top_k],
        "total_processed": 4 ** len(sites),
        "binding_hit_count": len(results),
    }
    print(json.dumps(payload))
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

    mutation = sub.add_parser(
        "mutation-search",
        help="Run accelerated mutation-space search for one sequence/target pair.",
    )
    mutation.add_argument("--sequence", required=True)
    mutation.add_argument("--smiles", required=True)
    mutation.add_argument("--sites", required=True)
    mutation.add_argument("--top-k", type=int, default=500)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "predict":
        return cmd_predict(args)
    if args.command == "mutation-search":
        return cmd_mutation_search(args)
    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
