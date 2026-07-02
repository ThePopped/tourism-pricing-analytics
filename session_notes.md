# Session Notes

## Current State (2026-07-02)

Active focus is **scraper memory hardening** so the expanded 316-property
Chania Booking.com scrape can run cleanly with 4 parallel workers on the
memory-constrained laptop (11.6 GB RAM). Roadmap Phases 0-4 remain complete
(durable export, analysis foundation, comparables benchmark, hedonic layer,
price-movement monitoring); the operational goal is still to accumulate repeated
daily snapshots so movement comparisons gain history.

The immediate blocker is per-worker memory growth during the scrape, diagnosed
and partly fixed this session. See "Memory Diagnosis" and "Remaining Work".

## Active Scrape

- Run dir: `saved_dom/runs/20260701_205217_772483` (git-ignored; base search
  date 2026-07-01). Fully resumable per-property; safe to kill and relaunch.
- Config in use: a 316-property expanded headless config (seed 10001,
  headless=True, slow_mo=0) passed via `--config`. The committed default is
  `config/booking_scraper_config_chania_full.json`.
- Orchestrator: `scripts/run_full_scrape.py --config <cfg> --workers 4
  --run-dir <run>`, launched detached (PowerShell `Start-Process`) so it
  survives the IDE closing.
- Progress: most room inventories done; the price phase (5 lead times x 3 stay
  lengths = 15 windows/property) is the long tail. Rate observed ~26 page
  loads/min across 4 workers.

## Memory Diagnosis (this session)

Three distinct causes, in order of discovery:

1. **Kernel driver nonpaged-pool leak.** After ~11 days uptime the host idled at
   90-97% RAM with ~1.6 GB nonpaged pool unattributed to any process. A **reboot**
   clears it (restored ~5-6 GB free). Documented in the memory note
   `scrape-host-memory-constraint.md`.
2. **The user's own Chrome.** `chrome.exe` (distinct from workers'
   `chrome-headless-shell.exe`) held ~1.5 GB across ~12 procs; closing it was the
   swing factor that took a thrashing 96%/536 MB-free run down to a healthy
   77%/2.8 GB-free run.
3. **Per-worker Python RSS growth (the core remaining issue).** Each worker
   process climbs monotonically to ~900 MB-1 GB and **never decreases**. This is
   NOT the accumulated record lists (all per-property JSONL on disk totals only
   ~2.4 MB) and is NOT reclaimed by context recycling. It is Playwright/CPython
   retained memory: CPython does not return freed arenas to the OS, so once a
   long-lived worker touches ~1 GB it holds it. Killing the process reclaims it
   fully (usage dropped 89% -> 28% on kill). The only true reset is a fresh
   process.

## Uncommitted Code Changes (do NOT commit without user request)

Implemented and passing (`python -m unittest discover -s tests` = **301 OK**):

- `tourism_pricing_analytics/scraping/booking/browser.py`
  - `BLOCKED_RESOURCE_TYPES` + `block_heavy_resources` (abort image/media/font
    requests; stylesheets kept for layout/visibility).
  - `MEMORY_SAVING_BROWSER_ARGS` (Chromium flags: `--disable-dev-shm-usage`,
    renderer/heap caps, etc.).
  - `new_scraper_context`, `recycle_context`, `should_recycle_context`, and
    cadence constants `CONTEXT_RECYCLE_EVERY_N_PROPERTIES = 10` (room inventory)
    and `PRICE_CONTEXT_RECYCLE_EVERY_N_PROPERTIES = 3` (price phase; denser
    because ~15 navs/property).
- `tourism_pricing_analytics/scraping/booking/runner.py`
  - Both loops take `browser`, recycle the context every N properties, and return
    the live context; `run()` launches with the memory args, uses
    `new_scraper_context`, and recycles once between phases.
- `tests/test_browser_memory.py` (new) and `tests/test_runner_failure_recording.py`
  (updated for the new `run_price_loop` signature).

Effect: context recycling bounds the **Chromium renderer** side well
(headless-shell stays flat/drops), but does **not** fix the Python RSS climb
(cause 3) — that needs process-level recycling (below).

## Remaining Work

**Process-level batch recycling (planned, approved approach, NOT yet
implemented).** Make workers short-lived so Python RSS resets between batches:

1. `sharding.py`: add pure helper
   `next_round_targets(pending, attempted_urls, capacity)` (excludes
   already-attempted-this-invocation URLs, caps at capacity; capacity <= 0 = all).
2. `scripts/run_full_scrape.py`: add `--batch-per-worker` (default 8) and
   restructure `main()` into a round loop — each round recomputes pending from
   disk, selects up to `workers x batch` not-yet-attempted targets, spawns fresh
   worker processes, joins, repeats until none remain, then aggregates/validates/
   builds the modelling table. An `attempted_urls` set keeps each property to at
   most one attempt per invocation (same semantics as today's single pass) so the
   loop cannot spin forever on persistent non-terminal failures
   (`navigation_error` etc.). Sold-out properties already terminate via the
   `empty_availability` terminal category (see
   `resume.py::TERMINAL_FAILURE_CATEGORIES`).
3. Tests for `next_round_targets` in `tests/test_sharded_scrape_driver.py`.
4. Validate: `py_compile` + full unittest sweep, then relaunch 4 workers and
   confirm Python total saw-tooths (drops at round boundaries) instead of
   climbing to OOM.

**After the scrape completes:** run
`python scripts/append_price_observations.py --latest` to fold today's snapshot
into the movement-history stores; report aggregated counts,
`validation_report.json`, how many of the ~200 newly added listings returned
usable rates, and any data-quality-gate rejections.

## Repeated-Scrape Workflow (daily loop)

```powershell
cd C:\Users\gabri\Documents\Projects\tourism_pricing_analytics
.\.venv\Scripts\Activate.ps1

# Full sharded scrape (memory-safe once process recycling lands):
python scripts\run_full_scrape.py --config <expanded-config> --workers 4 --run-dir <run>
python scripts\append_price_observations.py --latest
python scripts\run_dashboard.py
```

- The append updates `data/modelling/price_observations.parquet` and
  `offer_presence.parquet`, deduped by snapshot/property/window/occupancy
  identity (re-running a run is safe).
- First snapshot shows a low-history dashboard state; movement comparisons appear
  once a stay window is observed on two different snapshot dates.

## Known Issues / Watch Items

- **Host is memory-constrained.** 11.6 GB RAM. Reboot before a big scrape (clears
  the driver pool leak) and close your own Chrome. With 4 workers, memory safety
  depends on the process-recycling fix landing. See
  `scrape-host-memory-constraint.md`.
- **Append rejects whole runs on data-quality gates.** Runs with non-numeric
  `latitude`/`longitude` or null `room_id` are refused by
  `normalize_price_observations` rather than written row-wise. Decide whether such
  rows should be cleaned/skipped instead of failing the entire run.
- **Lead-time-relative windows limit cross-snapshot comparability.** Windows are
  relative to scrape date, so absolute stay dates rarely coincide across
  snapshots. A fixed-window daily cadence would fix this.
- **Villa 2-guest under-coverage.** All prices are 2-guest nightly rates, so
  whole-villa / large-party economics remain under-served until a
  varied-occupancy re-scrape.

## Important Files

- `tourism_pricing_analytics/scraping/booking/browser.py`,
  `.../runner.py`, `.../sharding.py`, `.../resume.py`
- `scripts/run_full_scrape.py`
- `tests/test_browser_memory.py`, `tests/test_runner_failure_recording.py`,
  `tests/test_sharded_scrape_driver.py`, `tests/test_resume.py`
- `scripts/append_price_observations.py`, `scripts/run_dashboard.py`
- `docs/analytics/pricing_analytics_roadmap.md` (Phases 0-4 complete),
  `docs/analytics/modelling_approach.md`
- `data/modelling/README.md`

Generated history files remain local operating data and are git-ignored:
`data/modelling/price_observations.parquet`,
`data/modelling/offer_presence.parquet`,
`data/modelling/demand_covariates.csv` (optional, manually maintained).

## Analytics Context

- Client subject: **Stavros Villas & Apartments**
  (`https://www.booking.com/hotel/gr/stavros-villas-amp-apartments.en-gb.html`),
  Gerani, Chania west coast.
- Use the Gerani-local comparable benchmark as the client-facing anchor; use the
  broad-trained hedonic model as a directional feature-adjustment layer.
- Prices are EUR/night for a 2-guest Booking.com search; positioning, not demand
  or revenue optimization.

## Verification (2026-07-02)

- `python -m py_compile` on `browser.py`, `runner.py`, and the changed tests: OK.
- `python -m unittest discover -s tests`: **301 tests OK** (293 prior + 8 new
  browser-memory/context-recycle tests). Process-recycling tests still to be added.

This file was replaced by request on 2026-07-02.
