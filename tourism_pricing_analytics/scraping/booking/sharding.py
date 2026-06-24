"""Pure helpers for sharded Booking.com scrape orchestration."""

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from tourism_pricing_analytics.scraping.booking.io import save_jsonl_file
from tourism_pricing_analytics.scraping.booking.models import PropertyTarget
from tourism_pricing_analytics.scraping.booking.resume import (
    expected_property_dir,
    is_property_complete,
)
from tourism_pricing_analytics.scraping.booking.validation import load_jsonl_records


AGGREGATE_FILENAMES: tuple[str, ...] = (
    "room_inventory.jsonl",
    "price_rows.jsonl",
    "room_features.jsonl",
    "property_features.jsonl",
    "failures.jsonl",
)


@dataclass(frozen=True)
class IndexedTarget:
    """A property target with its stable one-based config index."""

    index: int
    target: PropertyTarget


def indexed_targets(targets: list[PropertyTarget]) -> list[IndexedTarget]:
    """Attach stable one-based indexes to configured targets."""

    return [
        IndexedTarget(index=index, target=target)
        for index, target in enumerate(targets, start=1)
    ]


def select_indexed_targets(
    all_targets: list[IndexedTarget],
    selected_targets: list[PropertyTarget],
) -> list[IndexedTarget]:
    """Return selected targets while preserving their full-config indexes."""

    selected_urls = {target.url for target in selected_targets}
    return [item for item in all_targets if item.target.url in selected_urls]


def pending_indexed_targets(
    run_dir: Path,
    targets: list[IndexedTarget],
    lead_times: list[int],
    stay_lengths: list[int],
    search_base_date: date | None = None,
) -> list[IndexedTarget]:
    """Return indexed targets whose persisted artifacts are incomplete."""

    return [
        item
        for item in targets
        if not is_property_complete(
            run_dir,
            item.index,
            item.target,
            lead_times,
            stay_lengths,
            search_base_date,
        )
    ]


def split_indexed_targets(
    targets: list[IndexedTarget],
    worker_count: int,
) -> list[list[IndexedTarget]]:
    """Split targets into deterministic contiguous shards."""

    if worker_count < 1:
        raise ValueError("worker_count must be at least 1.")

    shard_size, remainder = divmod(len(targets), worker_count)
    shards: list[list[IndexedTarget]] = []
    cursor = 0
    for worker_index in range(worker_count):
        count = shard_size + (1 if worker_index < remainder else 0)
        shards.append(targets[cursor : cursor + count])
        cursor += count
    return shards


def property_output_dirs_for_targets(
    run_dir: Path,
    targets: list[IndexedTarget],
) -> dict[str, Path]:
    """Return per-property output dirs keyed by property URL without creating them."""

    return {
        item.target.url: expected_property_dir(run_dir, item.index, item.target)
        for item in targets
    }


def load_property_artifact_records(
    run_dir: Path,
    targets: list[IndexedTarget],
    filename: str,
) -> list[dict]:
    """Load one artifact stream from per-property dirs in config order."""

    records: list[dict] = []
    for item in targets:
        artifact_path = expected_property_dir(run_dir, item.index, item.target) / filename
        if not artifact_path.exists():
            continue
        artifact_records, issues = load_jsonl_records(artifact_path)
        if issues:
            logging.warning(
                "Skipping malformed per-property artifact %s with %d parse issue(s)",
                artifact_path,
                len(issues),
            )
            continue
        records.extend(artifact_records)
    return records


def aggregate_run_artifacts(
    run_dir: Path,
    targets: list[IndexedTarget],
    filenames: tuple[str, ...] = AGGREGATE_FILENAMES,
) -> dict[str, int]:
    """Rebuild top-level JSONL streams from per-property artifacts."""

    counts: dict[str, int] = {}
    for filename in filenames:
        records = load_property_artifact_records(run_dir, targets, filename)
        save_jsonl_file(records, run_dir / filename)
        counts[filename] = len(records)
    return counts
