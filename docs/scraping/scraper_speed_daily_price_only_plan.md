# Scraper Speed And Daily Price-Only Implementation

## Status

Implemented on 2026-07-06. The upgrade shipped as one coordinated scraper
change covering:

- Stop writing full HTML snapshots for `empty_availability` failures.
- Keep `--batch-per-worker` default at `1`, but add a validated path to run/benchmark with `--batch-per-worker 2`.
- Replace round-barrier scheduling with a dynamic worker scheduler.
- Add `price_only` daily scrape mode that reuses recent inventory/property features; if the latest stable scrape is older than 7 days, automatically run a full scrape instead and surface freshness in logs, metadata, and dashboard.

The live smoke and `--batch-per-worker 2` benchmark remain follow-up validation
items.

## Implemented Behavior

- **Failure snapshots**
  - The scraper runner saves debug HTML only when failure category is not `empty_availability`.
  - Keep `failures.jsonl` unchanged; expected empty availability records still include category, reason, requested/final URL, dates, status code, and `snapshot_filename: null`.
  - Continue saving snapshots for `selector_drift`, `blocked_challenge`, `redirect`, `navigation_error`, `temporary_booking_error`, `partial_load`, and `extraction_error`.

- **Dynamic scheduler**
  - `scripts/run_full_scrape.py` now uses a parent-side dynamic queue:
    - Start up to `--workers` processes.
    - Each process receives up to `--batch-per-worker` pending properties.
    - When a process finishes, immediately schedule the next batch if memory is healthy.
    - Abort on any worker non-zero exit, preserving current failure policy.
  - Keep `--batch-per-worker` default as `1`; support explicit `--batch-per-worker 2`.
  - Preserve memory checks at worker-completion boundaries and before scheduling replacements.
  - Record scheduler metadata: `scheduler="dynamic_queue"`, `batch_per_worker`, `worker_batches_completed`, `memory_halt`, and existing worker/headless/config fields.

- **Price-only mode and inventory freshness**
  - Added CLI mode to `scripts/run_full_scrape.py`: `--mode full|price-only`, default `full`.
  - Added `--inventory-max-age-days`, default `7`.
  - Added inventory freshness resolution from `data/run_registry.jsonl`, selecting the latest completed run with nonzero `room_inventory.jsonl` and `property_features.jsonl`.
  - For `--mode price-only`:
    - If latest inventory/property-feature scrape is fresh, skip `run_room_inventory_loop`.
    - Run only price collection.
    - Hydrate the new run's top-level `room_inventory.jsonl` and `property_features.jsonl` from the latest fresh stable run before validation/model-table build.
    - Record `settings.mode="price_only"` and `settings.inventory_source_run_id`.
    - If latest stable scrape is missing or older than 7 days, automatically switch to full mode and record `settings.requested_mode="price_only"`, `settings.effective_mode="full"`, and a staleness reason.
  - Add price-only resume logic that considers price windows complete without requiring same-run inventory artifacts.

- **Dashboard freshness warning**
  - Added inventory freshness status to `/api/meta`: latest inventory run id, finished date, age days, stale threshold, and `is_stale`.
  - Render a dashboard notice when inventory/property features are stale or unknown.
  - Keep benchmark and movement calculations unchanged; the warning is informational.

## Verification Completed

- Unit tests:
  - `empty_availability` failures create failure records with `snapshot_filename: null`.
  - Non-empty failure categories still save snapshots.
  - Price-only pending/resume logic ignores missing same-run inventory but requires all expected price windows.
  - Inventory freshness helper selects the latest completed stable-feature run and marks stale when age is greater than 7 days.
  - Price-only mode auto-switches to full when inventory is stale.
  - Dynamic scheduler helper assigns pending targets without round barriers and respects `batch_per_worker`.

- Dashboard tests:
  - `/api/meta` includes inventory freshness payload.
  - Rendered HTML includes a mount point/warning behavior for stale inventory.
  - Fresh inventory produces no warning state.

Commands run:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe -m py_compile $(rg --files -g "*.py")
.\.venv\Scripts\python.exe scripts\run_full_scrape.py --help
```

Result: 391 tests passed; compile checks passed.

## Follow-Up Live Validation

- Live smoke: `python scripts\run_full_scrape.py --limit 3 --mode price-only`.
- Benchmark trial: `python scripts\run_full_scrape.py --limit 100 --batch-per-worker 2`.
- Compare duration, memory stats, challenge/failure rate, and validation against the current 8-worker baseline.

## Assumptions

- `--batch-per-worker 2` is a benchmark path, not the new default.
- Price-only daily scrapes should auto-upgrade to full scrapes when inventory/property features are older than 7 days.
- The run registry is the primary freshness source; saved run metadata can be used as a fallback if needed.
- Price-only runs reuse room inventory and property features from the latest stable run, while room features may still be collected from current dated price pages.
