"""Run-level result summaries and the central scrape run registry.

Pure helpers over already-persisted run artifacts. They enrich a run's
``run_metadata.json`` with settings, timing, and result roll-ups at finalize
time, and maintain the git-tracked ``data/run_registry.jsonl`` index with one
upserted row per run. The enriched per-run metadata object and the registry
row are the same object, so the two records cannot drift.
"""

import json
from datetime import datetime
from pathlib import Path

from tourism_pricing_analytics.scraping.booking.io import load_run_metadata
from tourism_pricing_analytics.scraping.booking.sharding import AGGREGATE_FILENAMES
from tourism_pricing_analytics.scraping.booking.validation import load_jsonl_records


FAILURES_FILENAME = "failures.jsonl"
PRICE_ROWS_FILENAME = "price_rows.jsonl"
MEMORY_STATS_FILENAME = "memory_stats.jsonl"
VALIDATION_REPORT_FILENAME = "validation_report.json"


def summarize_failures(run_dir: Path) -> dict:
    """Tally the top-level failure stream by category and challenge signals."""

    records, _issues = load_jsonl_records(run_dir / FAILURES_FILENAME)
    by_category: dict[str, int] = {}
    chal_t = 0
    err_aborted = 0
    for record in records:
        category = record.get("category")
        if isinstance(category, str) and category:
            by_category[category] = by_category.get(category, 0) + 1
        final_url = record.get("final_url")
        if isinstance(final_url, str) and "chal_t" in final_url:
            chal_t += 1
        exception_message = record.get("exception_message")
        if isinstance(exception_message, str) and "ERR_ABORTED" in exception_message:
            err_aborted += 1
    return {
        "by_category": dict(sorted(by_category.items())),
        "chal_t": chal_t,
        "err_aborted": err_aborted,
        "total": len(records),
    }


def count_priced_properties(run_dir: Path) -> int:
    """Count distinct property URLs that produced at least one price row."""

    records, _issues = load_jsonl_records(run_dir / PRICE_ROWS_FILENAME)
    return len(
        {
            record["property_url"]
            for record in records
            if isinstance(record.get("property_url"), str) and record["property_url"]
        }
    )


def min_available_gib(run_dir: Path) -> float | None:
    """Return the minimum available system RAM observed during the run, in GiB."""

    records, _issues = load_jsonl_records(run_dir / MEMORY_STATS_FILENAME)
    values = [
        record["available_bytes"]
        for record in records
        if isinstance(record.get("available_bytes"), (int, float))
        and not isinstance(record.get("available_bytes"), bool)
    ]
    if not values:
        return None
    return round(min(values) / 2**30, 2)


def read_validation_summary(run_dir: Path) -> dict | None:
    """Read ``validation_report.json`` down to its is_valid/issue_count core."""

    path = run_dir / VALIDATION_REPORT_FILENAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return {
        "is_valid": data.get("is_valid"),
        "issue_count": data.get("issue_count"),
    }


def count_artifact_records(run_dir: Path) -> dict[str, int]:
    """Count records in the aggregated top-level streams, for backfill use."""

    counts: dict[str, int] = {}
    for filename in AGGREGATE_FILENAMES:
        path = run_dir / filename
        if not path.exists():
            continue
        records, _issues = load_jsonl_records(path)
        counts[filename] = len(records)
    return counts


def build_run_summary(
    run_dir: Path,
    *,
    settings: dict | None,
    started_at: datetime | None,
    finished_at: datetime | None,
    status: str,
    artifact_counts: dict[str, int] | None = None,
) -> dict:
    """Merge existing run metadata with settings, timing, and result roll-ups.

    ``settings``/``started_at``/``finished_at`` may be ``None`` when backfilling
    historical runs whose orchestration settings were never recorded. When
    ``artifact_counts`` is omitted it is recomputed from the aggregated
    top-level JSONL streams.
    """

    if artifact_counts is None:
        artifact_counts = count_artifact_records(run_dir)
    duration_seconds = None
    if started_at is not None and finished_at is not None:
        duration_seconds = round((finished_at - started_at).total_seconds(), 1)

    summary = load_run_metadata(run_dir)
    summary.update(
        {
            "run_id": run_dir.name,
            "settings": settings,
            "status": status,
            "started_at": (
                started_at.isoformat(timespec="seconds") if started_at else None
            ),
            "finished_at": (
                finished_at.isoformat(timespec="seconds") if finished_at else None
            ),
            "duration_seconds": duration_seconds,
            "artifact_counts": artifact_counts,
            "priced_properties": count_priced_properties(run_dir),
            "failure_summary": summarize_failures(run_dir),
            "min_available_gib": min_available_gib(run_dir),
            "validation": read_validation_summary(run_dir),
        }
    )
    return summary


def append_run_registry(registry_path: Path, summary: dict) -> None:
    """Upsert the summary into the JSONL registry, keyed by ``run_id``.

    A resumed run finalizes more than once; the later row replaces the earlier
    one so the registry keeps exactly one row per run reflecting its final
    state.
    """

    run_id = summary.get("run_id")
    rows: list[dict] = []
    if registry_path.exists():
        for line in registry_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and row.get("run_id") != run_id:
                rows.append(row)
    rows.append(summary)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        "".join(
            f"{json.dumps(row, ensure_ascii=True, sort_keys=True)}\n" for row in rows
        ),
        encoding="utf-8",
    )
