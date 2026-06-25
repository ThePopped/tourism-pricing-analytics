"""Run a deterministic comparable-set benchmark from the modelling table."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tourism_pricing_analytics.analysis.competitors import (
    ComparableBenchmarkConfig,
    comparable_benchmarks,
)
from tourism_pricing_analytics.analysis.loader import DEFAULT_MODELLING_TABLE, load_modelling_table
from tourism_pricing_analytics.analysis.segment import segment_self_catering


def _default_subject_urls(frame, limit: int) -> list[str]:
    segment = segment_self_catering(frame)
    grouped = (
        segment.groupby(["property_url", "property_name"], dropna=False)
        .size()
        .reset_index(name="price_row_count")
    )
    selected = grouped.sort_values(
        ["price_row_count", "property_name", "property_url"],
        ascending=[False, True, True],
    ).head(limit)
    return [str(value) for value in selected["property_url"].tolist()]


def _resolve_subject_urls(frame, args: argparse.Namespace) -> list[str]:
    urls = list(args.subject_url or [])
    if urls:
        return urls
    return _default_subject_urls(frame, args.limit)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path",
        type=Path,
        default=DEFAULT_MODELLING_TABLE,
        help=f"Parquet table to benchmark (default: {DEFAULT_MODELLING_TABLE}).",
    )
    parser.add_argument(
        "--subject-url",
        action="append",
        default=None,
        help="Subject property URL to benchmark. Repeat for multiple subjects.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Number of deterministic default subjects when no URL is supplied.",
    )
    parser.add_argument(
        "--max-peers",
        type=int,
        default=ComparableBenchmarkConfig.max_peers,
        help="Maximum peer properties per subject.",
    )
    parser.add_argument(
        "--min-peers",
        type=int,
        default=ComparableBenchmarkConfig.min_peers,
        help="Minimum peer properties before a weak-set flag is emitted.",
    )
    parser.add_argument(
        "--max-distance-km",
        type=float,
        default=ComparableBenchmarkConfig.max_distance_km,
        help="Maximum geographic distance for candidate peers.",
    )
    parser.add_argument(
        "--min-peer-price-rows",
        type=int,
        default=ComparableBenchmarkConfig.min_peer_price_rows,
        help="Minimum matched peer price rows before a sparse-coverage flag is emitted.",
    )
    parser.add_argument(
        "--include-guest-house",
        action="store_true",
        help="Include Guest house rows in the self-catering segment.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Optional JSON output path. The benchmark is always printed.",
    )
    args = parser.parse_args()

    frame = load_modelling_table(args.path)
    subject_urls = _resolve_subject_urls(frame, args)
    config = ComparableBenchmarkConfig(
        max_peers=args.max_peers,
        min_peers=args.min_peers,
        max_distance_km=args.max_distance_km,
        min_peer_price_rows=args.min_peer_price_rows,
    )
    payload = {
        "source_table": str(args.path),
        "subject_urls": subject_urls,
        "benchmarks": comparable_benchmarks(
            frame,
            subject_urls,
            config,
            include_guest_house=args.include_guest_house,
        ),
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    print(text)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
