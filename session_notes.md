# Session Notes

## Active Focus

The Booking.com scraper data layer is complete, the configured property set has
been broadened to **15 Chania properties**, and the Scale-Up Pass toward the
full **438-property Chania candidate set** is underway.

Scale-Up Phases 0-4 are complete:

- Phase 0: full 438-property Chania config generated.
- Phase 1: post-navigation pause made config-driven and shortened for the
  scale-up run.
- Phase 2: artifact-based resumability added.
- Phase 3: retry policy with bounded exponential backoff added for transient
  scrape failures.
- Phase 4: process-sharding driver (`scripts/run_full_scrape.py`) with target
  slicing, shared run dirs, per-property resume, and deterministic aggregation.

The next implementation step is **Phase 5 - Staged live validation, then full
run**.

## Current Status

The scraper runs from reusable package modules under
`tourism_pricing_analytics/scraping/booking/`, with
`notebooks/property_page_scraper.py` as a thin manual entrypoint. It produces
room inventory, dated price rows, a Tier B room-feature stream
(`room_features.jsonl`), and a Tier C property-feature stream
(`property_features.jsonl`). A separate browser-free Layer 2 under
`tourism_pricing_analytics/features/` derives the modelling table from the
persisted JSONL. The full scale-up run is driven by
`scripts/run_full_scrape.py`, which shards configured targets across worker
processes (each its own sync Playwright browser) into a shared run dir, skips
already-complete properties via the resume predicate, then rebuilds aggregate
JSONL streams and runs validation + the modelling-table build as the gate.

Latest rigorous live validation remains run `20260622_105842_988147`
(15 properties):

- `validation_report.json` `is_valid: true`, 0 issues.
- 96 room inventory records, 421 price rows, 42 room features, 15 property
  features.
- All 126 failures are `empty_availability`; no selector drift was observed on
  the broadened layouts.
- Lucia and Royal Sun returned room inventory but 0 price rows because every
  dated window was `empty_availability`; this is explicitly supported by the
  resumability completion predicate.
- Modelling table builds end to end: 421 rows, 53 columns, 13 properties with
  availability; `property_facilities`/`languages_spoken` 421/421; `room_id`
  418/421, with 3 nulls from known bbasic reworded-label cases.

Current code/test state after Phase 4:

- Commit `43d5f68`: `Anchor scrape resume date windows` (latest), on top of
  `8a70e05`: `Add sharded full scrape driver`.
- `.\.venv\Scripts\python.exe -m unittest discover -s tests`: 184 tests OK.
- Targeted `py_compile` check OK for `scripts/run_full_scrape.py`,
  `sharding.py`, `runner.py`, the scraper entrypoint, and root config.
- `git diff --check`: only line-ending warnings, no whitespace errors.
- No new live scrape has been run since the 15-property validation; the roadmap
  deliberately stages live validation at Phase 5.

## Completed Project Milestones

- **Fixture-retention decision** (commit `8a35748`): untracked the 7.6 MB
  `data/sample/raw_html/listings_chania.html` region dump because it was used
  only by ad-hoc notebook exploration, not tests. The local file remains
  git-ignored. The README documents why the two roughly 2 MB parser fixtures
  are deliberately kept whole for regression coverage.
- **Selector-drift regression coverage** (commit `288e51d`): added fixture
  coverage for selector-drift behavior before scaling.
- **Candidate list secured** (commit `2eb8848`): added
  `scripts/extract_listing_candidates.py` and committed
  `data/sample/listings_chania_candidates.csv`, the durable 438-property menu.
- **Property set broadened 7 to 15** (commit `9ded24e`): added 8 stratified
  Chania hotels across budget, mid, upper, and luxury bands. Live validation
  passed on run `20260622_105842_988147`.
- **Scale-Up Phase 0 - full config** (commit `4b5dcac`): generated
  `config/booking_scraper_config_chania_full.json` from the candidates CSV.
  The full config has 438 canonicalized/deduplicated targets, the reduced
  matrix `lead_times [7, 30, 60] x stay_lengths [4, 7]`, `headless: true`,
  and `slow_mo_ms: 0`.
- **Scale-Up Phase 1 - config-driven post-navigation pause** (commit
  `27fef9a`): added `PauseConfig`, wired optional `pauses` into config loading,
  added the section to both configs, and replaced the fixed post-`goto`
  `human_pause(1.0, 2.0)` with config-driven jitter.
- **Scale-Up Phase 2 - resumability** (commit `dd57396`): added
  `tourism_pricing_analytics/scraping/booking/resume.py` with
  `expected_property_dir(...)`, `expected_price_windows(...)`,
  `is_property_complete(...)`, and `pending_targets(...)`; completion is based
  on persisted terminal artifacts, not directory existence. The runner now
  persists per-property failures incrementally and rebuilds aggregate top-level
  JSONL streams from per-property artifacts so resumed/skipped properties are
  preserved.
- **Scale-Up Phase 3 - retry with backoff** (commit `7c9ee94`): added
  `RetryConfig`, configurable retry sections in both scraper configs, pure
  retry/backoff helpers, and runner retry loops for inventory and price
  windows. Retryable categories are `blocked_challenge`, `partial_load`,
  `temporary_booking_error`, and `navigation_error`; terminal categories such
  as `empty_availability`, `selector_drift`, and `redirect` are not retried.
- **Scale-Up Phase 4 - process-sharding driver** (commits `8a70e05`,
  `43d5f68`): added `scripts/run_full_scrape.py` and
  `tourism_pricing_analytics/scraping/booking/sharding.py` with `IndexedTarget`,
  stable config-index attachment, `pending_indexed_targets`,
  deterministic contiguous `split_indexed_targets`, and
  `aggregate_run_artifacts`. The runner grew `target_slice`, `all_targets`,
  `finalize_run`, `worker_id`, and `search_base_date` hooks so each worker
  scrapes its slice into a shared run dir without finalizing, then the driver
  aggregates, validates, and builds the modelling table once all workers join.
  Resume date windows are anchored to a persisted run base date so resumed runs
  recompute the same windows. Added `tests/test_sharded_scrape_driver.py`.

## Scale-Up Pass Status

Full plan and phases: `docs/scraping/booking_scraper_roadmap.md`.

Completed:

- **Phase 0 - Plan doc + targets**: done and committed.
- **Phase 1 - Speed & politeness**: done and committed.
- **Phase 2 - Resumability**: done and committed.
- **Phase 3 - Retry with backoff**: done and committed.
- **Phase 4 - Process-sharding driver**: done and committed.

Pending:

- **Phase 5 - Staged live validation, then full run**: pilot about 50
  properties, tune worker count and pause if needed, then run the full
  438-property scrape and enforce the acceptance/data-quality gate.

Locked scale-up decisions:

- **Reduced price matrix**: `lead_times [7, 30, 60] x stay_lengths [4, 7]` =
  6 dated windows plus 1 inventory page, 7 navigations per property.
- **Process sharding, 3 workers**: sync runner per worker, own browser, shared
  run dir.
- **Resumable + retry/backoff**: skip completed properties on resume; retry
  transient/block failures; never retry legitimate empty availability or
  structural selector drift.
- **Gate before completion**: roadmap Live Validation Acceptance checklist,
  Data Quality checklist, explicit null-`room_id` review, and resumability
  evidence must pass before the scale-up run is considered done.

Projected wall-clock remains roughly 50-60 minutes at 3 workers, pending pilot
measurement.

## Current Package Structure

- `models.py`: config, output dataclasses, `PauseConfig`, `RetryConfig`,
  `RoomFeatureRecord` / `PropertyFeatureRecord`, failure categories and
  records.
- `config.py`: config loading, including optional `pauses` and `retry`.
- `urls.py`: property/dated/inventory URL, date window, and slug helpers.
- `parsing.py`: price normalization, per-night calculation, room inventory
  parser, price row parser, `room_id_from_block_id` recovery.
- `failures.py`: failure classification.
- `retry.py`: retryable failure categories, retry decision helper, and bounded
  exponential backoff with jitter.
- `io.py`: run dirs, logging, JSONL serialization and appending for inventory,
  price, failure, and feature streams; validation-report persistence; DOM
  snapshot writing; persisted run search base date.
- `resume.py`: browser-free expected property directory, expected window,
  per-property completion, and pending-target helpers.
- `sharding.py`: `IndexedTarget`, stable index attachment, pending/selected
  target filtering, deterministic shard splitting, and per-property artifact
  aggregation.
- `browser.py`: navigation, status capture, cookie dismissal, recovery, scroll,
  config-driven post-navigation pause, and
  `ensure_property_facilities_loaded`.
- `runner.py`: inventory loop, price loop, retry handling, feature collection,
  incremental per-property failure persistence, resumability filtering,
  aggregate stream rebuilding, sharding hooks (`target_slice`, `all_targets`,
  `finalize_run`, `worker_id`, `search_base_date`), post-run validation,
  orchestration.
- `validation.py`: run-output validation helpers and `RunValidationReport`.
- `listings.py`: listings-page parser (`parse_listings`) for candidate
  targets.
- `features/`: Layer 1 extraction registry and room/property extractors.
- `tourism_pricing_analytics/features/`: Layer 2 browser-free feature building
  (`seasonality`, `meal_plan`, `cancellation`, `encoders`,
  `build_features`).
- `scripts/run_full_scrape.py`: sharded orchestration entrypoint with
  `--config`, `--workers`, `--run-dir` (resume), and `--limit` (pilot) flags.

## Known Issues

- **Null `room_id` from bbasic reworded labels (3/421 in latest live run).**
  Booking generic bbasic blocks can produce price rows with a `room_name` but
  no numeric `room_id`. Layer 2 reconciles by exact
  `(property_url, room_name)` against inventory, which intentionally misses
  reworded short labels such as "Double Classic" vs "Classic Double Room".
  These are left as honest nulls rather than fuzzily assigning the wrong room.
  The scale-up gate reports this count.
- Some properties show no official star/class rating, so `star_rating` is left
  null rather than guessed; check-in/out times are likewise absent for some.
- Structured bed info (`.rt-bed-type`) is absent on many room blocks, so
  `bed_types`/`bed_count` are sparsely populated by design.
- The facilities/languages section is lazy-loaded. The current
  `ensure_property_facilities_loaded` helper scrolls it into view best-effort;
  if Booking changes anchors, selectors may need updating. A miss degrades to
  null rather than failing a run.
- Generated scrape outputs under `saved_dom/runs/` stay local and git-ignored.
  Promote only small representative HTML to `data/sample/raw_html/`.
- The full 7.6 MB `listings_chania.html` region dump is git-ignored and
  local-only. The committed `listings_chania_candidates.csv` is the durable
  candidate list, and `listings_chania_sample.html` backs the listings parser
  test.
- Listing display names can differ from URL slugs, for example "Angellinas
  Apartments" vs slug `ntountoulaki-maria`; the scraper keys on URL.
- Live Booking.com DOM and availability behavior can change; parser and
  failure-category heuristics should keep gaining regression tests as new live
  cases appear.

## Next Recommended Step

Execute **Scale-Up Phase 5 - Staged live validation, then full run**:

- Run a pilot of about 50 properties with
  `python scripts/run_full_scrape.py --limit 50 --workers 3`. Resume makes the
  pilot count toward the full run.
- Measure pilot throughput, block rate, and feature coverage; tune `--workers`
  and the config `pauses` section if blocking or wall-clock warrant it.
- Run the full 438-property scrape (no `--limit`) against
  `config/booking_scraper_config_chania_full.json`, resuming the same run dir
  via `--run-dir` so completed pilot properties are skipped.
- Enforce the roadmap acceptance gate before declaring done:
  `validation_report.json` `is_valid: true`, the Live Validation Acceptance
  checklist, the Data Quality checklist, an explicit null-`room_id` review, and
  machine-readable per-property resumability evidence (terminal inventory state
  plus a rows-or-terminal-failure state for every configured window).
- Capture the final run's evidence under `saved_dom/runs/<timestamp>/` and only
  then mark the Scale-Up Pass complete.
