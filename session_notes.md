# Session Notes

## Current State (2026-07-05)

Roadmap Phases 0-4 for analytics remain complete: durable export, analysis
foundation, comparables benchmark, hedonic layer, and competitor price-movement
monitoring. The scraper build/scale roadmap is also complete as an engineering
pass, including retry/backoff, resumability, process sharding, structured
validation, feature-stream aggregation, and memory-bounded worker recycling.

The current operational focus is repeated scrapes, combined full+retry dashboard
exports, movement-history accumulation, and monitoring Booking.com challenge
signals plus host memory pressure.

**Default run profile (set 2026-07-05): 8 workers, headless,
`--batch-per-worker 1`.** `scripts/run_full_scrape.py` now defaults to
`--workers 8`, and the full config
(`config/booking_scraper_config_chania_full.json`) is already headless. This is
the result of the July 5 A/B below, which overturned the earlier July 3 belief
that headed mode was materially cleaner.

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

## July 5 Worker/Headless A/B (definitive)

Controlled A/B on 2026-07-05: identical first-100-property slice (`--limit 100`),
`--batch-per-worker 1`, seed 10001, run **sequentially** (shared IP means arms
cannot run in parallel). Six arms: {4, 8, 12} workers x {headed, headless}.

| Arm | Wall-clock | Price rows | Priced props | Inv | PF | drift/`chal_t` | `ERR_ABORTED` | blocked | Min free RAM |
|---|---|---|---|---|---|---|---|---|---|
| 4w headed    | 36m22s | 771 | 60 | 430 | 100 | 3 | 0 | 0 | 7.00 GiB |
| 8w headed    | 30m11s | 767 | 60 | 430 | 100 | 2 | 0 | 0 | 4.89 GiB |
| 12w headed   | 31m36s | 765 | 60 | 430 | 100 | 7 | 0 | 0 | 6.83 GiB |
| 4w headless  | 32m49s | 763 | 59 | 430 | 100 | 1 | 0 | 0 | 6.00 GiB |
| **8w headless** | **25m21s** | 762 | 59 | 430 | 100 | 4 | 0 | 0 | 6.84 GiB |
| 12w headless | 26m34s | 762 | 59 | 430 | 100 | 0 | 0 | 0 | 8.19 GiB |

(Headless times are Round-1-start to finalize; headed are round-loop wall-clock,
a ~45s finalize offset that does not change any ranking.)

Findings:

- **8-worker headless is the best cell and the new default** — fastest overall
  (25m21s), lightest on RAM, coverage within one property of headed, challenge
  signals in the noise band.
- **Headless is ~4-5 min faster than headed at every worker count**, and lighter
  on RAM (higher min-free everywhere).
- **8 is the sweet spot in both modes; 12 is slower than 8.** Past 8, contention
  on the 6-core/12-thread host erases the parallelism gain. Do not go to 12.
- **The "headless provokes more challenges" fear is not supported.** drift/`chal_t`
  counts (headless 1/4/0 vs headed 3/2/7) are all <2% of ~440 windows with no
  monotonic trend; `chal_t` and `selector_drift` count the same events. The 12w
  headed spike of 7 did NOT reproduce headless (12w=0), so the earlier tentative
  "12 nudges challenges up" hint is downgraded to noise. Zero `ERR_ABORTED`,
  zero blocked/403/429 across all six runs.
- **Only cost of headless: one property.** Headless priced 59 vs 60 and a handful
  fewer price rows — one property renders availability only under a headed
  browser. Trivial for aggregate analytics; use headed only when that specific
  property is client-critical.

Run dirs: `saved_dom/runs/ab_{4,8,12}w_{headed,headless}_100`.

## July 3 Scrape Findings (historical; headed-vs-headless conclusion superseded)

NOTE: the July 3 pilots concluded headed was materially cleaner than headless.
The July 5 controlled A/B (above) overturns that on the headed/headless axis. The
full-run facts below still stand and remain the dashboard source.

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
- Caveat: this retry changed several variables at once (4 vs 8 workers, second
  pass, 283-property subset, later time of day), so it does NOT isolate worker
  count — which is why the July 5 A/B was run.

Targeted Stavros same-window scrape:

- Run dir: `saved_dom/runs/stavros_targeted_20260703`.
- Headed, 1 worker, same 7/30/60 x 4/7 matrix.
- Validation passed.
- Price rows 16; room inventory 3; property features 1; failures 2.
- No `chal_t`, no `ERR_ABORTED`, no 403/429, no blocked challenge.
- Misses: `7/4 selector_drift`, `30/7 empty_availability`.

## Run Registry

Every `scripts/run_full_scrape.py` invocation now enriches its run's
`run_metadata.json` at finalize (settings, timing, status, artifact counts,
priced properties, failure breakdown incl. `chal_t`/`ERR_ABORTED`, min free
RAM, validation summary) and upserts the same object as one row per run into
the git-tracked `data/run_registry.jsonl`. View with
`python scripts\list_runs.py`; seed historical runs with
`python scripts\list_runs.py --backfill saved_dom\runs\<dir> ...` (settings
show `-` for backfilled runs). This replaces the manual log/JSONL archaeology
the July 5 A/B required.

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

- **Default full/pilot run: 8 workers, headless, `--batch-per-worker 1`.** This is
  now the code default; `python scripts\run_full_scrape.py` needs no `--workers`
  flag. Fastest, lightest on RAM, challenge-clean.
- **Drop to 4 workers only when RAM is tight** (~20% slower, equally clean).
  **Never go to 12** — no speed gain past 8 on this host, and contention rises.
- **Use headed only for client-critical completeness** on a specific property
  that renders availability only under a headed browser (headless costs ~1
  priced property per 100). For that, run a small headed targeted pass rather
  than flipping the whole full run to headed.
- Keep generated configs and run artifacts under `saved_dom/runs/`.
- Use explicit `--run-dir`; avoid relying on "latest" when ingesting/exporting.
- For dashboard refreshes, use combined full+retry+client run exports in order.

## Known Issues / Watch Items

- Host memory remains tight at about 11.6 GB RAM. Reboot before big scrapes if
  nonpaged pool has grown, close personal Chrome, and watch `memory_stats.jsonl`.
  Headless (the new default) is lighter on RAM, which helps here.
- Append rejects whole runs on data-quality gates such as non-numeric
  `latitude`/`longitude` or null `room_id`; decide later whether to skip bad rows
  instead of rejecting the full run.
- Lead-time-relative windows limit cross-snapshot comparability. Fixed-window
  daily cadence would make movement comparisons richer.
- All current prices are 2-guest nightly Booking.com rates. Whole-villa and
  large-party economics remain under-served until a varied-occupancy re-scrape.
- Treat `saved_dom/runs/` as generated output; promote only small representative
  HTML fixtures when needed for durable regression tests.

## Remaining Work / Next Steps

- Consider a fixture/regression test for the recurring `selector_drift` cases
  (e.g. Casa Delfino under a `chal_t=...` 202 redirect) so a real selector break
  is distinguishable from a challenge redirect.
- Review the ~4 zero-data properties in the full config for removal.
- Run the next full 788-property scrape on the new 8w-headless default and
  refresh the dashboard tables from full + retry/client runs in order.

## Important Files

- `scripts/run_full_scrape.py`
- `scripts/list_runs.py`
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
- `tourism_pricing_analytics/scraping/booking/registry.py`
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

This file was replaced by request on 2026-07-05 (prior full replacement: 2026-07-03).
