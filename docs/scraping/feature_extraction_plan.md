# Feature Extraction Plan

## Objective

Add a modular, extensible **feature-extraction layer** to the Booking.com
scraper so that per-room and per-property characteristics can be captured and,
in a separate downstream layer, turned into a modelling table for an ML-based
price regression.

Two hard design rules govern this work:

1. **Scraping stays separate from encoding/processing.** The scraper captures
   raw and lightly-normalized fields only. All encoding (multi-hot, ordinals),
   seasonality derivation, joins, and any modelling preparation live in a
   separate layer that reads persisted output and never touches a browser.
2. **New features are pluggable.** Adding a feature should mean: write one small
   extractor module, register it, and add a fixture regression test. No surgery
   on the core scraper, browser orchestration, or runner loop.

## Branch

All work happens on `feature/room-property-features` (not `main`). Commit at the
end of each phase, after a full rigorous test sweep.

## Current Starting Point

- Parsing produces `RoomInventoryRecord` (undated room links) and
  `PriceRowRecord` (dated price table rows) in
  `tourism_pricing_analytics/scraping/booking/parsing.py`.
- Persistence writes `room_inventory.jsonl`, `price_rows.jsonl`, failures, and
  `validation_report.json` per run under `saved_dom/runs/<timestamp>/`.
- Fixture regression tests load saved real HTML via Playwright `set_content`
  (`tests/test_booking_parser_fixtures.py`).
- Confirmed by probing the saved fixtures, **every targeted signal already
  exists in HTML we hold**, so the whole layer can be developed and regression
  tested offline before any live run:
  - Room scope (in `th.hprt-table-cell-roomtype` / occupancy cell): room size
    (`(\d+)\s*m²`), bed types (`.rt-bed-types` / `.rt-bed-type`), max persons
    (`title="Max persons: N"`), per-room amenities (`.hprt-facilities-facility`,
    ~142 in one fixture).
  - Property scope: star rating (`bk-icon -sprite-ratings_stars_N` / `N-star`),
    review score badge, review count (`N reviews`), geo (`data-atlas-latlng`).

## Target Feature Set

### Tier A — derived from existing records (no scraper change; Layer 2 only)
Seasonality from `checkin` (month, ISO week, day-of-week, is_weekend, Crete
peak/shoulder/off flag); `lead_time_days`; `stay_length_days`; discount depth
from existing current/original prices; meal plan and cancellation flexibility
parsed from `conditions_text`; property identity as a categorical/fixed effect.

### Tier B — per-room DOM (new scrape-time extractors)
Room size (m²), bed configuration (count + types), max occupancy (integer),
per-room amenities **captured as a raw string list** (encoding deferred to
Layer 2). Best-effort room class parsed from `room_name`.

### Tier C — per-property DOM (new scrape-time extractors)
Core: star/class rating, guest review score, review count, property type, geo
coordinates.

High value (confirmed present in the saved property fixture, stable selectors):
- **Review subscores** (`data-testid="review-subscore"`): category breakdown
  (Cleanliness, Comfort, Location, Facilities, Staff, Value for money, Free
  WiFi) captured as a `{category: score}` map. Richer quality signal than the
  single overall score, useful for both regression and clustering.
- **Property-level facilities** (`facility-group-container` / `facility-icon` /
  `property-most-popular-facilities-wrapper`): the whole-hotel amenity set,
  distinct from per-room amenities. Captured as a **raw grouped list**, encoded
  (multi-hot) in Layer 2 like room amenities.
- **Surroundings / nearby POIs with distances** (`hp_location_block` /
  `poi-block`): distance to beach, airport, centre, etc., captured as
  `{poi_name, distance, unit}` pairs. Location is a top price/clustering driver.

Cheap wins (low effort, grabbed in the same pass): check-in / check-out times
and core house rules (children & beds, pets, age restriction, cancellation
summary); photo count; sustainability certification level; languages spoken.

Out of scope here: free-text property description (an NLP/topic input, not a
regression feature) belongs in a separate text-processing effort.

## Architecture

### Layer 1 — scrape-time extraction (the registry)

```
tourism_pricing_analytics/scraping/booking/features/
  base.py        # Extractor protocols + context dataclasses
  registry.py    # ROOM_EXTRACTORS = [...]  PROPERTY_EXTRACTORS = [...]
  room/          # size.py, beds.py, occupancy.py, amenities.py, room_class.py
  property/      # rating.py, reviews.py (score+subscores), geo.py, prop_type.py,
                 # facilities.py, surroundings.py, policies.py, misc.py
                 #   (photo count, sustainability, languages)
```

- A **room-scope extractor** is a callable `extract(ctx) -> dict[str, value]`
  where `ctx` wraps the room-block `Locator` plus identifying fields.
- A **property-scope extractor** has the same shape but receives the page.
- The parser builds the context once, runs every registered extractor, and
  merges their dicts into the corresponding record.
- Each extractor is isolated: an exception in one is caught and recorded as a
  per-feature failure (`extraction_error` / `selector_drift`) without aborting
  the row, the other extractors, or the run.
- **Hooking a new feature = add a module under `room/` or `property/` and append
  it to the registry list.** Nothing else changes.

### Layer 2 — feature derivation (encoding & modelling prep)

```
tourism_pricing_analytics/features/
  build_features.py   # join the JSONL streams into one modelling table
  seasonality.py      # Tier A calendar features
  meal_plan.py        # conditions_text -> meal-plan ordinal
  cancellation.py     # conditions_text -> flexibility flags
  encoders.py         # full multi-hot for amenities, ordinals, scaling
```

Pure Python over persisted JSONL. No browser, no Playwright. Fully unit-tested
with fast tests. **Full amenity multi-hot is fit here, across the entire
dataset**, so the vocabulary can grow as more properties are scraped without
changing the raw scrape artifact.

### Data model — normalize, keep price rows lean

Room and property attributes are stable across dates, so they are stored once
and joined, not duplicated across price rows:

- `RoomFeatureRecord` — one row per `(property_url, room_id)`, written to
  `room_features.jsonl`, deduped like inventory, joined to price rows on
  `room_id`. Fields: `room_size_sqm`, `bed_types` (list), `bed_count`,
  `max_persons`, `amenities` (raw list), `room_class` (best-effort), plus
  identity/`captured_at`.
- `PropertyFeatureRecord` — one row per `property_url`, written to
  `property_features.jsonl`. Fields: `star_rating`, `review_score`,
  `review_count`, `property_type`, `latitude`, `longitude`,
  `review_subscores` (map), `property_facilities` (raw list), `nearby_poi`
  (list of `{poi_name, distance, unit}`), `checkin_from`/`checkin_until`,
  `checkout_from`/`checkout_until`, `house_rules` (children/pets/age/cancel
  summary), `photo_count`, `sustainability_level`, `languages_spoken` (list),
  plus identity/`captured_at`. Every added field is nullable/best-effort.
- `PriceRowRecord` is unchanged.

The modelling table is a Layer 2 join:
`price_rows ⋈ room_features (room_id) ⋈ property_features (property_url)`.

## Phased Implementation

Each phase ends with a full rigorous sweep (unit + `py_compile` + fixture/parser
+ serialization) and a focused commit. Phase 4 adds live validation.

### Phase 0 — scaffolding (no behavior change)
- Add extractor protocols + context dataclasses (`base.py`), empty registry,
  `RoomFeatureRecord` / `PropertyFeatureRecord` models, and their JSONL
  serialization in `io.py`.
- Tests: model construction + serialization round-trip; registry is empty and
  the existing scrape path is byte-for-byte unchanged.

### Phase 1 — Tier B room extractors
- Implement `size`, `beds`, `occupancy`, `amenities` (raw list), `room_class`.
- Wire room-scope extraction into the price-table room cell; dedup into
  `RoomFeatureRecord`; write `room_features.jsonl`.
- Extend `validation.py` for the new stream (non-null `room_id`, no duplicate
  `(property_url, room_id)`, size/persons within sane bounds).
- Fixture regression tests against `elia_palatino_listing_page.html` and
  `selected_suites_discounted_page.html` with exact expected values per
  extractor (mirroring `DiscountedRateFixtureTests`).

### Phase 2 — Layer 2 derivation & encoding
- Implement `seasonality`, `meal_plan`, `cancellation`, `encoders` (full
  amenity multi-hot, ordinals), and `build_features` join.
- Pure unit tests on small synthetic record sets; assert join cardinality,
  multi-hot vocabulary handling (incl. unseen values), and ordinal mappings.

### Phase 3 — Tier C property extractors
- Core: implement `rating`, `reviews` (overall score + count), `geo`,
  `prop_type`.
- High value: `reviews` subscore map, `facilities` (raw grouped list),
  `surroundings` (nearby-POI distance pairs).
- Cheap wins: `policies` (check-in/out times, house rules) and `misc` (photo
  count, sustainability level, languages spoken).
- Write `property_features.jsonl`; extend validation (score/subscore bounds,
  non-negative distances/counts). Every added field is nullable — a missing or
  lazy-loaded section yields `null`, never a row/run failure.
- Fixture tests against the saved property page with exact expected values per
  extractor, including a case that asserts a fully-scrolled DOM parses the
  facilities / subscores / surroundings sections.

### Phase 4 — live validation & handoff
- Run `python notebooks/property_page_scraper.py` against the curated set;
  confirm `validation_report.json` `is_valid: true`; review per-property
  feature coverage; build the modelling table once end to end.
- Update `session_notes.md` (full replace, per policy).

## Risks & Mitigations
- **Room size has no dedicated class** (text trails an SVG icon): extract by
  regex over the room-cell text; cover with a regression test.
- **`room_class` from `room_name` is brittle**: keep best-effort, never let it
  fail a row, and treat a miss as `null`.
- **Amenity vocabulary drift / localization**: mitigated by capturing the raw
  list and encoding downstream where the full dataset is visible.
- **Large fixtures**: reuse existing fixtures; do not add new large pages unless
  a genuinely new layout (e.g. selector drift) is needed.
- **Lazy-loaded property sections**: the full facilities list, review subscores,
  and surroundings can be lazy-loaded or behind expanders in some layouts. The
  fixture captures them because the scraper scrolls, but extractors must stay
  best-effort/nullable and rely on the existing scroll/load step (add a click
  only if a layout demands it).

## Out of Scope (for now)
- The price regression model itself (this plan produces its inputs).
- Property-level features that require additional navigation beyond the already
  captured property page.
- Selector-drift fixture coverage and the null-`room_id` decision carried in
  `session_notes.md` (tracked separately).
