"""Print the central scrape run registry as an aligned table.

Optionally backfill registry rows from existing run directories whose
orchestration settings were never recorded (settings columns show "-").
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tourism_pricing_analytics.scraping.booking.registry import (
    append_run_registry,
    build_run_summary,
)

DEFAULT_REGISTRY_PATH = REPO_ROOT / "data" / "run_registry.jsonl"

COLUMNS = (
    "run_id",
    "workers",
    "headless",
    "batch",
    "limit",
    "duration",
    "price_rows",
    "priced_props",
    "failures",
    "drift",
    "chal_t",
    "min_gib",
    "valid",
    "status",
)


def load_registry(registry_path: Path) -> list[dict]:
    if not registry_path.exists():
        return []
    rows: list[dict] = []
    for line in registry_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _fmt(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _fmt_duration(seconds: object) -> str:
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool):
        return "-"
    minutes, rest = divmod(int(round(seconds)), 60)
    return f"{minutes}m{rest:02d}s"


def registry_row_to_cells(row: dict) -> dict[str, str]:
    settings = row.get("settings") or {}
    artifact_counts = row.get("artifact_counts") or {}
    failure_summary = row.get("failure_summary") or {}
    by_category = failure_summary.get("by_category") or {}
    validation = row.get("validation") or {}
    return {
        "run_id": _fmt(row.get("run_id")),
        "workers": _fmt(settings.get("workers")),
        "headless": _fmt(settings.get("headless")),
        "batch": _fmt(settings.get("batch_per_worker")),
        "limit": _fmt(settings.get("limit")),
        "duration": _fmt_duration(row.get("duration_seconds")),
        "price_rows": _fmt(artifact_counts.get("price_rows.jsonl")),
        "priced_props": _fmt(row.get("priced_properties")),
        "failures": _fmt(failure_summary.get("total")),
        "drift": _fmt(by_category.get("selector_drift", 0)),
        "chal_t": _fmt(failure_summary.get("chal_t")),
        "min_gib": _fmt(row.get("min_available_gib")),
        "valid": _fmt(validation.get("is_valid")),
        "status": _fmt(row.get("status")),
    }


def render_table(rows: list[dict]) -> str:
    cell_rows = [registry_row_to_cells(row) for row in rows]
    widths = {
        column: max([len(column)] + [len(cells[column]) for cells in cell_rows])
        for column in COLUMNS
    }
    lines = [
        "  ".join(column.ljust(widths[column]) for column in COLUMNS).rstrip(),
        "  ".join("-" * widths[column] for column in COLUMNS).rstrip(),
    ]
    for cells in cell_rows:
        lines.append(
            "  ".join(cells[column].ljust(widths[column]) for column in COLUMNS).rstrip()
        )
    return "\n".join(lines)


def backfill_run_dirs(registry_path: Path, run_dirs: list[Path]) -> None:
    for run_dir in run_dirs:
        if not run_dir.is_dir():
            print(f"Skipping missing run directory: {run_dir}")
            continue
        summary = build_run_summary(
            run_dir,
            settings=None,
            started_at=None,
            finished_at=None,
            status="backfilled",
        )
        append_run_registry(registry_path, summary)
        print(f"Backfilled {run_dir.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_REGISTRY_PATH,
        help=f"Registry JSONL path (default: {DEFAULT_REGISTRY_PATH}).",
    )
    parser.add_argument(
        "--backfill",
        type=Path,
        nargs="+",
        default=None,
        help="Run directories to summarize and upsert before listing.",
    )
    args = parser.parse_args()

    if args.backfill:
        backfill_run_dirs(args.registry, args.backfill)

    rows = load_registry(args.registry)
    if not rows:
        print(f"No registry rows found at {args.registry}")
        return
    rows.sort(key=lambda row: str(row.get("created_at") or ""))
    print(render_table(rows))


if __name__ == "__main__":
    main()
