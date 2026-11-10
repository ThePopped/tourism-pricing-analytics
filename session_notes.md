# Session Notes

## Current State (2026-07-07)

Roadmap Phases 0-4 for analytics remain complete: durable export, analysis
foundation, comparables benchmark, hedonic layer, and competitor price-movement
monitoring. On 2026-07-07 the durable modelling tables were rebuilt from the
July 5 full run and the hedonic feature-adjustment was hardened (see the Hedonic
Data-Quality Fix section below). The scraper scale roadmap is also implemented
through the daily price-only upgrade:

- Production code default remains 8 workers, headless, `--batch-per-worker 1`,
  but Codex/operator launches on this host should explicitly use `--workers 4`
  unless the user asks for a different worker count.
- `scripts/run_full_scrape.py` now uses a dynamic worker queue instead of a
  round barrier.
- `--batch-per-worker 2` is supported as an explicit benchmark path, not the
  default.
- `--mode price-only` reuses fresh room inventory and property features from the
  latest completed stable run in `data/run_registry.jsonl`.
- Price-only mode auto-upgrades to full mode when the latest stable inventory
  run is missing or older than `--inventory-max-age-days` (default 7).
- `empty_availability` failures no longer write full HTML snapshots; failure
  records still keep `snapshot_filename: null`.
- Dashboard `/api/meta` exposes inventory freshness, and the UI shows a stale or
  unknown inventory warning.

The operational focus is now daily price collection, benchmark validation for
`--batch-per-worker 2`, and keeping dashboard exports sourced from the intended
full + retry/client run order.

## Target Set Rule

`config/booking_scraper_config.json` is the baseline/client operating config and
includes Stavros Villas & Apartments. `config/booking_scraper_config_chania_full.json`
must preserve every baseline target first, then append canonicalized discovered
candidate URLs.

## Dashboard Data Rule

Do not refresh `data/modelling/modelling_table.parquet` from a retry-only run.
Build it from relevant runs in order, where later runs replace earlier rows for
the same `property_url`.

Current durable tables (rebuilt 2026-07-07 from the July 5 full run,
commit `3f3a602`):

- `data/modelling/modelling_table.parquet` (peer/comparable market): 5,963 rows
  x 53 columns, 478 properties. Layered Jul3 full+retry+Stavros -> Jul5.
  - Stavros rows: 8. Stavros priced windows: `7/4`, `60/4`, `60/7`.
- `data/modelling/hedonic_training_table.parquet` (broad model training input):
  5,869 rows, 448 properties, from the July 5 full run alone. Grouped-CV
  out-of-property GBM log R2 is 0.533.

## Hedonic Data-Quality Fix (2026-07-07, commits `0ddb9fd` + follow-up)

Sanity-checking a suspicious +76% feature-adjustment swing for Stavros
(raw peer median ~EUR 106 -> adjusted EUR 185) uncovered two problems, both
now fixed:

- Room-size tokens (`25 m2`, etc.) rode along in Booking's raw room amenity
  list and leaked into the amenity multi-hot vocabulary as ~38 sparse per-size
  one-hots redundant with `room_size_sqm`. `is_room_size_token()` now filters
  them out in `features/encoders.py` and `analysis/hedonic.py::_clean_token`
  (amenity vocab 165 -> 127 clean tokens). Size still flows to `room_size_sqm`
  via the room `size` extractor; only the vocabulary is cleaned.
- The feature-adjustment counterfactual swapped the client's *entire* sparse
  token bundle into every peer, so a long tail of incidental low-frequency
  amenity/facility flags compounded off-distribution. `feature_adjusted_peer_prices`
  and `explain_price_gap` now share one curated counterfactual: only high-signal
  columns (size, beds, star, review score/count, subscores, location, property
  type, curated `hq__` flags) transfer; sparse one-hots stay at the target's
  own value; the multiplier is clipped to `[0.5, 2.0]`.

Result: adjusted peer median EUR 110.38 vs raw EUR 105.57 (factor median 1.05,
IQR 0.89-1.15); gap split feature-explained EUR 4.54 / residual EUR 39.46. The
positioning narrative is now internally consistent - the premium reads as
unexplained pricing power, not a quality-justified premium, matching that
Stavros is average-or-below peers on review score, amenity count, and facility
subscore. Regression tests cover the size-token leak and the curated, clipped
adjustment. Deliverables (`hedonic_report.md`, `competitive_pricing_workbook.xlsx`,
`positioning_narrative.md`) were regenerated from the refreshed model.

## July 6 Speed / Price-Only Upgrade

Implemented in one coordinated phase:

- Failure snapshots are skipped for expected `empty_availability` pages only.
  Snapshots remain enabled for selector drift, challenge/block signals,
  redirects, navigation errors, temporary Booking.com errors, partial loads, and
  extraction errors.
- The sharded scrape driver now schedules worker batches dynamically:
  completed workers immediately free capacity for the next pending batch, while
  memory checks still happen before scheduling and after worker completion.
- Run metadata records `scheduler="dynamic_queue"`, `worker_batches_completed`,
  `memory_halt`, requested/effective mode, inventory source run id, and the
  inventory freshness payload.
- Price-only resume logic requires only terminal price-window coverage in the
  current run; inventory/property features are hydrated from the fresh source
  run before validation and modelling-table construction.
- Dashboard metadata includes latest inventory run id, finished timestamp, age
  days, stale threshold, stale state, and reason.

Verification on 2026-07-06:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe -m py_compile $(rg --files -g "*.py")
.\.venv\Scripts\python.exe scripts\run_full_scrape.py --help
```

Result: 391 tests passed; compile checks passed; scraper CLI exposes
`--mode {full,price-only}` and `--inventory-max-age-days`.

Live Booking.com smoke and `--batch-per-worker 2` benchmark were not run during
this implementation commit.

## July 5 Worker/Headless A/B

Controlled A/B on 2026-07-05: identical first-100-property slice (`--limit 100`),
`--batch-per-worker 1`, seed 10001, run sequentially. Six arms:
{4, 8, 12} workers x {headed, headless}.

| Arm | Wall-clock | Price rows | Priced props | Inv | PF | drift/`chal_t` | `ERR_ABORTED` | blocked | Min free RAM |
|---|---|---|---|---|---|---|---|---|---|
| 4w headed | 36m22s | 771 | 60 | 430 | 100 | 3 | 0 | 0 | 7.00 GiB |
| 8w headed | 30m11s | 767 | 60 | 430 | 100 | 2 | 0 | 0 | 4.89 GiB |
| 12w headed | 31m36s | 765 | 60 | 430 | 100 | 7 | 0 | 0 | 6.83 GiB |
| 4w headless | 32m49s | 763 | 59 | 430 | 100 | 1 | 0 | 0 | 6.00 GiB |
| **8w headless** | **25m21s** | 762 | 59 | 430 | 100 | 4 | 0 | 0 | 6.84 GiB |
| 12w headless | 26m34s | 762 | 59 | 430 | 100 | 0 | 0 | 0 | 8.19 GiB |

Findings:

- 8-worker headless was the fastest A/B arm, but current host memory is tight;
  for Codex/operator production launches, use `--workers 4` explicitly unless
  the user asks otherwise.
- Do not use 12 workers on this host; contention erases the parallelism gain.
- Use headed only for targeted client-critical completeness checks.

Run dirs: `saved_dom/runs/ab_{4,8,12}w_{headed,headless}_100`.

## Run Registry

Every finalized `scripts/run_full_scrape.py` invocation enriches
`run_metadata.json` and upserts the same object into
`data/run_registry.jsonl`. The registry is now also the source of truth for
price-only inventory freshness.

View runs with:

```powershell
python scripts\list_runs.py
```

Backfill historical runs with:

```powershell
python scripts\list_runs.py --backfill saved_dom\runs\<dir>
```

## Movement History

The Price Movements tab has enough snapshots overall for Stavros, but individual
movement signals still depend on selected windows:

- `60/4` and `60/7`: usable movement signals, peer market firming.
- `7/4`: scrape failed on July 3, so no comparable subject price.
- `7/7`: newly available, missing previous comparison.
- `30/4`: subject current/previous exist, but previous peer median is missing.
- `30/7`: unavailable/still unavailable.

If the tab says insufficient history, check whether it means too few snapshots
overall or missing current/previous subject/peer medians for the selected window.

## Operating Recommendations

- Default full/pilot run for Codex/operator use on this host:
  `python scripts\run_full_scrape.py --workers 4`.
- Do not launch a bare `python scripts\run_full_scrape.py` production scrape
  unless the user explicitly asks for the code default worker count.
- Daily price scrape: `python scripts\run_full_scrape.py --mode price-only`.
- Live Booking.com scrapes must be run outside Codex sandboxed network access.
  Request/use unsandboxed execution from the start; do not first attempt a live
  Booking.com scrape inside the sandbox.
  Sandboxed runs fail with Chromium `net::ERR_NETWORK_ACCESS_DENIED`, produce
  redirect-classified failures, and contaminate the run directory.
- Benchmark batch size 2 with a controlled pilot before adopting it:
  `python scripts\run_full_scrape.py --limit 100 --batch-per-worker 2`.
- Use explicit `--run-dir` when resuming; avoid relying on "latest" for exports.
- Reboot before big scrapes if nonpaged pool has grown, and monitor
  `memory_stats.jsonl`.
- Treat `saved_dom/runs/` as generated output; promote only small representative
  HTML fixtures when needed for durable regression tests.

## Known Issues / Watch Items

- `saved_dom/runs/20260706_180705_645696` is a contaminated failed attempt:
  first stopped on low memory, then resumed through sandboxed network access and
  produced `ERR_NETWORK_ACCESS_DENIED` redirect failures. Do not resume it or use
  it for analytics.
- Host memory remains tight at about 11.6 GB RAM.
- Append rejects whole runs on data-quality gates such as non-numeric
  `latitude`/`longitude` or null `room_id`; decide later whether to skip bad rows
  instead of rejecting the full run.
- Lead-time-relative windows limit cross-snapshot comparability. Fixed-window
  daily cadence would make movement comparisons richer.
- All current prices are 2-guest nightly Booking.com rates. Whole-villa and
  large-party economics remain under-served until a varied-occupancy re-scrape.

## Remaining Work / Next Steps

- Run live smoke: `python scripts\run_full_scrape.py --limit 3 --mode price-only`.
- Run benchmark trial: `python scripts\run_full_scrape.py --limit 100 --batch-per-worker 2`.
- Compare duration, memory stats, challenge/failure rate, and validation against
  the current 8-worker baseline.
- Review the few zero-data properties in the full config for removal.
- After the next successful production scrape, refresh the durable tables again
  from full + retry/client runs in order (the current tables are the July 5
  rebuild).
- Investigate the Stavros window drift: commit `3f3a602` intended `7/7` and
  `30/4` to survive the layered rebuild, but the durable table now carries
  `7/4`, `60/4`, `60/7`. Confirm which windows Stavros actually priced on
  July 3/5 before relying on any single-window movement signal.

## Important Files

- `scripts/run_full_scrape.py`
- `scripts/list_runs.py`
- `scripts/export_modelling_table.py`
- `scripts/append_price_observations.py`
- `scripts/run_dashboard.py`
- `tourism_pricing_analytics/analysis/dashboard.py`
- `tourism_pricing_analytics/analysis/movement.py`
- `tourism_pricing_analytics/scraping/booking/runner.py`
- `tourism_pricing_analytics/scraping/booking/sharding.py`
- `tourism_pricing_analytics/scraping/booking/resume.py`
- `tourism_pricing_analytics/scraping/booking/registry.py`
- `tourism_pricing_analytics/scraping/booking/validation.py`
- `docs/scraping/scraper_speed_daily_price_only_plan.md`
- `docs/scraping/scraper_design.md`
- `docs/scraping/booking_scraper_roadmap.md`
