# Listing Discovery Plan - Gerani Comparable Expansion

Status: done (implemented 2026-06-28; later expanded into the 377-property
Gerani/Chania operating config)

The discovery implementation is complete: the browser-backed discovery module,
candidate CSV CLI, merge-into-config script, pure unit tests, and downstream
config expansion have all landed. This document is retained as design context
and as a reminder of the Gerani location correction that motivated the work.

## Goal

The downstream report/hedonic subject is **Stavros Villas & Apartments**
(`https://www.booking.com/hotel/gr/stavros-villas-amp-apartments.en-gb.html`),
which sits in **Gerani, Chania** (west-coast strip, about 13 km west of Chania
town; approx lat 35.520, lon 23.870). The name "Stavros" is not its location.

The local self-catering supply around Gerani was under-represented in the first
scrape. The goal of this plan was to collect similar self-catering listing URLs
around Gerani and add them to the live scraper target list, so a re-scrape could
enrich both the local peer set and the hedonic training population.

Locked scope decisions:

- Area: Gerani plus immediate west-coast neighbours.
- Count: up to 100 new candidate properties per discovery run.
- Mode: add, not replace. Existing Chania/Crete properties remain useful
  training data; the comparables engine distance-filters per subject.

## Comparables Gap

Against the corrected Gerani coordinates, the earlier committed modelling table
had only:

| Radius from Gerani | Scraped self-catering peers |
| ---: | ---: |
| 3 km | 6 |
| 5 km | 10 |
| 8 km | 16 |
| 12 km | 28 |

Booking listed about 48 self-catering properties in Gerani alone, with more in
the adjacent strip, so the west-coast peer market needed expansion.

The first data-quality pass accidentally used Stavros/Akrotiri coordinates
because it inferred location from the property name. Disregard that pass; the
client subject is in Gerani.

## Live Research Findings

Captured on Booking.com on 2026-06-28:

- Search-card selectors were still usable:
  `[data-testid="property-card"]`, `a[data-testid="title-link"]`,
  `[data-testid="title"]`, and `[data-testid="price-and-discounted-price"]`.
- Self-catering type filter:
  `nflt=ht_id=201;ht_id=213;ht_id=220` for apartments, villas, and holiday
  homes. Aparthotels self-classified under apartments.
- Pagination is offset-based (`offset=25`, `50`, etc.), so no infinite-scroll
  dependency is needed for discovery.
- Free-text destination resolution can be flaky; curated village names are more
  reliable than ambiguous destination text.
- Dateless discovery is intentional: the scraper only needs stable property
  URLs. Adding check-in/check-out dates would filter out relevant unavailable
  listings.

## Architecture

The old flow had a manual gap: save search-result HTML, parse it, extract CSV
candidates, then generate a config. The implemented discovery flow automates
the navigation while keeping parsing and merge decisions pure and testable.

Implemented components:

- `tourism_pricing_analytics/scraping/booking/discovery.py`
  - `DiscoveryConfig`
  - `DEFAULT_SEARCH_AREAS`
  - `SELF_CATERING_HT_IDS = (201, 213, 220)`
  - Pure helpers: `build_search_url`, `detect_blocked_page`,
    `should_stop_pagination`, `merge_candidates`
  - Browser helpers: `collect_area_candidates`, `discover_candidates`
- `scripts/discover_listings.py`
  - Runs live discovery and writes candidate CSV rows in the same schema as
    `extract_listing_candidates.py`.
- `scripts/merge_candidates_into_config.py`
  - Preserves the baseline config's search matrix, browser settings, retry
    policy, and existing properties.
  - Appends only canonicalized, deduplicated candidate URLs via
    `merge_candidate_rows`.
- `tests/test_discovery.py`
  - Covers URL construction, pagination stopping, blocked-page detection,
    candidate merging, merge-into-config behavior, and config-setting
    preservation.

## Completion Notes

- The subject property was added to `config/booking_scraper_config.json`.
- The discovery module, CLI, merge script, and tests were implemented and
  committed after the relevant compile/test sweep.
- Later work ran the expansion path and produced the current
  `config/booking_scraper_config.json` operating config with 377 targets.
- The full Chania scale-up config remains separately committed as
  `config/booking_scraper_config_chania_full.json`; it preserves all baseline
  targets first, including Stavros Villas & Apartments, then appends canonical
  Chania candidate URLs. The 2026-07-03 generated config has 788 unique targets.

When changing the target set again:

```powershell
python scripts\discover_listings.py --max-total 100
python scripts\merge_candidates_into_config.py --candidates data\sample\listings_gerani_candidates.csv
```

Then re-scrape the combined target set and rebuild
`data/modelling/modelling_table.parquet` so peer windows stay on one consistent
scrape vintage.

For a scale-up config, regenerate with:

```powershell
python scripts\generate_full_config.py
```

Do not replace baseline properties with candidate CSV rows. Baseline/client
targets should remain first so subject properties are always included in full
scrapes and dashboard refreshes.

## Re-Scrape Caveat

The comparables benchmark matches peers to the subject on
`(checkin, lead_time_days, stay_length_days)` windows. For newly added
properties to be comparable on the same windows, the cleanest path is a single
combined re-scrape of the full target set, not a separate new-vintage scrape
stitched onto older data.

## Deferred Refinement

If curated village discovery proves too loose or too tight, add a map
bounding-box search around Gerani as a precision upgrade. Distance-to-Gerani
filtering is already handled downstream once the property scrape captures real
lat/lon.

## Dependencies

No new dependencies were required; Playwright and BeautifulSoup were already in
the project dependency set.
