# Session Notes

## Active Focus

The Booking.com scraper data layer is complete, the configured property set has
been broadened to **15 Chania properties**, and the Scale-Up Pass toward the
full **438-property Chania candidate set** is underway.

Scale-Up Phases 0-2 are complete:

- Phase 0: full 438-property Chania config generated.
- Phase 1: post-navigation pause made config-driven and shortened for the
  scale-up run.
- Phase 2: artifact-based resumability added.

The next implementation step is **Phase 3 - Retry with backoff**.

## Current Status

The scraper runs from reusable package modules under
`tourism_pricing_analytics/scraping/booking/`, with
`notebooks/property_page_scraper.py` as a thin manual entrypoint. It produces
room inventory, dated price rows, a Tier B room-feature stream
(`room_features.jsonl`), and a Tier C property-feature stream
(`property_features.jsonl`). A separate browser-free Layer 2 under
`tourism_pricing_analytics/features/` derives the modelling table from the
persisted JSONL.

Latest rigorous live validation remains run `20260622_105842_988147`
(15 properties):

- `validation_report.json` `is_valid: true`, 0 issues.
- 96 room inventory records, 421 price rows, 42 room features, 15 property
  features.
- All 126 failures are `empty_availability`; no selector drift was observed on
  the broadened layouts.
- Lucia and Royal Sun returned room inventory but 0 price rows because every
  dated window was `empty_availability`; this is now explicitly supported by
  the resumability completion predicate.
- Modelling table builds end to end: 421 rows, 53 columns, 13 properties with
  availability; `property_facilities`/`languages_spoken` 421/421; `room_id`
  418/421, with 3 nulls from known bbasic reworded-label cases.

Current code/test state after Phase 2:

- Commit `dd57396`: `Add scraper resumability helpers`.
- `.\.venv\Scripts\python.exe -m unittest discover -s tests`: 164 tests OK.
- Targeted `py_compile` check OK for the scraper entrypoint, root config, and
  Phase 2 touched modules.
- No live scrape was run for Phase 2; the roadmap deliberately stages live
  validation at Phase 5.

Working-tree items to keep separate from scraper progress:

- `notebooks/exploring_listings.ipynb`: local notebook metadata/noise.
- `.claude/`: local state.
- `session_notes.md`: this file.

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

## Scale-Up Pass Status

Full plan and phases: `docs/scraping/booking_scraper_roadmap.md`.

Completed:

- **Phase 0 - Plan doc + targets**: done and committed.
- **Phase 1 - Speed & politeness**: done and committed.
- **Phase 2 - Resumability**: done and committed.

Pending:

- **Phase 3 - Retry with backoff**: add retry policy for transient categories
  such as `blocked_challenge`, `temporary_booking_error`, and
  `navigation_error`; never retry `empty_availability` or `selector_drift`.
- **Phase 4 - Process-sharding driver**: add `scripts/run_full_scrape.py` and
  the supporting runner hooks for target slices, shared run dirs, aggregation,
  validation, and modelling-table build.
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

- `models.py`: config, output dataclasses, `PauseConfig`,
  `RoomFeatureRecord` / `PropertyFeatureRecord`, failure categories and
  records.
- `config.py`: config loading, including optional `pauses`.
- `urls.py`: property/dated/inventory URL, date window, and slug helpers.
- `parsing.py`: price normalization, per-night calculation, room inventory
  parser, price row parser, `room_id_from_block_id` recovery.
- `failures.py`: failure classification.
- `io.py`: run dirs, logging, JSONL serialization and appending for inventory,
  price, failure, and feature streams; validation-report persistence; DOM
  snapshot writing.
- `resume.py`: browser-free expected property directory, expected window,
  per-property completion, and pending-target helpers.
- `browser.py`: navigation, status capture, cookie dismissal, recovery, scroll,
  config-driven post-navigation pause, and
  `ensure_property_facilities_loaded`.
- `runner.py`: inventory loop, price loop, feature collection, incremental
  per-property failure persistence, resumability filtering, aggregate stream
  rebuilding, post-run validation, orchestration.
- `validation.py`: run-output validation helpers and `RunValidationReport`.
- `listings.py`: listings-page parser (`parse_listings`) for candidate
  targets.
- `features/`: Layer 1 extraction registry and room/property extractors.
- `tourism_pricing_analytics/features/`: Layer 2 browser-free feature building
  (`seasonality`, `meal_plan`, `cancellation`, `encoders`,
  `build_features`).

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

Implement **Scale-Up Phase 3 - Retry with backoff**:

- Add pure retry-policy helpers, likely in a new small module or near failure
  classification: `should_retry(category, attempt, max_attempts)` and a
  deterministic backoff/jitter helper that can be unit tested.
- Retry transient categories: `blocked_challenge`, `temporary_booking_error`,
  and `navigation_error`.
- Do not retry terminal categories: `empty_availability`, `selector_drift`,
  `redirect`, and successful price rows.
- Integrate the retry wrapper around price-window navigation/extraction first;
  room-inventory retry can use the same helper if the implementation stays
  small and clear.
- Preserve the Phase 2 completion semantics: only record final terminal failure
  evidence after retries are exhausted, and keep transient unresolved windows
  pending.
- Add unit tests for retry decisions, max-attempt behavior, backoff bounds, and
  the rule that transient failures remain resumable until terminal evidence is
  written.
- Run the full relevant test sweep before committing and moving to Phase 4.
