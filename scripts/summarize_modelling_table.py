"""Print a deterministic EDA summary for the durable modelling table."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tourism_pricing_analytics.analysis.eda import modelling_table_summary
from tourism_pricing_analytics.analysis.loader import DEFAULT_MODELLING_TABLE, load_modelling_table


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path",
        type=Path,
        default=DEFAULT_MODELLING_TABLE,
        help=f"Parquet table to summarize (default: {DEFAULT_MODELLING_TABLE}).",
    )
    parser.add_argument(
        "--include-guest-house",
        action="store_true",
        help="Include Guest house rows in the self-catering segment summary.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Optional JSON output path. The summary is always printed.",
    )
    args = parser.parse_args()

    frame = load_modelling_table(args.path)
    summary = modelling_table_summary(
        frame,
        include_guest_house=args.include_guest_house,
    )
    payload = json.dumps(summary, indent=2, sort_keys=True)
    print(payload)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
