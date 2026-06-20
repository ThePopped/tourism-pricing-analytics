# Next Pass Refactor Plan

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
