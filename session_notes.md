# Session Notes

## Current State (2026-07-03)

Roadmap Phases 0-4 for analytics remain complete: durable export, analysis
foundation, comparables benchmark, hedonic layer, and competitor price-movement
monitoring. The scraper build/scale roadmap is also complete as an engineering
pass, including retry/backoff, resumability, process sharding, structured
validation, feature-stream aggregation, and memory-bounded worker recycling.

The current operational focus is repeated scrapes, combined full+retry dashboard
exports, movement-history accumulation, and monitoring Booking.com challenge
signals plus host memory pressure.

## Target Set Rule

`config/booking_scraper_config.json` is the baseline/client operating config and
includes Stavros Villas & Apartments. `config/booking_scraper_config_chania_full.json`
must preserve every baseline target first, then append canonicalized discovered
candidate URLs.

This was corrected on 2026-07-03:

- `scripts/generate_full_config.py` now merges baseline targets plus Chania
  candidates instead of replacing baseline properties.
- Regenerated `config/booking_scraper_config_chania_full.json` has 788 unique
  targets, with Stavros at index 0.
- Tests now assert the full config includes Stavros and has deduplicated URLs.

## Dashboard Data Rule

Do not refresh `data/modelling/modelling_table.parquet` from a retry-only run.
Build it from relevant runs in order, where later runs replace earlier rows for
the same `property_url`.

Current dashboard table source order:

```powershell
.\.venv\Scripts\python.exe scripts\export_modelling_table.py `
  --run-dir saved_dom\runs\headed8_full_20260703_113337 `
  --run-dir saved_dom\runs\headed8_retry_challenges_20260703_133957 `
  --run-dir saved_dom\runs\stavros_targeted_20260703
```

Current durable table:

- `data/modelling/modelling_table.parquet`: 4,702 rows x 53 columns.
- Properties: 295.
- Stavros rows: 16.
- Stavros priced windows: `7/7`, `30/4`, `60/4`, `60/7`.

The dashboard is currently running at `http://127.0.0.1:8765/` and `/api/meta`
reports Stavros Villas & Apartments as the default subject with 141 self-catering
subjects.

## July 3 Scrape Findings

Pilot runs against the first 20 Chania-full properties showed headed mode was
materially cleaner than headless:

- Headed 8-worker pilot: 378 price rows, property features 20/20, room inventory
  20/20, no `chal_t`, no `ERR_ABORTED`, no 403/429.
- Headed 4-worker pilot: 360 price rows, property features 19/20, no aborts,
  `chal_t` far lower than headless.
- Headless pilots had more `chal_t` and `ERR_ABORTED` signals.

Full headed 8-worker run:

- Run dir: `saved_dom/runs/headed8_full_20260703_113337`.
- Duration about 1h45m.
- Validation passed.
- Price rows 4,618; room inventory 861; property features 210; failures 2,028.
- Challenge-ish signals: `chal_t` on 283 properties, `ERR_ABORTED` on 67; no
  403/429 and no `blocked_challenge`.
- Memory stayed safe: minimum available about 5.67 GiB; nonpaged spike settled.

4-worker headed retry for affected properties:

- Run dir: `saved_dom/runs/headed8_retry_challenges_20260703_133957`.
- Retried 283 affected properties.
- Validation passed.
- Price rows 3,058; room inventory 990; property features 228; failures 1,205.
- `chal_t` dropped to 59 properties; `ERR_ABORTED` dropped to 3; no 403/429.

Targeted Stavros same-window scrape:

- Run dir: `saved_dom/runs/stavros_targeted_20260703`.
- Headed, 1 worker, same 7/30/60 x 4/7 matrix.
- Validation passed.
- Price rows 16; room inventory 3; property features 1; failures 2.
- No `chal_t`, no `ERR_ABORTED`, no 403/429, no blocked challenge.
- Misses: `7/4 selector_drift`, `30/7 empty_availability`.

## Movement History

After appending the fresh Stavros run:

- `data/modelling/price_observations.parquet`: 8,723 rows x 22 columns.
- `data/modelling/offer_presence.parquet`: 9,576 rows x 19 columns.

The Price Movements tab has enough snapshots overall for Stavros, but individual
movement signals depend on selected windows:

- `60/4` and `60/7`: usable movement signals, peer market firming.
- `7/4`: scrape failed on July 3, so no comparable subject price.
- `7/7`: newly available, missing previous comparison.
- `30/4`: subject current/previous exist, but previous peer median is missing.
- `30/7`: unavailable/still unavailable.

If the tab says insufficient history, check whether it means too few snapshots
overall or missing current/previous subject/peer medians for the selected window.

## Operating Recommendations

- For small or medium Booking.com pilots, prefer headed 8-worker mode with
  `--batch-per-worker 1`; it had the best pilot coverage and cleanest challenge
  signals.
- For recovery runs, a headed 4-worker retry was materially cleaner than the
  original full run for challenge/abort signals.
- Keep generated headed configs and run artifacts under `saved_dom/runs/`.
- Use explicit `--run-dir`; avoid relying on "latest" when ingestion/exporting
  generated runs.
- For dashboard refreshes, use combined full+retry+client run exports.

## Known Issues / Watch Items

- Host memory remains tight at about 11.6 GB RAM. Reboot before big scrapes if
  nonpaged pool has grown, close personal Chrome, and watch `memory_stats.jsonl`.
- Append rejects whole runs on data-quality gates such as non-numeric
  `latitude`/`longitude` or null `room_id`; decide later whether to skip bad rows
  instead of rejecting the full run.
- Lead-time-relative windows limit cross-snapshot comparability. Fixed-window
  daily cadence would make movement comparisons richer.
- All current prices are 2-guest nightly Booking.com rates. Whole-villa and
  large-party economics remain under-served until a varied-occupancy re-scrape.
- Treat `saved_dom/runs/` as generated output; promote only small representative
  HTML fixtures when needed for durable regression tests.

## Important Files

- `scripts/run_full_scrape.py`
- `scripts/generate_full_config.py`
- `scripts/export_modelling_table.py`
- `scripts/append_price_observations.py`
- `scripts/run_dashboard.py`
- `tourism_pricing_analytics/analysis/dashboard.py`
- `tourism_pricing_analytics/analysis/movement.py`
- `tourism_pricing_analytics/scraping/booking/browser.py`
- `tourism_pricing_analytics/scraping/booking/runner.py`
- `tourism_pricing_analytics/scraping/booking/sharding.py`
- `tourism_pricing_analytics/scraping/booking/resume.py`
- `tourism_pricing_analytics/scraping/booking/memory_probe.py`
- `tourism_pricing_analytics/scraping/booking/validation.py`
- `data/modelling/README.md`
- `docs/scraping/booking_scraper_roadmap.md`
- `docs/scraping/listing_discovery_plan.md`
- `docs/scraping/worker_memory_bounding_plan.md`
- `docs/analytics/pricing_analytics_roadmap.md`
- `docs/analytics/modelling_approach.md`

## Verification Snapshot

On 2026-07-03, after the config/export/dashboard fixes:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe -m py_compile notebooks\property_page_scraper.py config.py scripts\generate_full_config.py scripts\export_modelling_table.py
```

Result: 365 tests passed; compile checks passed.

This file was replaced by request on 2026-07-03.
