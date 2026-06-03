# Next Pass Refactor Plan

## Objective

Refactor the current exploratory scraper into a repeatable pipeline that:

1. Discovers candidate Booking.com properties
2. Captures room inventory from undated property pages
3. Captures dated price rows from property pages across configurable search windows
4. Saves structured output for downstream analytics

## Current Starting Point

`notebooks/property_page_scraper.py` is currently a live DOM exploration script. It:

- opens one property page
- scrolls and clicks exploratory controls
- detects newly opened modals
- saves DOM snapshots for debugging

It is useful for reconnaissance, but it is not yet the production-shaped scraper we need.

## Refactor Direction

The next pass should turn the script from "interaction probe" into "structured extractor".

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

Recommended first output format:
- CSV or JSONL in a timestamped run directory

Suggested files:
- `room_inventory.csv`
- `price_rows.csv`
- `scrape_debug.log`
- optional raw HTML snapshots only on failure

Goal:
- stop saving every exploratory DOM by default
- save structured data first, debug artifacts second

### Phase 7: Improve Error Handling

Add explicit handling for:

- cookie modal present / absent
- no availability table found
- property redirect or invalid slug
- empty rate table
- partial page load
- temporary Booking error banners

Recommended behavior:
- log and continue per property / per date window
- avoid failing the whole run on one bad property

### Phase 8: Add Lightweight Tests

Practical first tests:
- unit test for dated URL construction
- unit test for price normalization
- unit test for price-per-night calculation
- parser tests using saved HTML snippets where possible

Goal:
- protect the parsing logic before scaling the scrape

## Suggested File-Level Refactor

### Keep For Now

- `notebooks/property_page_scraper.py`

### Recommended Near-Term Structure

- `notebooks/property_page_scraper.py`
  - thin entrypoint for manual runs
- `tourism_pricing_analytics/scraping/booking/property_inventory.py`
- `tourism_pricing_analytics/scraping/booking/property_prices.py`
- `tourism_pricing_analytics/scraping/booking/models.py`
- `tourism_pricing_analytics/scraping/booking/io.py`

If package restructuring feels too early, the same function split can happen inside the notebook script first and be moved later.

## Execution Order For The Next Build Pass

1. Refactor the current script into parser-oriented helper functions
2. Implement undated room inventory extraction for one property
3. Implement dated price row extraction for one property
4. Run both flows against 2 to 5 properties
5. Save structured output to disk
6. Review gaps in room matching, price normalization, and availability edge cases

## Definition Of Done For The Next Pass

The next pass is successful when we can:

1. Run the scraper on a small property list
2. Produce structured room inventory output
3. Produce structured dated price output
4. Link each rate row back to a room id / room name
5. Compute price per night
6. Handle cookie dismissal and missing-data cases without manual intervention

## Recommended Non-Goals For This Pass

Avoid doing these in the same refactor unless they become necessary:

- full orchestration for all 100 properties
- database loading
- clustering or modelling integration
- sophisticated anti-bot behavior beyond the current human-like browsing basics
- full test suite coverage

## Immediate Implementation Notes

- Keep using direct query-parameter URLs for date changes
- Prefer DOM parsing over screenshots or OCR
- Treat room inventory and rate rows as separate entities
- Preserve Booking identifiers such as `room_id` and `block_id`
- Store raw rate-condition text before designing a normalized taxonomy
