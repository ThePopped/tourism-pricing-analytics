"""Append discovered Booking.com candidate targets to an existing scraper config.

This is the merge step for automated listing discovery. Unlike
``generate_full_config.py``, it preserves the baseline config's search matrix,
browser settings, retry policy, and every existing property, then appends only
new canonicalized candidate URLs from the discovery CSV.

Usage::

    python scripts/merge_candidates_into_config.py
    python scripts/merge_candidates_into_config.py --candidates data/sample/listings_gerani_candidates.csv
    python scripts/merge_candidates_into_config.py --out config/booking_scraper_config_gerani.json
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Iterable, Mapping

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tourism_pricing_analytics.scraping.booking.config import DEFAULT_CONFIG_PATH
from tourism_pricing_analytics.scraping.booking.urls import canonicalize_property_url

DEFAULT_CANDIDATES = PROJECT_ROOT / "data" / "sample" / "listings_gerani_candidates.csv"


def _clean_value(value: object) -> str:
    return str(value or "").strip()


def merge_candidate_rows(
    existing_targets: Iterable[Mapping[str, object]],
    candidate_rows: Iterable[Mapping[str, object]],
) -> tuple[list[dict[str, str]], int]:
    """Return existing targets plus new, deduplicated candidate targets.

    Existing targets are kept first and their display names are preserved, while
    URLs are canonicalized to match scraper config conventions. Candidate rows
    missing either ``name`` or ``url`` are ignored. Duplicates are compared by
    canonical URL, so query strings/fragments never create duplicate targets.
    """

    merged: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    for target in existing_targets:
        name = _clean_value(target.get("name"))
        url = _clean_value(target.get("url"))
        if not name or not url:
            continue
        canonical_url = canonicalize_property_url(url)
        if canonical_url in seen_urls:
            continue
        seen_urls.add(canonical_url)
        merged.append({"name": name, "url": canonical_url})

    existing_count = len(merged)

    for row in candidate_rows:
        name = _clean_value(row.get("name"))
        url = _clean_value(row.get("url"))
        if not name or not url:
            continue
        canonical_url = canonicalize_property_url(url)
        if canonical_url in seen_urls:
            continue
        seen_urls.add(canonical_url)
        merged.append({"name": name, "url": canonical_url})

    return merged, len(merged) - existing_count


def read_candidate_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def build_merged_config(
    baseline_config: Mapping[str, object],
    candidate_rows: Iterable[Mapping[str, object]],
) -> tuple[dict[str, object], int]:
    config = dict(baseline_config)
    merged_targets, added_count = merge_candidate_rows(
        baseline_config.get("properties", []),
        candidate_rows,
    )
    config["properties"] = merged_targets
    return config, added_count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output config path. Defaults to overwriting --config in place.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = args.out or args.config

    if not args.config.exists():
        raise SystemExit(f"Config JSON not found: {args.config}")
    if not args.candidates.exists():
        raise SystemExit(f"Candidate CSV not found: {args.candidates}")

    baseline = json.loads(args.config.read_text(encoding="utf-8"))
    candidate_rows = read_candidate_rows(args.candidates)
    merged_config, added_count = build_merged_config(baseline, candidate_rows)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(merged_config, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    total_targets = len(merged_config["properties"])
    relative_output = output_path.relative_to(PROJECT_ROOT)
    print(f"Loaded {len(candidate_rows)} candidate rows from {args.candidates.name}")
    print(f"Added {added_count} new properties; config now has {total_targets} targets")
    print(f"Wrote {relative_output}")


if __name__ == "__main__":
    main()
