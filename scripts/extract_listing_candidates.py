"""Extract the candidate property list from a saved Booking.com listings page.

The full region-listing dump (e.g. ``listings_chania.html``) is kept local-only
and git-ignored because of its size, but the candidate property set it contains
is the menu for broadening the configured scrape targets. This helper parses
that saved HTML with the pure ``parse_listings`` parser and writes the candidates
to a small, committable CSV so the target set can be derived reproducibly instead
of living only inside a multi-megabyte HTML blob.

Usage::

    python scripts/extract_listing_candidates.py
    python scripts/extract_listing_candidates.py <input.html> <output.csv>
"""

import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tourism_pricing_analytics.scraping.booking.listings import parse_listings

DEFAULT_INPUT = PROJECT_ROOT / "data" / "sample" / "raw_html" / "listings_chania.html"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "sample" / "listings_chania_candidates.csv"

FIELDNAMES = ["name", "url", "price_text", "review_score_text", "recommended_unit_text"]


def main() -> None:
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_INPUT
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUTPUT

    if not input_path.exists():
        raise SystemExit(
            f"Listings HTML not found: {input_path}\n"
            "This dump is git-ignored/local-only; point the script at your copy."
        )

    candidates = parse_listings(input_path.read_text(encoding="utf-8"))

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

    print(f"Parsed {len(candidates)} candidates from {input_path.name}")
    print(f"Wrote {output_path.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
