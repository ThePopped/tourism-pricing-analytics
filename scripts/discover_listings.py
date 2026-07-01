"""Discover self-catering listing candidates around the Gerani west-coast strip.

This is the automated front half of the target-discovery pipeline. It drives a
Playwright browser over Booking.com search results for a set of west-coast
destinations, type-filtered to self-catering, paginates them, and writes a
candidate CSV in the exact schema ``extract_listing_candidates.py`` emits -- so
the output flows straight into ``generate_full_config.py`` (or its
``--merge-into`` mode) to extend the live scraper's target list.

Usage::

    python scripts/discover_listings.py
    python scripts/discover_listings.py --max-total 100 --out data/sample/listings_gerani_candidates.csv
    python scripts/discover_listings.py --area "Gerani, Chania, Crete, Greece" --area "Maleme, Chania, Crete, Greece"
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tourism_pricing_analytics.scraping.booking.config import (
    DEFAULT_CONFIG_PATH,
    load_scraper_config,
)
from tourism_pricing_analytics.scraping.booking.discovery import (
    DEFAULT_SEARCH_AREAS,
    DiscoveryConfig,
    discover_candidates,
)

DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "sample" / "listings_gerani_candidates.csv"
FIELDNAMES = ["name", "url", "price_text", "review_score_text", "recommended_unit_text"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument(
        "--area",
        action="append",
        dest="areas",
        default=None,
        help="Search destination string. Repeatable. Defaults to the Gerani strip.",
    )
    parser.add_argument("--max-per-area", type=int, default=DiscoveryConfig.max_per_area)
    parser.add_argument("--max-total", type=int, default=DiscoveryConfig.max_total)
    parser.add_argument(
        "--max-pages-per-area", type=int, default=DiscoveryConfig.max_pages_per_area
    )
    parser.add_argument(
        "--include-existing",
        action="store_true",
        help="Do not exclude URLs already in the scraper config (keeps overlaps).",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def write_candidates(candidates, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        for candidate in candidates:
            writer.writerow(
                {
                    "name": candidate.name,
                    "url": candidate.url,
                    "price_text": candidate.price_text,
                    "review_score_text": candidate.review_score_text,
                    "recommended_unit_text": candidate.recommended_unit_text,
                }
            )


def main() -> None:
    args = parse_args()
    scraper_config = load_scraper_config(args.config)
    random.seed(scraper_config.seed)

    areas = tuple(args.areas) if args.areas else DEFAULT_SEARCH_AREAS
    discovery_config = DiscoveryConfig(
        areas=areas,
        max_per_area=args.max_per_area,
        max_total=args.max_total,
        max_pages_per_area=args.max_pages_per_area,
    )
    exclude_urls = () if args.include_existing else tuple(t.url for t in scraper_config.properties)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=scraper_config.browser.headless,
            slow_mo=scraper_config.browser.slow_mo_ms,
        )
        try:
            context = browser.new_context(
                user_agent=scraper_config.browser.user_agent,
                viewport={
                    "width": scraper_config.browser.viewport.width,
                    "height": scraper_config.browser.viewport.height,
                },
            )
            candidates = discover_candidates(
                context,
                scraper_config,
                discovery_config,
                exclude_urls=exclude_urls,
            )
        finally:
            browser.close()

    write_candidates(candidates, args.out)
    resolved_out = args.out.resolve()
    try:
        display_out = resolved_out.relative_to(PROJECT_ROOT)
    except ValueError:
        display_out = resolved_out
    print(f"Areas searched: {len(areas)}")
    print(f"Excluded already-configured URLs: {len(exclude_urls)}")
    print(f"Discovered {len(candidates)} new candidate properties")
    print(f"Wrote {display_out}")


if __name__ == "__main__":
    main()
