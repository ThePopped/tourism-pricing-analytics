"""Sharded orchestration entrypoint for the full Chania Booking.com scrape."""

import argparse
import logging
import multiprocessing
import random
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import CONFIG_DIR
from tourism_pricing_analytics.scraping.booking.config import load_scraper_config
from tourism_pricing_analytics.scraping.booking.io import create_run_dir, setup_logging
from tourism_pricing_analytics.scraping.booking.runner import (
    build_and_save_modelling_table,
    run,
    validate_and_report_run,
)
from tourism_pricing_analytics.scraping.booking.sharding import (
    aggregate_run_artifacts,
    indexed_targets,
    pending_indexed_targets,
    split_indexed_targets,
)


DEFAULT_FULL_CONFIG_PATH = CONFIG_DIR / "booking_scraper_config_chania_full.json"
DEFAULT_WORKER_COUNT = 3


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
    return parser.parse_args()


def _worker_entry(
    config_path: str,
    run_dir: str,
    worker_id: int,
    target_urls: list[str],
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
    setup_logging(run_path / f"scrape_debug_{worker_label}.log")
    logging.info("%s starting with %d assigned targets", worker_label, len(worker_targets))

    with sync_playwright() as playwright:
        run(
            playwright,
            scraper_config,
            run_path,
            target_slice=worker_targets,
            all_targets=scraper_config.properties,
            finalize_run=False,
            worker_id=worker_label,
        )

    logging.info("%s finished", worker_label)


def main() -> None:
    args = parse_args()
    if args.workers < 1:
        raise SystemExit("--workers must be at least 1")
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be at least 1 when provided")

    scraper_config = load_scraper_config(args.config)
    random.seed(scraper_config.seed)

    run_dir = args.run_dir or create_run_dir(scraper_config.output_root)
    run_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(run_dir / "scrape_debug.log")

    configured_targets = scraper_config.properties
    selected_targets = (
        configured_targets[: args.limit] if args.limit is not None else configured_targets
    )
    indexed_all_targets = indexed_targets(configured_targets)
    selected_urls = {target.url for target in selected_targets}
    indexed_selected_targets = [
        item for item in indexed_all_targets if item.target.url in selected_urls
    ]
    indexed_pending_targets = pending_indexed_targets(
        run_dir,
        indexed_selected_targets,
        scraper_config.lead_times,
        scraper_config.stay_lengths,
    )
    shards = split_indexed_targets(indexed_pending_targets, args.workers)

    logging.info("Run output directory: %s", run_dir)
    logging.info("Config path: %s", args.config)
    logging.info("Configured property count: %d", len(configured_targets))
    logging.info("Selected property count: %d", len(indexed_selected_targets))
    logging.info("Pending property count: %d", len(indexed_pending_targets))
    logging.info("Worker count: %d", args.workers)
    for worker_index, shard in enumerate(shards, start=1):
        logging.info("Worker %02d assigned %d pending targets", worker_index, len(shard))

    processes: list[multiprocessing.Process] = []
    for worker_index, shard in enumerate(shards, start=1):
        if not shard:
            continue
        process = multiprocessing.Process(
            target=_worker_entry,
            args=(
                str(args.config),
                str(run_dir),
                worker_index,
                [item.target.url for item in shard],
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

    artifact_counts = aggregate_run_artifacts(run_dir, indexed_all_targets)
    for filename, count in artifact_counts.items():
        logging.info("Aggregated %s records: %d", filename, count)

    validate_and_report_run(run_dir)
    build_and_save_modelling_table(run_dir)
    logging.info("Finished sharded scrape")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
