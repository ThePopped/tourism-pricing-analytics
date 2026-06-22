# Booking Scraper Roadmap

This is the staged build → harden → scale roadmap for the Booking.com ingestion
pipeline. The foundational build/hardening pass described first (Phases 1–8 and
its acceptance criteria) is **complete**, as is the feature-extraction layer and
the broadening of the configured set to 15 Chania properties. The current active
pass is the **Scale-Up Pass** documented at the end of this file. The acceptance
and data-quality checklists below remain the enduring validation gate for every
live run, including the scale-up.

## Objective

Continue hardening the Booking.com scraper as a repeatable ingestion pipeline that:

1. Discovers candidate Booking.com properties
2. Captures room inventory from undated property pages
3. Captures dated price rows from property pages across configurable search windows
4. Saves structured output for downstream analytics

## Current Starting Point

The scraper is now package-based, with `notebooks/property_page_scraper.py`
serving as a thin manual entrypoint. Reusable Booking.com logic lives under
`tourism_pricing_analytics/scraping/booking/`.

Implemented pieces:

- Config loading from `config/booking_scraper_config.json`
- Direct dated URL construction
- Undated room-inventory extraction
- Dated price-row extraction
- JSONL persistence for room inventory, price rows, and failures
- Per-property output directories and failure snapshots
- Explicit failure categories for empty availability, selector drift, redirects, blocked/challenge pages, partial loads, temporary Booking.com errors, navigation errors, and extraction errors
- Unit and fixture tests for core parser, URL, config, and failure behavior

## Refactor Direction

Future passes should focus on deeper data correctness, broader fixture coverage,
output-quality validation, and careful scale-up. Keep browser orchestration,
parsing, and persistence separate as new behavior is added.

## Best-Practice Implementation Priorities

Use these priorities to guide implementation order:

1. Protect current behavior with unit and fixture tests before larger refactors.
2. Fix data correctness issues before expanding scrape scale.
3. Keep browser orchestration, parsing, and persistence separate.
4. Keep reusable scraper logic in package modules; leave `notebooks/property_page_scraper.py` as a thin manual entrypoint.
5. Keep runtime and development dependencies declared in `pyproject.toml` as tools are added.
6. Treat `saved_dom/runs/` as generated output; promote only small representative HTML files to fixtures.
7. Classify scraper failures explicitly rather than treating every empty result as the same condition.

### Phase 1: Stabilize Configuration

Deliverables:
- central config for:
  - seed
  - headless mode
  - default occupancy
  - lead times
  - stay lengths
  - timeout values
  - output directories
- explicit property input list

Recommended changes:
- move hard-coded URL and scrape constants into named config objects
- keep one place for URL parameter construction

### Phase 2: Separate Concerns In Code

Break the script into small functions such as:

- `build_dated_url()`
- `dismiss_cookie_banner()`
- `extract_room_inventory()`
- `extract_price_rows()`
- `normalize_price_text()`
- `compute_price_per_night()`
- `run_room_inventory_loop()`
- `run_price_loop()`

Goal:
- make the scraper testable and easier to debug

### Phase 3: Implement Room Inventory Extraction

Input:
- canonical property URL with no dates

Output per room:
- property url
- room id
- room name
- capture timestamp

Logic:
- load page
- dismiss cookie banner if present
- parse `a[href^="#RD"]`
- de-duplicate room ids

### Phase 4: Implement Dated Price Extraction

Input:
- property URL
- `checkin`
- `checkout`
- occupancy parameters

Output per rate row:
- property url
- scrape timestamp
- checkin
- checkout
- stay length
- room id
- room name
- block id
- current total price
- original total price
- rounded price
- rate conditions
- quantity options
- scarcity text
- normalized price per night

Logic:
- build dated URL directly
- do not click the calendar
- parse `tr.js-rt-block-row`
- carry the most recent room cell forward for subsequent rate rows in the same room group

### Phase 5: Build Data Models

Add simple typed records or dataclasses for:

- `PropertyTarget`
- `RoomInventoryRecord`
- `PriceRowRecord`

Goal:
- keep parsing logic explicit
- make downstream serialization safer

### Phase 6: Persist Structured Outputs

Recommended output format:
- JSONL in a timestamped run directory

Suggested files:
- `room_inventory.jsonl`
- `price_rows.jsonl`
- `failures.jsonl`
- `scrape_debug.log`
- optional raw HTML snapshots only on failure, empty availability, or suspicious selector drift

Goal:
- save structured data first, debug artifacts second

### Phase 7: Improve Error Handling

Add explicit handling for:

- cookie modal present / absent
- no availability table found
- property redirect or invalid slug
- empty rate table
- partial page load
- temporary Booking error banners
- likely selector drift
- blocked or challenge page

Recommended behavior:
- log and continue per property / per date window
- avoid failing the whole run on one bad property
- include a machine-readable failure category in logs or output metadata
- save debug HTML only for empty, failed, or suspicious windows

### Phase 8: Add Lightweight Tests

Practical first tests:
- unit test for dated URL construction
- unit test for price normalization
- unit test for price-per-night calculation
- parser tests using saved HTML snippets where possible

Goal:
- protect the parsing logic before scaling the scrape

## Testing And Acceptance Criteria

Each completed implementation phase must be followed by a full relevant test
sweep before the next phase begins. Do not treat a smoke run as sufficient when
the change can affect parser output, failure handling, serialization, or live
scrape behavior.

### Test Levels

1. Unit tests for pure logic
2. Fixture parser tests using saved HTML snapshots
3. Serialization and data-quality checks against structured output
4. Rigorous live validation for scraper behavior that depends on Booking.com pages

### Component Test Matrix

| Component | Test Type | Input / Fixture | Acceptance Criteria |
| --- | --- | --- | --- |
| config loading | unit | `config/booking_scraper_config.json` | config loads, required property list is non-empty, relative output paths resolve under the repo |
| date window generation | unit | fixed base date, lead times, stay lengths | checkin and checkout dates are deterministic and match expected offsets |
| dated URL construction | unit | canonical property URL plus search params | output URL contains expected `checkin`, `checkout`, `group_adults`, `group_children`, and `no_rooms` params |
| price normalization | unit | examples such as `EUR 1,095`, `EUR 919`, `EUR 1,095.50`, `EUR 1.095,50` | numeric values match expected totals and do not collapse thousands into decimals |
| price per night | unit | total price plus stay length | per-night value is rounded correctly; missing price or invalid stay length returns null |
| room inventory parser | fixture parser | saved undated property HTML | records include property name/url, non-empty room ids, non-empty room names, and no duplicate room ids |
| price row parser | fixture parser | saved dated property HTML | records include date window, room mapping where available, block id, raw price text, normalized price, conditions text, and quantity options |
| serialization | unit | sample room and price records | JSONL output is valid, one record per line, and preserves expected field names |
| missing or empty availability | fixture parser / live validation | saved empty availability HTML or live empty date window | scraper logs the empty case, writes `empty_availability`, saves debug HTML, and continues to the next window |
| per-property failure handling | unit / live validation | one failing property among valid properties | run continues for later properties and writes whatever valid records were extracted |

### Live Validation Acceptance

For a rigorous validation run against the configured small property set:

1. The scraper creates a timestamped run directory.
2. The run directory contains `scrape_debug.log`, `room_inventory.jsonl`, and `price_rows.jsonl`.
3. Each configured property has a per-property output directory.
4. Room inventory output has non-empty `room_id` and `room_name` fields for properties where an undated table is present.
5. Price rows have sane numeric prices, with typical Booking.com totals parsed as hundreds or thousands rather than fractional values.
6. `price_per_night` equals normalized total price divided by stay length.
7. Empty availability windows are logged and do not fail the whole run.
8. The browser closes cleanly and the final log line indicates completion.
9. `failures.jsonl` exists and every failure has a machine-readable category.
10. Debug snapshot paths referenced by failure records exist when a snapshot is expected.

### Data Quality Checks Before Downstream Analytics

Before scraped data is used for clustering, modelling, or dashboarding:

- no negative prices
- no zero or near-zero prices when raw price text contains a visible positive total
- no missing `checkin`, `checkout`, `stay_length_days`, or `captured_at`
- room inventory has no duplicate `(property_url, room_id)` pairs within a run
- price rows preserve raw text fields alongside normalized numeric fields
- rows with null `room_id` are reviewed separately before modelling

## Current File-Level Structure

- `notebooks/property_page_scraper.py`
  - thin entrypoint for manual runs
- `tourism_pricing_analytics/scraping/booking/models.py`
- `tourism_pricing_analytics/scraping/booking/config.py`
- `tourism_pricing_analytics/scraping/booking/urls.py`
- `tourism_pricing_analytics/scraping/booking/parsing.py`
- `tourism_pricing_analytics/scraping/booking/failures.py`
- `tourism_pricing_analytics/scraping/booking/io.py`
- `tourism_pricing_analytics/scraping/booking/browser.py`
- `tourism_pricing_analytics/scraping/booking/runner.py`

## Execution Order For The Next Build Passes

1. Add more representative fixtures for empty availability, selector drift, and discounted rate rows.
2. Add structured output validation helpers for run directories.
3. Promote durable data-quality checks for duplicate inventory records, missing price dates, missing room ids, nonpositive prices, and per-night calculation mismatches.
4. Run rigorous live validation against the configured small property set.
5. Review gaps in room matching, price normalization, and availability edge cases before expanding property count.

## Definition Of Done For The Next Pass

The next pass is successful when we can:

1. Run the scraper on a small property list
2. Produce structured room inventory output
3. Produce structured dated price output
4. Link each rate row back to a room id / room name
5. Compute price per night
6. Handle cookie dismissal and missing-data cases without manual intervention
7. Pass unit tests for URL/date/price/per-night/failure logic
8. Pass fixture parser tests for representative undated and dated property pages
9. Complete live validation that satisfies the acceptance criteria above
10. Preserve any newly discovered live-output bugs as regression tests before expanding scale

## Recommended Non-Goals For This Pass

Avoid doing these in the same refactor unless they become necessary:

- full orchestration for all 100 properties
- database loading
- clustering or modelling integration
- sophisticated anti-bot behavior beyond the current human-like browsing basics
- exhaustive test suite coverage across every Booking.com edge case

## Immediate Implementation Notes

- Keep using direct query-parameter URLs for date changes
- Prefer DOM parsing over screenshots or OCR
- Treat room inventory and rate rows as separate entities
- Preserve Booking identifiers such as `room_id` and `block_id`
- Store raw rate-condition text before designing a normalized taxonomy

---

# Scale-Up Pass: 438 Chania Properties

## Status

Underway. The foundational build, feature-extraction layer, and the 15-property
broadening (live-validated against run `20260622_105842_988147`) are done.
Scale-Up Phases 0-2 are complete:

- Phase 0: `config/booking_scraper_config_chania_full.json` generated from the
  438-property Chania candidate CSV with the reduced price matrix and speed
  settings.
- Phase 1: the fixed post-navigation pause was replaced with a smaller
  config-driven jittered pause.
- Phase 2: artifact-based resumability was added with per-property completion
  checks, incremental per-property failure persistence, and aggregate stream
  rebuilding from per-property artifacts.

The next implementation step is Phase 3, retry with backoff.

## Objective

Scrape the full Chania candidate set (438 properties from
`data/sample/listings_chania_candidates.csv`) reliably and in a reasonable
wall-clock time, producing the same structured streams (room inventory, dated
price rows, room/property feature streams) and a clean modelling table.

## Decisions (locked)

- **Data scope — reduced price matrix.** `lead_times: [7, 30, 60]` ×
  `stay_lengths: [4, 7]` = 6 dated windows + 1 undated inventory page = **7
  navigations/property** (down from 16). Drops last-minute (1-day, usually
  sold out) and 14-day leads, and the 14-night stay.
- **Concurrency — process sharding, 3 workers.** Split the property list across
  3 OS worker processes, each running the existing **sync** runner over its
  slice with its own browser, writing into one shared run directory. Chosen over
  an async rewrite because the parsers and feature extractors are coupled to the
  sync Playwright API (`page.locator(...)`), so sharding gets the parallelism
  with near-zero change to the tested parsing layer, plus crash isolation.
- **Robustness — resumable + retry/backoff.** Skip already-completed properties
  on resume; retry transient/block failures with exponential backoff; never
  retry legitimate `empty_availability` or structural `selector_drift`.

## Rationale: why these levers

Measured baseline (run `20260622_105842_988147`): 15 properties → ~23 min, 240
navigations → ~5.8 s/navigation, ~93 s/property. The work is I/O-bound (network
+ fixed sleeps), not CPU-bound, so the dominant levers are (1) fewer navigations
per property, (2) trimming fixed sleeps + headless, and (3) concurrency. Async
helps only because it enables concurrency; process sharding delivers the same
speedup without rewriting sync-coupled parsers.

**Projected wall-clock:** ~2.8 h sequential after speed tuning → **~50–60 min at
3 workers**.

## Phases

Each phase ends with a full relevant test sweep and a commit, per the testing
policy above.

### Phase 0 — Plan doc + targets
- Rename this doc to `booking_scraper_roadmap.md` and append this Scale-Up Pass
  section (done).
- Generate `config/booking_scraper_config_chania_full.json` from
  `listings_chania_candidates.csv`: normalize/dedupe the 438 URLs, apply the
  reduced matrix and speed settings. The validated 15-property
  `booking_scraper_config.json` baseline is left untouched. (Done, commit
  `4b5dcac`.)

### Phase 1 — Speed & politeness (config + minimal `browser.py`)
- `headless: true`, `slow_mo_ms: 0`, and convert the fixed post-`goto`
  `human_pause(1.0, 2.0)` into a smaller config-driven jittered pause (retain
  some jitter for politeness). Target ~5.8 → ~3.3 s/navigation.
- New config field → config-loading test. (Done, commit `27fef9a`.)

### Phase 2 — Resumability
- Add a pure resumability layer, likely
  `tourism_pricing_analytics/scraping/booking/resume.py`, that can identify
  completed properties without touching the browser. At minimum:
  `expected_property_dir(run_dir, index, target)`, `expected_price_windows(...)`,
  `is_property_complete(...)`, and `pending_targets(...)`. (Done.)
- Do **not** treat per-property directory existence as completion. The runner
  prepares every property directory up front, so a directory alone proves only
  that the run was initialized. (Done.)
- Completion rule: a property is complete only when room inventory has a
  terminal artifact and every configured price window has either successful
  price rows or a terminal failure record. This must handle genuinely sold-out
  properties such as Royal Sun and Lucia, where inventory exists and every price
  window is `empty_availability`, without requiring a per-property
  `price_rows.jsonl`. (Done.)
- Add crash-resistant progress evidence before relying on the predicate:
  either persist per-property failure records incrementally as each property
  finishes, or write a small per-property completion/progress marker. Without
  this, a hard crash can leave snapshots but no structured failure records to
  prove which windows reached a terminal state. (Done via incremental
  per-property failure persistence.)
- Unit-test with temporary run directories covering: missing directory,
  directory-only, inventory-only, successful price rows, all-empty sold-out
  property, partial price windows, and transient failures that must remain
  pending until Phase 3 retry policy handles them. (Done.)

### Phase 3 — Retry with backoff
- Pure `should_retry(category, attempt)` plus a retry wrapper so `blocked_challenge`,
  `temporary_booking_error`, and `navigation_error` get K retries with
  exponential backoff + jitter before being recorded as failures.
  `empty_availability` and `selector_drift` are never retried. Unit-tested.

### Phase 4 — Process-sharding driver
- `scripts/run_full_scrape.py`: load targets → apply resume filter → split into
  N shards → spawn N worker processes (each runs the existing sync runner over
  its slice with its own browser, into one shared run dir) → merge per-property
  JSONL into the top-level aggregated streams → validate → build modelling table.
- Light refactor of `run()` / `main()` to accept a target slice + shared run dir
  and skip final aggregation when running as a worker (the driver owns
  aggregation and validation). Parsers and feature extractors are reused
  unchanged. The driver should use the Phase 2 completion predicate rather than
  directory existence when deciding which targets remain pending. Stdlib only
  (`multiprocessing`, backoff) — no new `pyproject.toml` dependencies.
  Shard-split and merge helpers are pure and unit-tested.

### Phase 5 — Staged live validation, then full run
- Pilot ~50 properties first (resume makes the pilot count toward the full run)
  to measure throughput, block rate, and feature coverage, and tune worker count
  + pause. Then the full 438. Build the modelling table end to end and commit
  only after the gate below passes.

## Acceptance gate (enforced)

A scale-up run is **not** considered done until it satisfies, in addition to
`validation_report.json` `is_valid: true`:

1. The **Live Validation Acceptance** checklist (see "Live Validation
   Acceptance" above): timestamped run dir; `scrape_debug.log`,
   `room_inventory.jsonl`, `price_rows.jsonl` present; per-property output dirs;
   non-empty `room_id`/`room_name` where an undated table exists; sane numeric
   prices; `price_per_night = total / stay_length`; empty windows logged without
   failing the run; clean browser close with a completion log line;
   `failures.jsonl` present with a machine-readable category per failure; failure
   snapshot paths exist when expected.
2. The **Data Quality Checks Before Downstream Analytics** (see that section
   above): no negative or spurious near-zero prices; no missing `checkin` /
   `checkout` / `stay_length_days` / `captured_at`; no duplicate
   `(property_url, room_id)` within a run; raw text fields preserved alongside
   normalized numbers.
3. **Null-`room_id` review.** The count of price rows with a null `room_id`
   after Layer 2 name→id reconciliation is reported and reviewed (the known
   "bbasic" reworded-label limitation; 3/421 in the 15-property run), rather
   than silently carried into modelling.
4. **Resumability evidence.** For every configured property, the run has
   machine-readable per-property evidence that inventory reached a terminal
   state and each configured price window reached either a successful rows state
   or a terminal failure state. Directory existence alone is not accepted as
   proof of completion.
