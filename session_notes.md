# Session Notes

## Active Focus

The Booking.com scraper data layer is complete and the **Scale-Up Pass is done**:
the full **438-property Chania candidate set** has been scraped end to end and
passed the acceptance gate. The scraper, resumability, retry, and process-
sharding driver are all in place and validated against a full live run.

Scale-Up Phases 0-5 are complete:

- Phase 0: full 438-property Chania config generated.
- Phase 1: post-navigation pause made config-driven and shortened.
- Phase 2: artifact-based resumability added.
- Phase 3: retry policy with bounded exponential backoff added.
- Phase 4: process-sharding driver (`scripts/run_full_scrape.py`).
- Phase 5: staged live validation, then the full 438-property run, gate passed.

The next step is no longer scraper scale-up. The small failure-classification
refinement is now **done** (no-room-table "not bookable" pages reclassified from
`selector_drift` to `empty_availability`; see Completed Project Milestones). The
recommended follow-up is moving downstream to clustering / hedonic pricing /
monitoring on the modelling table.

## Current Status

The scraper runs from reusable package modules under
`tourism_pricing_analytics/scraping/booking/`, with
`notebooks/property_page_scraper.py` as a thin manual entrypoint and
`scripts/run_full_scrape.py` as the sharded full-run driver. It produces room
inventory, dated price rows, a Tier B room-feature stream
(`room_features.jsonl`), and a Tier C property-feature stream
(`property_features.jsonl`). A browser-free Layer 2 under
`tourism_pricing_analytics/features/` derives the modelling table from the
persisted JSONL.

### Latest full live run: `20260623_222416_346202` (438 properties)

Run started as a ~50-property pilot on 2026-06-23, was resumed as the full run,
the full run was interrupted on 2026-06-24, and was resumed to completion on
2026-06-25. Resume correctly skipped completed properties and finished the rest.

Acceptance gate result: **PASS.**

- `validation_report.json` `is_valid: true`, 0 issues.
- Aggregate output: 1,777 room inventory, 5,331 price rows, 773 room features,
  429 property features, 1,633 failures, 5,331 modelling-table rows.
- Resumability: 438/438 complete, 0 pending (per-property terminal-artifact
  predicate, not directory existence).
- Data quality: 0 non-positive or near-zero prices; `price_per_night ==
  current_price_value / stay_length_days` for all 5,331 rows; 0 rows missing
  `checkin` / `checkout` / `stay_length_days` / `captured_at`; raw text fields
  preserved alongside normalized numbers.
- Duplicates: the 1,252 colliding `(property_url, room_id, checkin, checkout)`
  keys are legitimate distinct rate offers; 0 remain once `block_id` is added,
  so `block_id` is the true unique key and there are no real duplicate rows.
- Null `room_id`: 12 / 5,331 = 0.2% after Layer 2 name->id reconciliation
  (known bbasic reworded-label limitation; proportional to the 3/421 baseline).
- Failures: 1,570 `empty_availability`, 49 `selector_drift`, 14 `redirect`.
- Coverage: 429 properties returned inventory/features; 287 had price
  availability (the rest were genuinely no-availability for the July-August
  windows); 9 returned no data (7 currently tagged `selector_drift`, 2
  `redirect`).

### Code/test state

- Latest commits: failure-classification refinement (this session), `8d25f0d`
  (session notes refresh), `43d5f68` (`Anchor scrape resume date windows`),
  `8a70e05` (`Add sharded full scrape driver`).
- `.\.venv\Scripts\python.exe -m unittest discover -s tests`: 187 tests OK.
- Targeted `py_compile` OK for `scripts/run_full_scrape.py`, `sharding.py`,
  `runner.py`, the scraper entrypoint, and root config.
- Scrape outputs under `saved_dom/runs/` are git-ignored and local-only;
  nothing from the run itself is committed.

## Completed Project Milestones

- **Failure-classification refinement** (this session): no-room-table "not
  bookable" pages now classify as `empty_availability` instead of
  `selector_drift`. `normalize_page_text` folds curly U+2019/U+2018 apostrophes;
  `EMPTY_AVAILABILITY_PATTERNS` gained `isn't taking reservations`,
  `not taking reservations`, and `not possible to make reservations`. Added the
  `data/sample/raw_html/hotel_off_no_reservations.html` regression fixture plus
  three tests (curly-apostrophe variant, "currently not possible" variant, and
  the fixture). Keeps `selector_drift` a meaningful signal for genuine drift.
- **Fixture-retention decision** (commit `8a35748`): untracked the 7.6 MB
  `data/sample/raw_html/listings_chania.html` region dump. The local file stays
  git-ignored. The README documents why the two ~2 MB parser fixtures are kept
  whole for regression coverage.
- **Selector-drift regression coverage** (commit `288e51d`): added fixture
  coverage for selector-drift behavior before scaling.
- **Candidate list secured** (commit `2eb8848`): added
  `scripts/extract_listing_candidates.py` and committed
  `data/sample/listings_chania_candidates.csv`, the durable 438-property menu.
- **Property set broadened 7 to 15** (commit `9ded24e`): added 8 stratified
  Chania hotels; live validation passed on run `20260622_105842_988147`.
- **Scale-Up Phase 0 - full config** (commit `4b5dcac`): generated
  `config/booking_scraper_config_chania_full.json` (438 deduplicated targets,
  matrix `lead_times [7, 30, 60] x stay_lengths [4, 7]`, `headless: true`,
  `slow_mo_ms: 0`).
- **Scale-Up Phase 1 - config-driven post-navigation pause** (commit
  `27fef9a`): added `PauseConfig`, wired optional `pauses`, replaced the fixed
  post-`goto` pause with config-driven jitter.
- **Scale-Up Phase 2 - resumability** (commit `dd57396`): added `resume.py`
  with expected-dir/window, per-property completion, and pending-target
  helpers; runner persists per-property failures incrementally and rebuilds
  aggregate streams from per-property artifacts.
- **Scale-Up Phase 3 - retry with backoff** (commit `7c9ee94`): added
  `RetryConfig`, retry sections in both configs, pure retry/backoff helpers,
  and runner retry loops. Retryable: `blocked_challenge`, `partial_load`,
  `temporary_booking_error`, `navigation_error`; terminal categories such as
  `empty_availability`, `selector_drift`, and `redirect` are not retried.
- **Scale-Up Phase 4 - process-sharding driver** (commits `8a70e05`,
  `43d5f68`): added `scripts/run_full_scrape.py` and `sharding.py`
  (`IndexedTarget`, stable indexes, `pending_indexed_targets`, deterministic
  `split_indexed_targets`, `aggregate_run_artifacts`); runner gained
  `target_slice` / `all_targets` / `finalize_run` / `worker_id` /
  `search_base_date` hooks; resume windows anchored to a persisted run base
  date. Added `tests/test_sharded_scrape_driver.py`.
- **Scale-Up Phase 5 - full live run + gate** (run `20260623_222416_346202`):
  full 438-property scrape completed via the sharded resumable driver and
  passed the acceptance gate (see Current Status). Outputs are local/git-ignored.

## Scale-Up Pass Status

Full plan and phases: `docs/scraping/booking_scraper_roadmap.md`. All phases
complete:

- **Phase 0 - Plan doc + targets**: done.
- **Phase 1 - Speed & politeness**: done.
- **Phase 2 - Resumability**: done.
- **Phase 3 - Retry with backoff**: done.
- **Phase 4 - Process-sharding driver**: done.
- **Phase 5 - Staged live validation, then full run**: done; gate passed.

Locked scale-up decisions that held up in the full run:

- **Reduced price matrix**: `lead_times [7, 30, 60] x stay_lengths [4, 7]` =
  6 dated windows plus 1 inventory page, 7 navigations per property.
- **Process sharding, 3 workers**: sync runner per worker, own browser, shared
  run dir. Worked end to end across two interruptions via resume.
- **Resumable + retry/backoff**: completed properties skipped on resume;
  transient/block failures retried; empty availability and structural
  selector drift not retried.

## Current Package Structure

- `models.py`: config, output dataclasses, `PauseConfig`, `RetryConfig`,
  `RoomFeatureRecord` / `PropertyFeatureRecord`, failure categories and records.
- `config.py`: config loading, including optional `pauses` and `retry`.
- `urls.py`: property/dated/inventory URL, date window, and slug helpers.
- `parsing.py`: price normalization, per-night calculation, room inventory
  parser (`tr.js-rt-block-row`), price row parser, `room_id_from_block_id`
  recovery.
- `failures.py`: failure classification.
- `retry.py`: retryable categories, retry decision helper, bounded exponential
  backoff with jitter.
- `io.py`: run dirs, logging, JSONL save (overwrite) and append helpers,
  per-property artifact writers, validation-report persistence, DOM snapshot
  writing, persisted run search base date.
- `resume.py`: browser-free expected dir/window, per-property completion, and
  pending-target helpers.
- `sharding.py`: `IndexedTarget`, stable index attachment, pending/selected
  filtering, deterministic shard splitting, per-property artifact aggregation.
- `browser.py`: navigation, status capture, cookie dismissal, recovery, scroll,
  config-driven post-navigation pause, `ensure_property_facilities_loaded`.
- `runner.py`: inventory loop, price loop, retry handling, feature collection,
  incremental per-property failure persistence, resumability filtering,
  aggregate stream rebuilding, sharding hooks, post-run validation,
  orchestration.
- `validation.py`: run-output validation helpers and `RunValidationReport`.
- `listings.py`: listings-page parser (`parse_listings`) for candidate targets.
- `features/`: Layer 1 extraction registry and room/property extractors.
- `tourism_pricing_analytics/features/`: Layer 2 browser-free feature building
  (`seasonality`, `meal_plan`, `cancellation`, `encoders`, `build_features`).
- `scripts/run_full_scrape.py`: sharded orchestration entrypoint with
  `--config`, `--workers`, `--run-dir` (resume), and `--limit` (pilot) flags.

## Known Issues

- **No-availability pages misclassified as `selector_drift` — FIXED this
  session.** Properties such as `064_hotel_off`, `022_alexandros_studios`,
  `170_tarra`, `102_akrogiali`, `411_john_akroyiali` return HTTP 200 with **no
  room table at all** (0 `tr.js-rt-block-row`) and a "we're sorry, but this
  property isn't taking reservations" banner (curly U+2019 apostrophe), or the
  sibling wording "it is currently not possible to make reservations". The
  classifier tagged these `selector_drift`; they are really `empty_availability`
  (nothing bookable, no price data lost). Fixed by folding curly apostrophes in
  `normalize_page_text` and adding the not-bookable markers to
  `EMPTY_AVAILABILITY_PATTERNS`; covered by a `hotel_off_no_reservations.html`
  fixture and three tests. Note: this fix applies to **future** runs — the
  persisted `failures.jsonl` artifacts from run `20260623_222416_346202` still
  carry the old `selector_drift` labels and are not rewritten. (Two of the
  originally listed properties, `275_villa_jokasti` and
  `283_summer_beach_georgioupoli`, have no snapshot dir in this run.)
- **Null `room_id` from bbasic reworded labels (12/5,331 = 0.2% in the full
  run).** Booking generic bbasic blocks can produce price rows with a
  `room_name` but no numeric `room_id`. Layer 2 reconciles by exact
  `(property_url, room_name)` against inventory and intentionally misses
  reworded short labels (e.g. "Double Classic" vs "Classic Double Room"). Left
  as honest nulls rather than fuzzily assigned. The gate reports this count.
- Some properties show no official star/class rating, so `star_rating` is left
  null; check-in/out times are likewise absent for some.
- Structured bed info (`.rt-bed-type`) is absent on many room blocks, so
  `bed_types` / `bed_count` are sparsely populated by design.
- The facilities/languages section is lazy-loaded;
  `ensure_property_facilities_loaded` scrolls it into view best-effort. A miss
  degrades to null rather than failing a run.
- Generated scrape outputs under `saved_dom/runs/` stay local and git-ignored.
  Promote only small representative HTML to `data/sample/raw_html/`.
- The full 7.6 MB `listings_chania.html` region dump is git-ignored and
  local-only; `listings_chania_candidates.csv` is the durable candidate list and
  `listings_chania_sample.html` backs the listings parser test.
- Listing display names can differ from URL slugs; the scraper keys on URL.
- A few properties redirect (`redirect` category, 2/438: `325_kermes_villa`,
  `382_2_familienhaus...`), where the listing URL no longer resolves to the
  expected property. Honest terminal failures, no data.
- Live Booking.com DOM and availability behavior can change; parser and
  failure-category heuristics should keep gaining regression tests as new live
  cases appear.

## Next Recommended Step

The scraper scale-up is complete, and the failure-classification refinement is
done. Recommended next actions, in order:

1. **Move downstream onto the modelling table.** With 5,331 validated price rows
   across 287 available properties, begin the originally planned analytics:
   clustering, hedonic pricing, monitoring, and dashboarding. The modelling
   table (`saved_dom/runs/20260623_222416_346202/modelling_table.jsonl`, 53
   columns) is the starting input; consider a durable export location since run
   dirs are git-ignored.
2. **Optional re-scrape cadence.** The reduced matrix plus 3-worker sharded
   resumable driver runs the full 438 in roughly an hour of live time; schedule
   periodic captures if longitudinal pricing data is wanted.
