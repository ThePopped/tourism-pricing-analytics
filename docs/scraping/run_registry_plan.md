# Central Run Registry Plan

Status: planned (2026-07-05)

## Context

The scraper produces one run directory per scrape under `saved_dom/runs/<id>/`, but
the only run-level record today is a two-field `run_metadata.json`
(`created_at`, `search_base_date` — written in `io.resolve_run_search_base_date`,
`io.py:122-124`). There is **no record of the settings used** (workers, headless,
batch, limit, config), **no timing** (end time / duration), **no result roll-up**
(counts, failure breakdown, challenge signals, memory), and **no central index**
across runs.

This gap was felt directly during the 2026-07-05 worker/headless A/B: building the
six-arm comparison required grepping `scrape_debug.log` for round timings,
`wc -l` on the JSONL streams, min-free RAM from `memory_stats.jsonl`, and challenge
signals from `failures.jsonl` — fragile manual archaeology.

**Goal:** (1) enrich each run's `run_metadata.json` with settings + timing +
results at finalize, and (2) maintain a git-tracked central registry
`data/run_registry.jsonl` (one upserted row per run) plus a `scripts/list_runs.py`
viewer, so every scrape self-documents and the run history is queryable at a glance.

Registry location is **git-tracked `data/run_registry.jsonl`** (verified not
gitignored; `data/` is already tracked). It holds small metadata only — no HTML —
so it does not violate the "don't commit generated runs" rule in `CLAUDE.md`.

## Scope decisions

- Enrichment + registry writing happens **only in the sharded orchestrator**
  `scripts/run_full_scrape.py::main()` — that is the real entrypoint and the only
  place where orchestration settings (`--workers`, `--batch-per-worker`, `--limit`,
  `--config`, `--max-rounds`) are in scope. The manual `runner.run(finalize_run=True)`
  path (notebook/single-property use) keeps its current minimal metadata; it does
  not know these settings and does not need a registry row.
- The registry is **upsert-by-run-dir** (not append-only): a resumed or
  memory-halted-then-resumed run finalizes more than once, and we want one row per
  run reflecting its final state. Same "later replaces earlier" idea already used
  for the modelling table.
- The enriched `run_metadata.json` object and the registry row are the **same
  object** (registry row just adds a `run_id` = run-dir name), so they cannot drift.

## New module: `tourism_pricing_analytics/scraping/booking/registry.py`

Pure, testable helpers (no browser coupling), reusing existing readers:

- `summarize_failures(run_dir) -> dict` — read top-level `failures.jsonl` via
  `validation.load_jsonl_records` (`validation.py:73-121`); tally by `category`
  (field name confirmed `category`, `models.py:195`), plus `chal_t` count
  (`final_url` contains `chal_t`) and `err_aborted` count (`exception_message`
  contains `ERR_ABORTED`). Returns `{by_category: {...}, chal_t, err_aborted, total}`.
- `count_priced_properties(run_dir) -> int` — distinct `property_url` in
  `price_rows.jsonl`.
- `min_available_gib(run_dir) -> float | None` — min `available_bytes` / 2**30
  across `memory_stats.jsonl`.
- `read_validation_summary(run_dir) -> dict` — `json.loads` of
  `validation_report.json`; return `{is_valid, issue_count}` (structure per
  `validation.py` `report_to_dict:53-62`). Tolerate missing/malformed file.
- `build_run_summary(run_dir, *, settings, started_at, finished_at, artifact_counts, status) -> dict`
  — merge existing `io.load_run_metadata(run_dir)` (keeps `created_at`,
  `search_base_date`) with: `settings` block, `started_at`/`finished_at`/
  `duration_seconds`, `status`, `artifact_counts` (from
  `sharding.aggregate_run_artifacts`), `priced_properties`, `failure_summary`,
  `min_available_gib`, `validation`. Also usable standalone for **backfill** of
  historical runs (settings unknown → recorded as `null`).
- `append_run_registry(registry_path, summary) -> None` — read existing JSONL
  rows, drop any with the same `run_id`, append `summary` (with `run_id` set to the
  run-dir name), rewrite the file. Create parent dir/file if absent.

## Wiring into `scripts/run_full_scrape.py::main()`

Confirmed insertion points:

1. Capture `run_started_at = datetime.now()` near the top of `main()` (~line 213).
2. Track a `status` string as the loop exits: max-rounds break (265-267) →
   `"max_rounds_stop"`, completion break (277-279) → `"completed"`, memory break
   (291-292) → `"memory_halt"`.
3. After finalize (`aggregate_run_artifacts` line 311, `validate_and_report_run`
   315, `build_and_save_modelling_table` 316) and **before** the `memory_low_stop`
   `SystemExit(3)` branch (318-325), assemble settings and write both records:

   ```python
   settings = {
       "workers": args.workers,
       "batch_per_worker": args.batch_per_worker,
       "limit": args.limit,
       "config": str(args.config),
       "max_rounds": args.max_rounds,
       "headless": scraper_config.browser.headless,
       "seed": scraper_config.seed,
       "rounds_completed": round_number,
   }
   summary = build_run_summary(
       run_dir, settings=settings, started_at=run_started_at,
       finished_at=datetime.now(), artifact_counts=artifact_counts, status=status,
   )
   save_run_metadata(run_dir, summary)             # enrich per-run file
   append_run_registry(REGISTRY_PATH, summary)     # central registry
   ```

   `REGISTRY_PATH = REPO_ROOT / "data" / "run_registry.jsonl"` (derive from the
   existing `CONFIG_DIR`/repo-root constants in the script).
4. `duration_seconds` here reflects the finalizing invocation's wall-clock. For a
   normal single-shot run that is the full run time; for a resumed run it is the
   final leg only, while original `created_at` is preserved from the first
   invocation.

## Viewer: `scripts/list_runs.py`

Read `data/run_registry.jsonl`, print an aligned table sorted by `created_at`:
`run_id · workers · headless · batch · limit · duration · price_rows ·
priced_props · failures · drift/chal_t · min_RAM · valid · status`. No new deps
(stdlib formatting, same style as other `scripts/`). Optional `--backfill
<run_dir>...` flag that calls `build_run_summary` on existing run dirs (settings
`null` for historical runs) and upserts them — used once to seed the registry from
the six `ab_*` runs and the July-3 full run.

## Files to change / add

- **Add** `tourism_pricing_analytics/scraping/booking/registry.py` (helpers above).
- **Add** `scripts/list_runs.py` (viewer + optional backfill).
- **Edit** `scripts/run_full_scrape.py` — timing capture, `status` tracking,
  finalize-time metadata enrichment + registry append, `REGISTRY_PATH` constant.
- **Add** `tests/test_run_registry.py` — unit tests for the pure helpers.
- **Edit** `session_notes.md` — add a "Run registry" note pointing at
  `data/run_registry.jsonl` and `list_runs.py`.
- **Edit** `CLAUDE.md` Package Structure list — add `registry.py`.
- Optionally note the viewer command in `README.md`.

## Reused existing code (do not reinvent)

- `sharding.aggregate_run_artifacts(run_dir, targets)` (`sharding.py:148-160`) —
  already called in `main()` as `artifact_counts`; pass it straight through.
- `validation.load_jsonl_records` (`validation.py:73-121`) — stream reader for the
  failure tally.
- `io.load_run_metadata` / `io.save_run_metadata` / `RUN_METADATA_FILENAME`
  (`io.py:34-52,24`) — read/merge/write the per-run metadata file.
- `models.ScrapeFailureRecord` category set (`models.py:6-15,195`) — canonical
  failure categories for the breakdown keys.

## Verification

1. **Unit tests:** `python -m unittest tests.test_run_registry` — cover
   `summarize_failures` (category tally + chal_t/err_aborted from crafted
   `failures.jsonl`), `count_priced_properties`, `min_available_gib`,
   `append_run_registry` upsert (same run_id replaces, different appends),
   `build_run_summary` key set + malformed-file tolerance.
2. **Compile:** `python -m py_compile scripts\run_full_scrape.py scripts\list_runs.py tourism_pricing_analytics\scraping\booking\registry.py`.
3. **Full suite:** `python -m unittest discover -s tests` (expect prior 365 + new).
4. **End-to-end live smoke:** `python scripts\run_full_scrape.py --limit 3` (uses
   the new 8w-headless default). Confirm: enriched `run_metadata.json` in the new
   run dir has settings/timing/results; `data/run_registry.jsonl` gained one row;
   `python scripts\list_runs.py` renders it.
5. **Backfill check:** `python scripts\list_runs.py --backfill saved_dom/runs/ab_8w_headless_100 saved_dom/runs/ab_8w_headed_100 ...`
   then `list_runs.py` shows the A/B runs (settings `null`, counts populated) —
   confirming the reconstruction the A/B did by hand is now one command.
6. Do **not** commit generated run dirs; the only tracked new data is
   `data/run_registry.jsonl` (small metadata).
