"""Write a single client-facing competitive positioning narrative.

This reuses the hedonic report payload (the same assembly used by the workbook
and dashboard) and renders it as plain-language positioning prose rather than
the raw technical tables in ``competitor_report.md`` and ``hedonic_report.md``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_hedonic import _default_subject_url, _load_spec, _normalize_windows, build_report_payload
from tourism_pricing_analytics.analysis.competitors import ComparableBenchmarkConfig
from tourism_pricing_analytics.analysis.loader import DEFAULT_MODELLING_TABLE, load_modelling_table
from tourism_pricing_analytics.analysis.narrative import render_positioning_narrative

DEFAULT_REPORT_PATH = REPO_ROOT / "data" / "modelling" / "positioning_narrative.md"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=DEFAULT_MODELLING_TABLE)
    parser.add_argument("--subject-url", default=None)
    parser.add_argument("--spec-json", default=None)
    parser.add_argument("--spec-path", type=Path, default=None)
    parser.add_argument("--window", action="append", help="Benchmark window as JSON. Repeatable.")
    parser.add_argument("--max-peers", type=int, default=ComparableBenchmarkConfig.max_peers)
    parser.add_argument("--max-distance-km", type=float, default=ComparableBenchmarkConfig.max_distance_km)
    parser.add_argument("--min-token-frequency", type=int, default=25)
    parser.add_argument("--out", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args()

    frame = load_modelling_table(args.path)
    spec = _load_spec(args)
    if spec is not None and args.subject_url:
        raise SystemExit("Use either --subject-url or a spec, not both.")
    client: str | dict[str, Any] = spec or args.subject_url or _default_subject_url(frame)

    payload = build_report_payload(
        frame,
        source_table=str(args.path),
        client=client,
        windows=_normalize_windows(args.window),
        max_peers=args.max_peers,
        max_distance_km=args.max_distance_km,
        min_token_frequency=args.min_token_frequency,
    )
    narrative = render_positioning_narrative(payload)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(narrative, encoding="utf-8")
    print(narrative)

    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
