# Worker Memory Bounding Plan

Status: done (implemented 2026-07-02)

Implementation note: the process-level recycling plan has landed in
`sharding.py`, `memory_probe.py`, `scripts/run_full_scrape.py`, and the
corresponding unit tests. Continue full scrapes with `--workers 4` and the
conservative one-property default batch; memory vigilance is handled at round
boundaries through `memory_stats.jsonl`, available-memory checks, nonpaged-pool
growth checks, and clean resumable stops.

Operational update: the first live resume with `--batch-per-worker 8` still let
price-phase Python workers climb toward ~1 GB before the round boundary because
each property can require up to 15 price navigations. The operational default is
therefore `--batch-per-worker 1` for full 5 lead-time x 3 stay-length scrapes.

## Problem

Long sharded scrapes (`scripts/run_full_scrape.py`) run out of memory on the
11.67 GB scrape host. Two distinct growth vectors:

1. **Python worker RSS climbs monotonically.** Context recycling (commit
   `043c14d`) bounds Chromium-side memory, but CPython holds its heap
   high-water mark as RSS even after contexts are freed (see the comment in
   `tourism_pricing_analytics/scraping/booking/browser.py`). Within one
   long-lived worker process this climb is effectively unbounded.
2. **Kernel nonpaged pool leaks** via a device driver during heavy
   Playwright/Chromium activity. This memory survives process exit; only a
   reboot reclaims it. No in-process change can fix it — the orchestrator can
   only observe it and stop cleanly before OOM.

## Approach

Keep 4 workers but make worker processes short-lived: each round, workers
process a small batch of properties and exit (fully reclaiming Python RSS),
then fresh processes are spawned for the next round. Per-property disk saves
plus the existing resume detection (`resume.is_property_complete`) mean no
data is lost across process restarts.

For the nonpaged-pool leak, the orchestrator samples system memory at round
boundaries and stops gracefully — finalizing whatever is complete and leaving
a resumable run dir — instead of climbing into an OOM.

## Changes

### 1. `sharding.py` — round-selection helper

```python
def next_round_targets(pending, attempted_urls, capacity) -> list[IndexedTarget]
```

Returns pending targets not yet attempted this invocation, capped at
`capacity` (`capacity <= 0` means all). Pure and unit-testable.

### 2. New `memory_probe.py` — memory sampling and threshold logic

- A thin probe reading system memory via `ctypes` (no new dependency):
  `GlobalMemoryStatusEx` for available physical bytes, `GetPerformanceInfo`
  for nonpaged pool bytes.
- A pure, unit-testable threshold helper:

```python
def is_memory_low(available_bytes, nonpaged_bytes, baseline_nonpaged, thresholds) -> bool
```

True when available memory is below a floor (default ~2 GB) or nonpaged pool
has grown more than a delta over the run-start baseline (default ~1–1.5 GB).

### 3. `scripts/run_full_scrape.py` — restructure `main()` into a round loop

New args:

- `--batch-per-worker` (default 1): properties per worker per round.
- `--max-rounds` (optional): end the invocation cleanly after N rounds, for
  deliberately chunking a long scrape across reboots.

At startup, capture the nonpaged-pool baseline. Then loop:

1. Recompute pending from disk (`pending_indexed_targets`).
2. `round_targets = next_round_targets(pending, attempted_urls, workers * batch)`.
   If empty, break.
3. Sample memory; log both numbers and append a record to
   `memory_stats.jsonl` in the run dir. If `is_memory_low(...)`, stop
   gracefully (see below) instead of spawning.
4. Mark the round's URLs attempted; split into `--workers` shards
   (`split_indexed_targets`); spawn fresh processes; join.
5. Any worker exit != 0 aborts the invocation (unchanged failure policy).

After the loop (normal completion, `--max-rounds` cap, or low-memory stop):
aggregate + validate + build modelling table, exactly as today — the finalize
path reads per-property artifacts and tolerates partial runs.

**Graceful low-memory stop:** finalize what is complete, log
"memory low — reboot, then rerun with `--run-dir <run>` to resume", and exit
with a distinct exit code so a stopped-for-memory run is distinguishable from
a failed worker.

**Loop-termination guarantee:** the `attempted_urls` set ensures each property
is tried at most once per invocation — the same semantics as today's single
pass, just chunked. This prevents an infinite loop on properties with
persistent non-terminal failures (e.g. `navigation_error`, which is not in
`TERMINAL_FAILURE_CATEGORIES`); sold-out properties already terminate via
`empty_availability`.

Each worker process keeps the existing in-process context recycling (bounds
memory within a batch); process exit resets Python RSS between batches.
Respawned workers append to the same per-worker debug log
(`setup_logging` uses append-mode `FileHandler`).

### 4. Tests

- `test_sharded_scrape_driver.py` — `next_round_targets`: excludes attempted
  URLs, respects capacity, `capacity <= 0` returns all, returns empty when all
  pending are attempted, preserves pending order.
- New tests for `is_memory_low`: below available floor, nonpaged delta over
  baseline, healthy case, boundary values. The ctypes probe itself stays an
  untested thin shim, consistent with how the project separates pure logic
  from OS/browser coupling.

## Validation

- `py_compile` + full unittest sweep (expect ~304+ tests green).
- Reboot the host (clears the nonpaged baseline), restart the 4-worker scrape
  (resumes the pending set), and monitor `memory_stats.jsonl`:
  - Python total should saw-tooth — dropping at each round boundary — and stay
    bounded, with no monotonic climb to OOM.
  - Watch the nonpaged-pool series too: if *it* is the number heading toward
    exhaustion, process recycling helps less and `--max-rounds` chunking
    across reboots becomes the primary mitigation.

## Expectations and trade-offs

- 1 property per process before exit → each worker resets after at most one
  room-inventory pass plus the property's price-window matrix. ~160 pending /
  (4 workers x 1) ≈ 40 rounds; process-startup overhead is accepted to keep
  Python RSS bounded on the 11.6 GB host.
- **Batch size trades one climb for the other.** Larger `--batch-per-worker`
  means fewer Chromium launch/teardown cycles (less driver churn feeding the
  nonpaged leak) but higher per-worker Python RSS peaks; smaller batches the
  reverse. Default 1 is deliberately conservative for the full 15-window scrape;
  use `memory_stats.jsonl` before increasing it.
- **Round barrier:** all workers join before the next round starts, so one
  slow property idles the other workers at each boundary. Accepted trade-off;
  the barrier-free alternative (`multiprocessing.Pool(maxtasksperchild=N)`)
  would restructure the worker Playwright lifecycle and failure policy for
  modest gain.
- **No per-worker RSS self-checks.** Workers bailing early on their own RSS
  would break the `attempted_urls` bookkeeping (the orchestrator has already
  marked the whole shard attempted) unless workers report back what they
  skipped. The batch size is the per-worker RSS bound; keep it the single
  mechanism.

## Scope

Touches `sharding.py`, new `memory_probe.py`, `scripts/run_full_scrape.py`,
and tests. Invoking with just `--workers` (no new args) keeps today's
behavior apart from batching, which is additive.
