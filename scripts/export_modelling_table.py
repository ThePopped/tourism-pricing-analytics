"""Export a completed run's modelling table to a durable, committed Parquet.

Scrape run directories under ``saved_dom/runs/`` are git-ignored and local-only,
so downstream analytics has no stable input. This script rebuilds the Layer 2
modelling table from a run's persisted JSONL via the existing
``build_features_from_run`` and writes it to ``data/modelling/`` as Parquet,
which (unlike CSV) preserves dtypes.

Nested columns (lists / dicts such as ``amenities``, ``review_subscores``,
``nearby_poi``) are JSON-encoded to strings so the Parquet round-trip is exactly
lossless regardless of per-row schema variation; the analysis loader decodes
them back. The set of encoded columns is recorded so the contract stays explicit.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tourism_pricing_analytics.features.build_features import build_features_from_run

DEFAULT_RUNS_ROOT = REPO_ROOT / "saved_dom" / "runs"
DEFAULT_OUT = REPO_ROOT / "data" / "modelling" / "modelling_table.parquet"


def find_latest_run_dir(runs_root: Path) -> Path:
    """Return the most recent timestamped run dir that has a modelling table source."""

    candidates = [
        d
        for d in runs_root.iterdir()
        if d.is_dir() and (d / "price_rows.jsonl").exists()
    ]
    if not candidates:
        raise FileNotFoundError(f"No run directories with price_rows.jsonl under {runs_root}")
    # Directory names are sortable timestamps (YYYYMMDD_HHMMSS_micros).
    return max(candidates, key=lambda d: d.name)


def encode_nested_columns(frame: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """JSON-encode object columns that hold list/dict values; return encoded names.

    A column is encoded if any non-null value is a ``list`` or ``dict``. Nulls are
    preserved as nulls (not the string "null") so missingness survives the round
    trip. Encoding is deterministic (sorted keys) for reproducible output.
    """

    encoded: list[str] = []
    out = frame.copy()
    for column in out.columns:
        values = out[column]
        if values.map(lambda v: isinstance(v, (list, dict))).any():
            out[column] = values.map(
                lambda v: None if v is None else json.dumps(v, sort_keys=True, ensure_ascii=False)
            )
            encoded.append(column)
    return out, encoded


def export_modelling_table(run_dir: Path, out_path: Path) -> tuple[pd.DataFrame, list[str]]:
    """Build the modelling table from ``run_dir`` and write it to ``out_path``."""

    rows = build_features_from_run(run_dir)
    frame = pd.DataFrame(rows)
    encoded_frame, encoded_columns = encode_nested_columns(frame)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    encoded_frame.to_parquet(out_path, engine="pyarrow", index=False)
    return frame, encoded_columns


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=None,
        help="Run directory to export (defaults to the latest under saved_dom/runs/).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"Output Parquet path (default: {DEFAULT_OUT}).",
    )
    args = parser.parse_args()

    run_dir = args.run_dir or find_latest_run_dir(DEFAULT_RUNS_ROOT)
    frame, encoded = export_modelling_table(run_dir, args.out)
    print(f"Source run dir : {run_dir}")
    print(f"Wrote          : {args.out}")
    print(f"Rows x cols    : {frame.shape[0]} x {frame.shape[1]}")
    print(f"JSON-encoded   : {', '.join(encoded) or '(none)'}")


if __name__ == "__main__":
    main()
