# Listing Discovery Plan — Gerani Comparable Expansion

## Goal

The downstream report/hedonic subject is **"Stavros Villas & Apartments"**
(`https://www.booking.com/hotel/gr/stavros-villas-amp-apartments.en-gb.html`),
added as the first entry in `config/booking_scraper_config.json`. **"Stavros" is
the property's name, not its location** — it actually sits in **Gerani, Chania**
(west-coast strip, ~13 km west of Chania town; approx lat 35.520, lon 23.870),
the opposite direction from Stavros/Akrotiri.

The local self-catering supply around Gerani is under-represented in the current
scrape. We are building an **automated listing-discovery module** that collects
~50–100 *similar* self-catering listing URLs around Gerani and **adds** them
(does not replace) to the live scraper's target list, so a re-scrape enriches the
local peer set and the hedonic training population.

Locked scope decisions (with the user):
- Area: **Gerani + immediate neighbours** (west-coast strip).
- Count: **up to 100** new candidate properties.
- Mode: **add**, not replace. Existing ~154 self-catering / 438 total properties
  stay as training data; the comparables engine distance-filters per subject, so
  non-local properties never pollute the Gerani peer set.

## Comparables gap (why this is needed)

Against the corrected Gerani coordinates (35.520, 23.870), the existing committed
modelling table has only:

| Radius from Gerani | Scraped self-catering peers |
| ---: | ---: |
| 3 km | 6 |
| 5 km | 10 |
| 8 km | 16 |
| 12 km | 28 |

Yet Booking lists ~48 self-catering properties **in Gerani alone** (Apartments
28, Villas 12, Holiday homes 8), and the adjacent strip adds many more. So the
west-coast strip is materially under-scraped relative to available supply.

(Note: the *first* data-quality pass in this work used the wrong location —
Stavros/Akrotiri, ~35.59/24.13 — and reported only 5 peers within 8 km. That was
based on the property name, not its real Gerani location. Disregard it.)

## Live research findings (Booking.com, captured 2026-06-28)

- **Card selectors still valid.** Today's DOM still uses
  `[data-testid="property-card"]`, `a[data-testid="title-link"]`,
  `[data-testid="title"]`, `[data-testid="price-and-discounted-price"]`. The
  existing pure parser `listings.parse_listings` works unchanged.
- **Self-catering type filter:** `nflt=ht_id=201;ht_id=213;ht_id=220` →
  Apartments (201), Villas (213), Holiday homes (220). Aparthotels self-classify
  under Apartments. (Other codes seen: 204 Hotels, 216 Guest houses, 206 Resorts,
  208 B&B, 203 Hostels, 222 Homestays, 223 Country houses.)
- **Pagination is offset-based:** `&offset=25,50,…` returns fresh pages of 25
  cards. No infinite-scroll dependency required. No reliable "load more" button.
- **Text-destination resolution is flaky.** An "Akrotiri" search resolved to a
  same-named hotel and showed fallback results ("No properties found" + nearby).
  A curated village list (or a map bounding box) is more reliable than free text.
- **Subject confirmed in Gerani:** a `ss=Gerani, Chania, Crete, Greece` search
  returns the subject property and ~53 properties (~48 self-catering).
- Dateless discovery is intentional: we only need stable URLs; adding
  checkin/checkout would gate on availability and drop relevant listings.
  Occupancy mirrors the controlled 2-guest scrape via `default_search`.

## Architecture

The pre-existing discovery flow had a **manual gap**: someone hand-saved
`listings_chania.html`, then `parse_listings` → `extract_listing_candidates.py`
(→ CSV) → `generate_full_config.py` (→ config). The new module automates the
navigation that produces those candidates.

Design principle (matches the repo): keep parsing pure; every decision is a pure,
unit-testable function; only a thin browser layer touches Playwright.

## Status

### DONE

- [x] Added subject to `config/booking_scraper_config.json` (first entry).
- [x] **`tourism_pricing_analytics/scraping/booking/discovery.py`** (new module),
      compiles. Contents:
  - `DiscoveryConfig` dataclass: `areas`, `ht_ids`, `max_per_area` (75),
    `max_total` (100), `max_pages_per_area` (8), `page_size` (25), with validation.
  - `DEFAULT_SEARCH_AREAS`: Gerani, Platanias, Maleme, Agia Marina, Kontomari,
    Tavronitis, Kolymbari (all "…, Chania, Crete, Greece").
  - `SELF_CATERING_HT_IDS = (201, 213, 220)`.
  - Pure: `build_search_url(...)`, `detect_blocked_page(...)`,
    `should_stop_pagination(...)`, `merge_candidates(...)`.
  - Thin browser layer: `collect_area_candidates(page, …)` (offset pagination +
    `parse_listings` + blocked-page guard), `discover_candidates(context, …)`
    (loops areas, merges, dedups, excludes config URLs, caps at `max_total`).
- [x] **`scripts/discover_listings.py`** (new CLI), compiles. Launches Chromium
      from the browser config, runs `discover_candidates`, writes a candidate CSV
      in the **same schema as `extract_listing_candidates.py`**
      (`name,url,price_text,review_score_text,recommended_unit_text`) so it feeds
      straight into the config pipeline. Flags: `--config`, `--area` (repeatable),
      `--max-per-area`, `--max-total`, `--max-pages-per-area`, `--include-existing`,
      `--out` (default `data/sample/listings_gerani_candidates.csv`). Excludes
      already-configured URLs (incl. the subject) by default.
- [x] Memory written: `client-subject-property.md` (Gerani location fact).

### TODO (pick up here)

1. **Merge script — `scripts/merge_candidates_into_config.py`** (NOT yet created).
   A dedicated script (intentionally *not* `generate_full_config.py`, which forces
   the reduced scale-up matrix + headless and would corrupt the full-matrix
   baseline). Core is a pure, testable function, sketch:
   ```python
   def merge_candidate_rows(existing_targets, candidate_rows):
       """existing {name,url} kept verbatim first; append new canonicalized,
       deduped candidate rows. Returns (merged_targets, added_count)."""
   ```
   Uses `canonicalize_property_url`. CLI: `--config` (baseline to extend),
   `--candidates` (CSV), `--out` (default in-place). Writes JSON with
   `indent=2, ensure_ascii=False`.
2. **Tests — `tests/test_discovery.py`** (NOT yet created), pure logic, seed 10001:
   - `build_search_url`: `ss`, `nflt == "ht_id=201;ht_id=213;ht_id=220"` (decode
     with `parse_qs`), `group_adults=2`, `offset` present only when `>0`.
   - `should_stop_pagination`: max-pages hit, short final page, zero-new-candidates,
     and the keep-going case.
   - `detect_blocked_page`: positive markers + negative (normal results).
   - `merge_candidates`: dedup by canonical URL, `exclude_urls`, `max_total` cap,
     order preserved.
   - `merge_candidate_rows` (from the merge script): existing kept first, new
     appended, dupes/excludes dropped, count correct.
   - Optional: trim a real Gerani search-results page into
     `data/sample/raw_html/` as a fixture and assert `parse_listings` count.
3. **Full test sweep** per CLAUDE.md before committing this phase:
   `python -m compileall tourism_pricing_analytics scripts` and
   `python -m unittest discover -s tests` (was 228 tests OK).
4. **Commit** the discovery phase (module + script + merge script + tests +
   this plan + config subject entry).
5. **Run discovery live** (heavy, outward-facing — get user go-ahead):
   `python scripts/discover_listings.py --max-total 100`
   → review the CSV → `python scripts/merge_candidates_into_config.py` →
   re-scrape the combined target set → rebuild
   `data/modelling/modelling_table.parquet`.

## Important caveat for the re-scrape

The committed modelling table is a single vintage (run `20260623_222416_346202`,
check-ins 2026-06-30 … 2026-08-22). The comparables benchmark matches peers to
the subject on `(checkin, lead_time_days, stay_length_days)` windows, so for the
new properties to be comparable on the *same* windows, the cleanest path is a
**single combined re-scrape of the full target set** (consistent base date and
lead/stay matrix), not a separate new-vintage scrape stitched onto the old one.
The hedonic model uses lead/stay/season covariates (not absolute dates), so it is
more tolerant, but a single-vintage rebuild keeps both stages clean.

## Refinement option (deferred)

If the curated village list proves too loose/tight, add a **map bounding-box**
search (SW/NE lat-lon around 35.52/23.87) as a precision upgrade. Start with the
village list (robust, simple); precise distance-to-Gerani filtering is already
handled downstream by the comparables engine after the property scrape captures
real lat/lon.

## No new dependencies

Playwright and BeautifulSoup are already project dependencies.
