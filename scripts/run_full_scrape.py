"""Sharded orchestration entrypoint for the full Chania Booking.com scrape."""

import argparse
import json
import logging
import math
import multiprocessing
import random
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import CONFIG_DIR
from tourism_pricing_analytics.scraping.booking.config import load_scraper_config
from tourism_pricing_analytics.scraping.booking.io import (
    create_run_dir,
    resolve_run_search_base_date,
    save_run_metadata,
    save_jsonl_file,
    setup_logging,
)
from tourism_pricing_analytics.scraping.booking.registry import (
    append_run_registry,
    build_run_summary,
    inventory_freshness_payload,
)
from tourism_pricing_analytics.scraping.booking.memory_probe import (
    MemorySample,
    MemoryThresholds,
    is_memory_low,
    sample_system_memory,
)
from tourism_pricing_analytics.scraping.booking.runner import (
    build_and_save_modelling_table,
    run,
    validate_and_report_run,
)
from tourism_pricing_analytics.scraping.booking.sharding import (
    IndexedTarget,
    aggregate_run_artifacts,
    indexed_targets,
    next_dynamic_batch,
    pending_indexed_targets,
)
from tourism_pricing_analytics.scraping.booking.validation import load_jsonl_records


# The default full config runs headless (browser.headless=true). A controlled
# A/B (2026-07-05, first-100 slice, sequential, shared IP) found 8 headless
# workers with --batch-per-worker 1 the fastest and most memory-efficient arm,
# with coverage within one property of headed and challenge signals in the noise
# band. See session_notes.md "July 5 Worker/Headless A/B".
DEFAULT_FULL_CONFIG_PATH = CONFIG_DIR / "booking_scraper_config_chania_full.json"
DEFAULT_WORKER_COUNT = 8
DEFAULT_BATCH_PER_WORKER = 1
MEMORY_STATS_FILENAME = "memory_stats.jsonl"
EXIT_CODE_MEMORY_LOW = 3
REGISTRY_PATH = PROJECT_ROOT / "data" / "run_registry.jsonl"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the full Booking.com scrape with process sharding.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_FULL_CONFIG_PATH,
        help="Scraper config path.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKER_COUNT,
        help=(
            "Number of worker processes. Default 8 is the A/B sweet spot on the "
            "6-core/12-thread host; drop to 4 only when RAM is tight."
        ),
    )
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=None,
        help="Existing run directory to resume. A new run is created when omitted.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit to the first N configured properties for pilot runs.",
    )
    parser.add_argument(
        "--batch-per-worker",
        type=int,
        default=DEFAULT_BATCH_PER_WORKER,
        help=(
            "Properties per worker batch; workers exit after each batch to "
            "reclaim Python RSS. 0 or less creates one single-pass batch per worker."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=("full", "price-only"),
        default="full",
        help="Scrape mode. price-only reuses fresh inventory/property features.",
    )
    parser.add_argument(
        "--inventory-max-age-days",
        type=int,
        default=7,
        help="Freshness threshold for reusing inventory/property features in price-only mode.",
    )
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=None,
        help="End the invocation cleanly after N worker batches, for chunking across reboots.",
    )
    return parser.parse_args()


def _worker_entry(
    config_path: str,
    run_dir: str,
    worker_id: int,
    target_urls: list[str],
    search_base_date_iso: str,
    price_only: bool,
) -> None:
    from playwright.sync_api import sync_playwright

    scraper_config = load_scraper_config(Path(config_path))
    target_url_set = set(target_urls)
    worker_targets = [
        target for target in scraper_config.properties if target.url in target_url_set
    ]

    random.seed(scraper_config.seed + worker_id)
    worker_label = f"worker-{worker_id:02d}"
    run_path = Path(run_dir)
    search_base_date = date.fromisoformat(search_base_date_iso)
    setup_logging(run_path / f"scrape_debug_{worker_label}.log")
    logging.info("%s starting with %d assigned targets", worker_label, len(worker_targets))
    logging.info("%s search base date: %s", worker_label, search_base_date.isoformat())

    with sync_playwright() as playwright:
        run(
            playwright,
            scraper_config,
            run_path,
            target_slice=worker_targets,
            all_targets=scraper_config.properties,
            finalize_run=False,
            worker_id=worker_label,
            search_base_date=search_base_date,
            price_only=price_only,
        )

    logging.info("%s finished", worker_label)


def _try_sample_memory() -> MemorySample | None:
    try:
        return sample_system_memory()
    except OSError as error:
        logging.warning("Memory probe failed; skipping memory checks: %s", error)
        return None


def _record_memory_sample(
    run_dir: Path,
    round_number: int,
    sample: MemorySample,
    baseline_nonpaged: int,
) -> None:
    record = {
        "sampled_at": datetime.now().isoformat(timespec="seconds"),
        "round": round_number,
        "available_bytes": sample.available_bytes,
        "nonpaged_bytes": sample.nonpaged_bytes,
        "baseline_nonpaged_bytes": baseline_nonpaged,
    }
    with (run_dir / MEMORY_STATS_FILENAME).open("a", encoding="utf-8") as handle:
        handle.write(f"{json.dumps(record)}\n")
    gib = 1024**3
    logging.info(
        "Round %d memory: available %.2f GiB, nonpaged pool %.2f GiB (baseline %.2f GiB)",
        round_number,
        sample.available_bytes / gib,
        sample.nonpaged_bytes / gib,
        baseline_nonpaged / gib,
    )


@dataclass
class RunningWorker:
    process: multiprocessing.Process
    batch_number: int
    targets: list[IndexedTarget]


def _effective_batch_size(
    pending_count: int,
    worker_count: int,
    batch_per_worker: int,
) -> int:
    if batch_per_worker > 0:
        return batch_per_worker
    return max(1, math.ceil(pending_count / worker_count))


def effective_scrape_mode(requested_mode: str, freshness: dict) -> str:
    """Return the actual mode after applying inventory freshness policy."""

    if requested_mode != "price-only":
        return "full"
    return "price_only" if freshness.get("is_stale") is False else "full"


def _memory_allows_scheduling(
    run_dir: Path,
    sample_number: int,
    baseline_nonpaged: int | None,
    thresholds: MemoryThresholds,
) -> bool:
    sample = _try_sample_memory()
    if sample is None or baseline_nonpaged is None:
        return True
    _record_memory_sample(run_dir, sample_number, sample, baseline_nonpaged)
    return not is_memory_low(
        sample.available_bytes,
        sample.nonpaged_bytes,
        baseline_nonpaged,
        thresholds,
    )


def _start_worker(
    *,
    config_path: Path,
    run_dir: Path,
    worker_id: int,
    batch: list[IndexedTarget],
    search_base_date: date,
    price_only: bool,
) -> RunningWorker:
    process = multiprocessing.Process(
        target=_worker_entry,
        args=(
            str(config_path),
            str(run_dir),
            worker_id,
            [item.target.url for item in batch],
            search_base_date.isoformat(),
            price_only,
        ),
        name=f"booking-scrape-worker-{worker_id:02d}",
    )
    process.start()
    logging.info(
        "Started worker batch %02d with %d target(s): %s",
        worker_id,
        len(batch),
        ", ".join(str(item.index) for item in batch),
    )
    return RunningWorker(process=process, batch_number=worker_id, targets=batch)


def _run_dynamic_queue(
    *,
    config_path: Path,
    run_dir: Path,
    pending: list[IndexedTarget],
    worker_count: int,
    batch_per_worker: int,
    search_base_date: date,
    baseline_nonpaged: int | None,
    thresholds: MemoryThresholds,
    max_batches: int | None,
    price_only: bool,
) -> tuple[int, bool, str]:
    """Run pending targets through a dynamic parent-side process queue."""

    running: list[RunningWorker] = []
    attempted_urls: set[str] = set()
    scheduled_batches = 0
    completed_batches = 0
    memory_halt = False
    stop_reason = "completed"
    batch_size = _effective_batch_size(len(pending), worker_count, batch_per_worker)

    while True:
        while len(running) < worker_count:
            if memory_halt:
                break
            if max_batches is not None and scheduled_batches >= max_batches:
                stop_reason = "max_rounds_stop"
                break

            batch = next_dynamic_batch(pending, attempted_urls, batch_size)
            if not batch:
                break

            if not _memory_allows_scheduling(
                run_dir,
                scheduled_batches + completed_batches + 1,
                baseline_nonpaged,
                thresholds,
            ):
                memory_halt = True
                stop_reason = "memory_halt"
                logging.warning("Memory threshold hit before scheduling another worker")
                break

            scheduled_batches += 1
            attempted_urls.update(item.target.url for item in batch)
            running.append(
                _start_worker(
                    config_path=config_path,
                    run_dir=run_dir,
                    worker_id=scheduled_batches,
                    batch=batch,
                    search_base_date=search_base_date,
                    price_only=price_only,
                )
            )

        if not running:
            break

        completed_now: list[RunningWorker] = []
        while not completed_now:
            for worker in running:
                if not worker.process.is_alive():
                    worker.process.join()
                    completed_now.append(worker)
            if completed_now:
                break
            time.sleep(0.25)

        for worker in completed_now:
            running.remove(worker)
            if worker.process.exitcode != 0:
                logging.error(
                    "%s failed with exit code %s",
                    worker.process.name,
                    worker.process.exitcode,
                )
                for other in running:
                    other.process.terminate()
                    other.process.join(timeout=5)
                raise SystemExit(1)

            completed_batches += 1
            logging.info(
                "Completed worker batch %02d (%d/%d scheduled)",
                worker.batch_number,
                completed_batches,
                scheduled_batches,
            )
            if not _memory_allows_scheduling(
                run_dir,
                scheduled_batches + completed_batches,
                baseline_nonpaged,
                thresholds,
            ):
                memory_halt = True
                stop_reason = "memory_halt"
                logging.warning("Memory threshold hit after worker completion")

        if memory_halt:
            # Let already-running workers finish, but do not schedule replacements.
            continue

    return completed_batches, memory_halt, stop_reason


def _copy_fresh_inventory_artifacts(
    *,
    source_run_dir: Path,
    destination_run_dir: Path,
    selected_urls: set[str],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for filename in ("room_inventory.jsonl", "property_features.jsonl"):
        records, issues = load_jsonl_records(source_run_dir / filename)
        if issues:
            logging.warning(
                "Inventory source artifact %s had %d parse issue(s); copying clean rows only",
                source_run_dir / filename,
                len(issues),
            )
        filtered = [
            record
            for record in records
            if not selected_urls or record.get("property_url") in selected_urls
        ]
        save_jsonl_file(filtered, destination_run_dir / filename)
        counts[filename] = len(filtered)
        logging.info(
            "Hydrated %s with %d record(s) from %s",
            filename,
            len(filtered),
            source_run_dir.name,
        )
    return counts


def main() -> None:
    run_started_at = datetime.now()
    args = parse_args()
    if args.workers < 1:
        raise SystemExit("--workers must be at least 1")
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be at least 1 when provided")
    if args.max_rounds is not None and args.max_rounds < 1:
        raise SystemExit("--max-rounds must be at least 1 when provided")
    if args.inventory_max_age_days < 0:
        raise SystemExit("--inventory-max-age-days must be nonnegative")

    scraper_config = load_scraper_config(args.config)
    random.seed(scraper_config.seed)

    run_dir = args.run_dir or create_run_dir(scraper_config.output_root)
    run_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(run_dir / "scrape_debug.log")
    search_base_date = resolve_run_search_base_date(run_dir)

    configured_targets = scraper_config.properties
    selected_targets = (
        configured_targets[: args.limit] if args.limit is not None else configured_targets
    )
    indexed_all_targets = indexed_targets(configured_targets)
    selected_urls = {target.url for target in selected_targets}
    indexed_selected_targets = [
        item for item in indexed_all_targets if item.target.url in selected_urls
    ]

    inventory_freshness = inventory_freshness_payload(
        REGISTRY_PATH,
        scraper_config.output_root,
        max_age_days=args.inventory_max_age_days,
    )
    effective_mode = effective_scrape_mode(args.mode, inventory_freshness)
    source_run_dir = (
        Path(inventory_freshness["source_run_dir"])
        if effective_mode == "price_only"
        and isinstance(inventory_freshness.get("source_run_dir"), str)
        else None
    )

    logging.info("Run output directory: %s", run_dir)
    logging.info("Search base date: %s", search_base_date.isoformat())
    logging.info("Config path: %s", args.config)
    logging.info("Configured property count: %d", len(configured_targets))
    logging.info("Selected property count: %d", len(indexed_selected_targets))
    logging.info("Worker count: %d", args.workers)
    logging.info(
        "Batch per worker: %s",
        args.batch_per_worker if args.batch_per_worker > 0 else "single pass",
    )
    logging.info(
        "Requested mode: %s; effective mode: %s",
        args.mode,
        effective_mode,
    )
    logging.info("Inventory freshness: %s", json.dumps(inventory_freshness, sort_keys=True))

    thresholds = MemoryThresholds()
    baseline_sample = _try_sample_memory()
    baseline_nonpaged = baseline_sample.nonpaged_bytes if baseline_sample else None
    if baseline_sample is not None:
        _record_memory_sample(run_dir, 0, baseline_sample, baseline_sample.nonpaged_bytes)

    pending = pending_indexed_targets(
        run_dir,
        indexed_selected_targets,
        scraper_config.lead_times,
        scraper_config.stay_lengths,
        search_base_date,
        price_only=effective_mode == "price_only",
    )
    logging.info("Pending selected targets: %d", len(pending))

    worker_batches_completed, memory_low_stop, status = _run_dynamic_queue(
        config_path=args.config,
        run_dir=run_dir,
        pending=pending,
        worker_count=args.workers,
        batch_per_worker=args.batch_per_worker,
        search_base_date=search_base_date,
        baseline_nonpaged=baseline_nonpaged,
        thresholds=thresholds,
        max_batches=args.max_rounds,
        price_only=effective_mode == "price_only",
    )

    artifact_counts = aggregate_run_artifacts(run_dir, indexed_all_targets)
    if effective_mode == "price_only" and source_run_dir is not None:
        artifact_counts.update(
            _copy_fresh_inventory_artifacts(
                source_run_dir=source_run_dir,
                destination_run_dir=run_dir,
                selected_urls=selected_urls,
            )
        )
    for filename, count in artifact_counts.items():
        logging.info("Aggregated %s records: %d", filename, count)

    validate_and_report_run(run_dir)
    build_and_save_modelling_table(run_dir)

    settings = {
        "scheduler": "dynamic_queue",
        "workers": args.workers,
        "batch_per_worker": args.batch_per_worker,
        "limit": args.limit,
        "config": str(args.config),
        "max_rounds": args.max_rounds,
        "headless": scraper_config.browser.headless,
        "seed": scraper_config.seed,
        "requested_mode": args.mode,
        "effective_mode": effective_mode,
        "mode": effective_mode,
        "inventory_max_age_days": args.inventory_max_age_days,
        "inventory_source_run_id": inventory_freshness.get("latest_inventory_run_id")
        if effective_mode == "price_only"
        else None,
        "inventory_freshness": inventory_freshness,
        "worker_batches_completed": worker_batches_completed,
        "memory_halt": memory_low_stop,
    }
    summary = build_run_summary(
        run_dir,
        settings=settings,
        started_at=run_started_at,
        finished_at=datetime.now(),
        status=status,
        artifact_counts=artifact_counts,
    )
    save_run_metadata(run_dir, summary)
    append_run_registry(REGISTRY_PATH, summary)
    logging.info("Run registry updated: %s", REGISTRY_PATH)

    if memory_low_stop:
        logging.error(
            "Memory low — stopped before round %d. Reboot, then rerun with "
            "--run-dir %s to resume.",
            worker_batches_completed + 1,
            run_dir,
        )
        raise SystemExit(EXIT_CODE_MEMORY_LOW)

    logging.info("Finished sharded scrape")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
