# Feature Extraction Plan

Status: done

The modular room/property feature-extraction layer is implemented, wired into
the Booking.com scraper, covered by fixture/unit tests, and consumed by the
Layer 2 modelling-table builder. This document is retained as design context
for future extractor additions.

## Objective

Add a modular, extensible feature-extraction layer to the Booking.com scraper
so per-room and per-property characteristics can be captured and then joined
downstream into modelling rows for competitive pricing analytics.

Two design rules guided the work:

1. Scraping captures raw and lightly-normalized fields only. Encoding,
   seasonality, joins, and modelling preparation live in the downstream
   `tourism_pricing_analytics/features/` layer.
2. New features are pluggable: add a small extractor module, register it, and
   protect it with a fixture regression test.

## Implemented Architecture

### Layer 1 - Scrape-Time Extraction

Implemented under `tourism_pricing_analytics/scraping/booking/features/`:

- `base.py`: extractor protocols and context dataclasses.
- `registry.py`: room and property extractor registries.
- `extract.py`: room feature extraction into `RoomFeatureRecord`.
- `extract_property.py`: property feature extraction into `PropertyFeatureRecord`.
- `room/`: size, beds, occupancy, amenities, room class.
- `property/`: rating, reviews/subscores, geo, property type, facilities,
  surroundings, policies, and miscellaneous fields such as photo count,
  sustainability level, and languages spoken.

The scraper writes:

- `room_features.jsonl`: one row per `(property_url, room_id)`.
- `property_features.jsonl`: one row per `property_url`.

Both streams are best-effort and nullable where Booking.com omits or lazily
loads a section. Validation checks bounds and duplicates without making missing
optional features fatal.

### Layer 2 - Feature Derivation

Implemented under `tourism_pricing_analytics/features/`:

- `seasonality.py`
- `meal_plan.py`
- `cancellation.py`
- `encoders.py`
- `build_features.py`

The modelling table joins:

```text
price_rows x room_features x property_features
```

It derives seasonality, discount depth, meal/cancellation ordinals, amenity and
facility encodings, and reconciles null `room_id` price rows by
`(property_url, room_name)` when possible.

## Completed Phases

- [x] Phase 0: extractor scaffolding, feature record models, JSONL
      serialization, and scaffolding tests.
- [x] Phase 1: Tier B room extractors, scrape-loop wiring, validation, and
      fixture tests against saved Booking.com pages.
- [x] Phase 2: Layer 2 feature derivation/encoding, modelling-table join, and
      unit tests for cardinality, vocabulary handling, ordinals, and
      name-based room-id reconciliation.
- [x] Phase 3: Tier C property extractors, property feature stream, validation,
      and fixture tests for ratings, reviews/subscores, geo, property type,
      facilities, surroundings, policies, photo count, sustainability, and
      languages.
- [x] Phase 4: live validation/handoff, end-to-end modelling-table build, and
      documentation updates.

## Resolved Live Finding

An early curated live run showed `property_facilities` and `languages_spoken`
empty even though fixture extraction was correct. The cause was Booking.com's
lazy-loaded whole-property facilities section. The browser layer now includes
`ensure_property_facilities_loaded`, and the runner calls it before property
feature extraction so the facilities/languages section has a better chance to
materialize during live runs.

The extractors remain best-effort: a missing lazy-loaded section yields empty or
null fields rather than failing a row or run.

## Test Coverage

Relevant coverage includes:

- `tests/test_feature_scaffolding.py`
- `tests/test_room_feature_extractors.py`
- `tests/test_property_feature_extractors.py`
- `tests/test_layer2_features.py`
- `tests/test_run_output_validation.py`
- scraper runner tests that cover feature stream persistence and validation

## Risks And Mitigations

- Room size has no dedicated class: regex extraction is fixture-tested.
- `room_class` is heuristic: misses stay nullable.
- Amenity/facility vocabulary can drift: raw strings are preserved and encoded
  downstream across the full dataset.
- Lazy-loaded property sections can vary: browser loading is best-effort, and
  extraction remains nullable.

## Out Of Scope

- Free-text description NLP.
- Property-level features requiring navigation beyond the already captured
  property page.
- Demand/revenue optimization; this layer produces pricing-positioning inputs.
