"""Generate the full Chania scrape config from the candidate CSV.

The validated 15-property ``config/booking_scraper_config.json`` baseline stays
untouched. This script derives the Scale-Up Pass config
(``config/booking_scraper_config_chania_full.json``) reproducibly from
``data/sample/listings_chania_candidates.csv`` so the 438-property target set is
regenerated from the committed candidate menu rather than hand-maintained.

It inherits browser/search/timeout/scroll/selector settings from the baseline
config and overrides only the Scale-Up levers:

- reduced price matrix: ``lead_times [7, 30, 60] x stay_lengths [4, 7]``
- speed settings: ``headless: true``, ``slow_mo_ms: 0``
- the full canonicalized, de-duplicated candidate property list

Usage::

    python scripts/generate_full_config.py
    python scripts/generate_full_config.py <candidates.csv> <output.json>
"""

import csv
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tourism_pricing_analytics.scraping.booking.urls import canonicalize_property_url

DEFAULT_BASELINE = PROJECT_ROOT / "config" / "booking_scraper_config.json"
DEFAULT_INPUT = PROJECT_ROOT / "data" / "sample" / "listings_chania_candidates.csv"
DEFAULT_OUTPUT = PROJECT_ROOT / "config" / "booking_scraper_config_chania_full.json"

# Scale-Up Pass locked decisions.
LEAD_TIMES = [7, 30, 60]
STAY_LENGTHS = [4, 7]


def load_targets(csv_path: Path) -> list[dict[str, str]]:
    """Read candidate rows, canonicalize URLs, and drop duplicate URLs.

    The first occurrence of each canonical URL wins so the output order follows
    the committed candidate CSV.
    """

    targets: list[dict[str, str]] = []
    seen: set[str] = set()
    with csv_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            url = canonicalize_property_url(row["url"].strip())
            if url in seen:
                continue
            seen.add(url)
            targets.append({"name": row["name"].strip(), "url": url})
    return targets


def build_config(baseline: dict, targets: list[dict[str, str]]) -> dict:
    config = dict(baseline)
    config["lead_times"] = list(LEAD_TIMES)
    config["stay_lengths"] = list(STAY_LENGTHS)
    config["browser"] = dict(baseline["browser"])
    config["browser"]["headless"] = True
    config["browser"]["slow_mo_ms"] = 0
    config["properties"] = targets
    return config


def main() -> None:
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_INPUT
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUTPUT

    if not csv_path.exists():
        raise SystemExit(f"Candidate CSV not found: {csv_path}")

    baseline = json.loads(DEFAULT_BASELINE.read_text(encoding="utf-8"))
    targets = load_targets(csv_path)
    if not targets:
        raise SystemExit(f"No candidate targets parsed from {csv_path}")

    config = build_config(baseline, targets)
    output_path.write_text(
        json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"Loaded {len(targets)} unique targets from {csv_path.name}")
    print(f"Matrix: lead_times {LEAD_TIMES} x stay_lengths {STAY_LENGTHS} "
          f"= {len(LEAD_TIMES) * len(STAY_LENGTHS)} dated windows + 1 inventory page")
    print(f"Wrote {output_path.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
