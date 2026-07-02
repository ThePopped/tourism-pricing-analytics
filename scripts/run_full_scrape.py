"""Sharded orchestration entrypoint for the full Chania Booking.com scrape."""

import argparse
import json
import logging
import multiprocessing
import random
import sys
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
    setup_logging,
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
    next_round_targets,
    pending_indexed_targets,
    split_indexed_targets,
)


DEFAULT_FULL_CONFIG_PATH = CONFIG_DIR / "booking_scraper_config_chania_full.json"
DEFAULT_WORKER_COUNT = 3
DEFAULT_BATCH_PER_WORKER = 1
MEMORY_STATS_FILENAME = "memory_stats.jsonl"
EXIT_CODE_MEMORY_LOW = 3


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
        help="Number of worker processes.",
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
            "Properties per worker per round; workers exit after each round to "
            "reclaim Python RSS. 0 or less disables batching (single round)."
        ),
    )
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=None,
        help="End the invocation cleanly after N rounds, for chunking across reboots.",
    )
    return parser.parse_args()


def _worker_entry(
    config_path: str,
    run_dir: str,
    worker_id: int,
    target_urls: list[str],
    search_base_date_iso: str,
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


def _run_round(
    config_path: Path,
    run_dir: Path,
    shards: list[list[IndexedTarget]],
    search_base_date: date,
) -> None:
    processes: list[multiprocessing.Process] = []
    for worker_index, shard in enumerate(shards, start=1):
        if not shard:
            continue
        process = multiprocessing.Process(
            target=_worker_entry,
            args=(
                str(config_path),
                str(run_dir),
                worker_index,
                [item.target.url for item in shard],
                search_base_date.isoformat(),
            ),
            name=f"booking-scrape-worker-{worker_index:02d}",
        )
        process.start()
        processes.append(process)

    failed_workers: list[tuple[str, int | None]] = []
    for process in processes:
        process.join()
        if process.exitcode != 0:
            failed_workers.append((process.name, process.exitcode))

    if failed_workers:
        for name, exitcode in failed_workers:
            logging.error("%s failed with exit code %s", name, exitcode)
        raise SystemExit(1)


def main() -> None:
    args = parse_args()
    if args.workers < 1:
        raise SystemExit("--workers must be at least 1")
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be at least 1 when provided")
    if args.max_rounds is not None and args.max_rounds < 1:
        raise SystemExit("--max-rounds must be at least 1 when provided")

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

    round_capacity = (
        args.workers * args.batch_per_worker if args.batch_per_worker > 0 else 0
    )

    logging.info("Run output directory: %s", run_dir)
    logging.info("Search base date: %s", search_base_date.isoformat())
    logging.info("Config path: %s", args.config)
    logging.info("Configured property count: %d", len(configured_targets))
    logging.info("Selected property count: %d", len(indexed_selected_targets))
    logging.info("Worker count: %d", args.workers)
    logging.info(
        "Batch per worker: %s",
        args.batch_per_worker if round_capacity else "unlimited",
    )

    thresholds = MemoryThresholds()
    baseline_sample = _try_sample_memory()
    baseline_nonpaged = baseline_sample.nonpaged_bytes if baseline_sample else None
    if baseline_sample is not None:
        _record_memory_sample(run_dir, 0, baseline_sample, baseline_sample.nonpaged_bytes)

    attempted_urls: set[str] = set()
    round_number = 0
    memory_low_stop = False

    while True:
        if args.max_rounds is not None and round_number >= args.max_rounds:
            logging.info("Reached --max-rounds %d; ending invocation", args.max_rounds)
            break

        pending = pending_indexed_targets(
            run_dir,
            indexed_selected_targets,
            scraper_config.lead_times,
            scraper_config.stay_lengths,
            search_base_date,
        )
        round_targets = next_round_targets(pending, attempted_urls, round_capacity)
        if not round_targets:
            logging.info("No pending unattempted targets remain; ending round loop")
            break

        round_number += 1
        sample = _try_sample_memory()
        if sample is not None and baseline_nonpaged is not None:
            _record_memory_sample(run_dir, round_number, sample, baseline_nonpaged)
            if is_memory_low(
                sample.available_bytes,
                sample.nonpaged_bytes,
                baseline_nonpaged,
                thresholds,
            ):
                memory_low_stop = True
                break

        attempted_urls.update(item.target.url for item in round_targets)
        shards = split_indexed_targets(round_targets, args.workers)
        logging.info(
            "Round %d: %d pending targets, scraping %d this round",
            round_number,
            len(pending),
            len(round_targets),
        )
        for worker_index, shard in enumerate(shards, start=1):
            logging.info(
                "Round %d worker %02d assigned %d targets",
                round_number,
                worker_index,
                len(shard),
            )
        _run_round(args.config, run_dir, shards, search_base_date)

    artifact_counts = aggregate_run_artifacts(run_dir, indexed_all_targets)
    for filename, count in artifact_counts.items():
        logging.info("Aggregated %s records: %d", filename, count)

    validate_and_report_run(run_dir)
    build_and_save_modelling_table(run_dir)

    if memory_low_stop:
        logging.error(
            "Memory low — stopped before round %d. Reboot, then rerun with "
            "--run-dir %s to resume.",
            round_number,
            run_dir,
        )
        raise SystemExit(EXIT_CODE_MEMORY_LOW)

    logging.info("Finished sharded scrape")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
