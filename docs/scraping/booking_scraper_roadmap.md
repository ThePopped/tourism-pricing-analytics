# Booking Scraper Roadmap

Status: core roadmap done; keep this file as the scraper acceptance gate

The Booking.com ingestion pipeline has moved from exploratory scraper to
package-based, resumable, validated, feature-producing ingestion. The original
build/harden phases, the feature-extraction layer, the scale-up
driver, and the later memory-bounded worker recycling pass are implemented.

Future scraper changes should use this file as the validation checklist rather
than as an open implementation backlog.

## Objective

Maintain a repeatable Booking.com ingestion pipeline that:

1. Discovers candidate Booking.com properties.
2. Captures room inventory from undated property pages.
3. Captures dated price rows across configurable lead/stay windows.
4. Captures room/property feature streams.
5. Saves structured output and validation reports for downstream analytics.

## Implemented Architecture

The scraper is package-based, with `notebooks/property_page_scraper.py` serving
as the thin manual entrypoint. Reusable logic lives under
`tourism_pricing_analytics/scraping/booking/`.

Implemented pieces:

- Config loading from `config/booking_scraper_config.json`.
- Canonical property URLs, date-window generation, and direct dated URLs.
- Undated room-inventory extraction.
- Dated price-row extraction.
- Room/property feature extraction and feature JSONL streams.
- JSONL persistence for inventory, prices, features, and failures.
- Per-property output directories and failure snapshots.
- Explicit failure categories.
- Retry/backoff for transient failures.
- Artifact-based resumability.
- Process-sharded full-scrape orchestration in `scripts/run_full_scrape.py`.
- Aggregate stream rebuilding from per-property artifacts.
- Structured run-output validation and `validation_report.json`.
- Modelling-table build from completed run artifacts.
- Memory-bounded scrape rounds via short-lived worker batches and
  `memory_stats.jsonl`.

## Completed Build Phases

- [x] Stabilize configuration.
- [x] Separate browser orchestration, parsing, persistence, and runner logic.
- [x] Implement room inventory extraction.
- [x] Implement dated price extraction.
- [x] Build typed data models.
- [x] Persist structured outputs.
- [x] Improve error handling and failure classification.
- [x] Add unit and fixture coverage.
- [x] Add scrape-time room/property feature extraction.
- [x] Add Layer 2 feature joins and modelling-table export.
- [x] Add structured output validation.
- [x] Add retry/backoff.
- [x] Add resumable process-sharded full-scrape driver.
- [x] Add memory-bounded worker recycling.
- [x] Add downstream analytics/movement-history integration.

## Key Files

- `notebooks/property_page_scraper.py`
- `scripts/run_full_scrape.py`
- `scripts/discover_listings.py`
- `scripts/merge_candidates_into_config.py`
- `scripts/export_modelling_table.py`
- `tourism_pricing_analytics/scraping/booking/config.py`
- `tourism_pricing_analytics/scraping/booking/urls.py`
- `tourism_pricing_analytics/scraping/booking/parsing.py`
- `tourism_pricing_analytics/scraping/booking/failures.py`
- `tourism_pricing_analytics/scraping/booking/browser.py`
- `tourism_pricing_analytics/scraping/booking/runner.py`
- `tourism_pricing_analytics/scraping/booking/resume.py`
- `tourism_pricing_analytics/scraping/booking/retry.py`
- `tourism_pricing_analytics/scraping/booking/sharding.py`
- `tourism_pricing_analytics/scraping/booking/validation.py`
- `tourism_pricing_analytics/scraping/booking/memory_probe.py`
- `tourism_pricing_analytics/scraping/booking/features/`
- `tourism_pricing_analytics/features/`

## Scale-Up Pass

Status: done as an engineering pass

The Chania scale-up config is committed at
`config/booking_scraper_config_chania_full.json`. It preserves every baseline
target first, including Stavros Villas & Apartments, then appends canonicalized
Chania candidate rows. The 2026-07-03 generated config has 788 unique targets.
It uses the reduced matrix (`lead_times: [7, 30, 60]`,
`stay_lengths: [4, 7]`), headless Chromium, jittered post-navigation pauses,
retry/backoff, and process sharding.

Completed scale-up phases:

- [x] Phase 0: generated the full config from the baseline target set plus the
      Chania candidate CSV while preserving the validated baseline/client
      targets first.
- [x] Phase 1: replaced fixed post-navigation sleeps with configurable jittered
      pauses.
- [x] Phase 2: added artifact-based resumability and per-property completion
      checks.
- [x] Phase 3: added retry/backoff for transient failures.
- [x] Phase 4: added `scripts/run_full_scrape.py` as the sharded driver with
      aggregate stream rebuilding, validation, and modelling-table finalization.
- [x] Phase 5: completed staged/live validation and used the resulting scrape
      output for durable analytics exports documented in `data/modelling/README.md`.

Later memory-hardening work extended the sharded driver with:

- `--batch-per-worker` (default 1)
- `--max-rounds`
- `memory_stats.jsonl`
- system-memory sampling at round boundaries
- clean low-memory stops with a resumable run directory

See `docs/scraping/worker_memory_bounding_plan.md` for the memory-specific
design and trade-offs.

## Live Validation Acceptance

For every rigorous live validation run:

1. The scraper creates or resumes a timestamped run directory.
2. The run directory contains `scrape_debug.log`, `room_inventory.jsonl`,
   `price_rows.jsonl`, and `failures.jsonl`.
3. Each configured property has a per-property output directory.
4. Room inventory output has non-empty `room_id` and `room_name` where an
   undated table is present.
5. Price rows have sane numeric prices; Booking totals must parse as hundreds
   or thousands rather than fractional values.
6. `price_per_night` equals normalized total price divided by stay length.
7. Empty availability windows are logged and do not fail the whole run.
8. Browser processes close cleanly.
9. Every failure has a machine-readable category.
10. Debug snapshot paths referenced by failure records exist when expected.
11. `validation_report.json` is written and reviewed.
12. `modelling_table.jsonl` is built when enough valid artifacts exist.

## Data Quality Gate

Before scraped data feeds analytics, validate:

- no negative prices
- no zero or near-zero prices when raw price text contains a visible positive
  total
- no missing `checkin`, `checkout`, `stay_length_days`, or `captured_at`
- no duplicate `(property_url, room_id)` inventory rows within a run
- no duplicate room/property feature identities within a run
- feature bounds are sane
- price rows preserve raw text fields alongside normalized numeric fields
- rows with null `room_id` are reconciled by room name when possible and
  reviewed when not
- failure records have populated categories
- snapshot filenames referenced by failure records exist

## Test Sweep For Scraper Changes

After each completed implementation phase or scraper behavior change:

1. Run focused unit or fixture tests for the changed behavior.
2. Run `python -m unittest discover -s tests`.
3. Run full `python -m py_compile` checks for changed scripts, package modules,
   and tests.
4. Run compatibility import checks when public compatibility imports are touched.
5. Run rigorous live validation when browser behavior, selectors, failure
   classification, serialization, or output semantics are affected.

Do not treat a smoke run as enough for parser output, serialization, failure
classification, or data correctness changes.

## Current Operational Focus

The build backlog is no longer the limiting factor. Current scraper operations
are about:

- running repeated daily scrapes with the memory-bounded driver
- appending snapshots to movement-history stores
- watching for parser/selector drift
- keeping newly discovered live-output bugs covered by regression tests
- rebuilding dashboard tables from full-run + retry-run combinations rather
  than from retry-only artifacts

## Non-Goals For Ordinary Maintenance

Avoid bundling these into routine scraper fixes unless explicitly scoped:

- database loading
- major analytics/model redesigns
- sophisticated anti-bot behavior beyond the current human-like browsing basics
- exhaustive coverage across every Booking.com edge case in one pass
