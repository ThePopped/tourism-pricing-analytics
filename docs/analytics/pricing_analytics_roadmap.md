# Competitive Pricing Analytics Roadmap

## Status

As of 2026-07-01, **Phases 0-4 are fully implemented and committed**. The
durable export, analysis foundation, comparables benchmark, hedonic
adjustment/explanation, and the Phase 4 competitor price-movement layer (history
stores, snapshot comparison, peer-market movement, transparent pricing signals,
the `/api/movements` service, and the dashboard Price Movements tab) are all in
place, with Step 10 real-run validation done (see
[data/modelling/README.md](../../data/modelling/README.md)).

The operational focus now shifts from building to **accumulating repeated daily
scrapes** so movement comparisons gain history. Future direction (villa
varied-occupancy re-scrape, fixed-window daily cadence for demand-aware pricing,
and clustering segmentation) remains in **Out Of Scope** below.

## Context

Booking.com ingestion is complete: the full 438-property Chania scrape passed its
acceptance gate, and the Layer 2 join
([build_features.py](../../tourism_pricing_analytics/features/build_features.py))
produces a clean **modelling table of 5,331 rows x 53 columns**, one row per
price offer (room x property x date-window), with **100% lat/lon coverage**.

The **business goal** is actionable pricing advice for a specific Chania operator
that owns **apartments and villas**: tell them where their nightly price sits
versus comparable competitors, identify those competitors, and explain the price
gaps. This plan starts the downstream analytics phase.

Three framing decisions, grounded in what the data can honestly support:

- **Positioning, not optimization.** Every price is a *listed asking price for an
  available offer* -- not a transacted price and not demand. So the deliverable is
  a **competitive-positioning benchmark** ("where you sit vs comparable supply"),
  not a revenue-optimal price. True optimization would need demand/occupancy
  signal from recurring scrapes (deferred).
- **Comparables-first, hedonic as the adjustment/explanation layer.** A peer-set
  price benchmark is the headline (intuitive, defensible, directly actionable);
  the hedonic model exists to *feature-adjust* comps and *decompose* price gaps --
  not as the centerpiece.
- **2-guest pricing, controlled by construction.** The scrape used
  `group_adults=2`, so the whole dataset is 2-guest nightly prices
  (`max_persons == 2` for ~all rows; `bed_count` null/0 for 56%). This makes
  occupancy a clean control (apples-to-apples) and means **no per-person/per-bed
  normalization** -- the benchmark unit is simply **EUR/night for a 2-guest
  booking**. Whole-villa / large-party pricing is *under-served* (all 13 villa
  properties captured at 2 guests) and is flagged as needing a future
  varied-occupancy re-scrape.

Decisions locked with the user: scope = foundation -> comparables benchmark ->
hedonic adjustment/explanation; code form = package modules + scripts + unit
tests; export = committed Parquet under `data/modelling/`; training population =
self-catering segment; client input = in-data Booking URL **or** hand-entered
spec; occupancy = proceed at 2-guest and flag villas.

## Dependencies

New dependencies in `pyproject.toml`, mirrored in `dev`:

- `pandas>=2.2,<3`
- `numpy>=1.26,<3`
- `scikit-learn>=1.5,<2`
- `statsmodels>=0.14,<1`
- `pyarrow>=16`
- `shap>=0.45`

Gradient boosting uses sklearn's own `GradientBoostingRegressor` /
`HistGradientBoostingRegressor` (supported by `shap.TreeExplainer`; no extra
binary dependency). Similarity distance is implemented directly (no `gower`
dependency). Use seed `10001` throughout.

## Phase 0: Durable Export

- `scripts/export_modelling_table.py`: read a run directory via existing
  `build_features_from_run(run_dir)`
  ([build_features.py](../../tourism_pricing_analytics/features/build_features.py)),
  write `data/modelling/modelling_table.parquet` (lossless for nested columns).
  Flags: `--run-dir` (default latest under `saved_dom/runs/`), `--out`.
- `data/modelling/README.md`: provenance (run `20260623_222416_346202`, capture
  dates, 5,331 rows, **2-guest search**, rebuild command). Commit both.
- Verify round-trip and row count (5,331).

## Phase 1: Analysis Foundation

New package `tourism_pricing_analytics/analysis/`:

- `loader.py`: `load_modelling_table()` -- read Parquet, coerce dtypes, parse
  dates, assert `price_per_night == current_price_value / stay_length_days`.
  Derive only what's missing: `nearby_poi_count`, `nearest_poi_km`, flatten
  `review_subscores` -> `subscore_*`. Reuse existing Tier A columns.
- `segment.py`: `SELF_CATERING_TYPES` (default `Apartment`, `Villa`,
  `Aparthotel`, `Holiday home`; `Guest house` behind a documented flag) and
  `filter_self_catering(df)`; drops hotels/resorts and the `property_type == "6"`
  parse glitch. Tunable so EDA can refine it.
- `eda.py` + `scripts/run_eda.py` -> `data/modelling/eda_report.md`
  (committed): target distribution (raw/log), missingness, segment sizes,
  EUR/night-at-2-guests by `crete_season` / `lead_time` / `stay_length` /
  `property_type` / `star_rating`, geo spread, and grain/duplicate checks
  (`block_id` is the true unique key). Surfaces the villa under-coverage
  explicitly.

## Phase 2: Comparables Benchmark

Headline deliverable.

New `tourism_pricing_analytics/analysis/competitors.py`, on the self-catering
segment:

- `haversine_km(...)` -- geographic distance (lat/lon present for all rows).
- `feature_similarity(client, candidates)` -- standardized mixed-type distance
  (size, bed_count where present, star_rating, review_score, amenity-overlap,
  `property_type` match), aligned to the hedonic feature set.
- `rank_competitors(client, df, *, w_geo, w_sim, k)` -- weighted combination ->
  top-`k` comparable competitors; reduces to pure proximity or pure similarity at
  the weight extremes.
- `peer_price_benchmark(client, df, windows, *, k)` -- for a client (in-data URL
  *or* hand-entered spec) and date windows (lead_time x stay_length x season),
  build the peer set and report the **peer EUR/night-at-2-guests distribution**
  (median, IQR, min/max) plus the client's **percentile position** when an actual
  price exists. This is the actionable output: "for a 2-guest booking like
  yours, on these dates, comparable competitors list EUR X-Y; you sit at the Nth
  percentile."
- `scripts/run_competitors.py` -> `data/modelling/competitor_report.md`: the peer
  set + the benchmark range for a given client.

## Phase 3: Hedonic Adjustment And Gap Explanation

New `tourism_pricing_analytics/analysis/hedonic.py`, trained on the segment. Its
job is to *support* the comparables benchmark in two ways:

- **Design matrix** `build_design_matrix(df) -> (X, y, groups, feature_meta)`:
  - `y = log(price_per_night)` (2-guest); `groups = property_url`.
  - Numeric (median-impute + `*_missing` flag where genuinely null):
    `room_size_sqm`, `bed_count`, `star_rating`, `review_score`, `review_count`,
    `nearest_poi_km`, `nearby_poi_count`, `subscore_*`. (`max_persons` dropped --
    constant at 2.)
  - Window covariates: `lead_time_days`, `stay_length_days`, `crete_season`,
    `checkin_month`, `checkin_is_weekend`.
  - Ordinals present: `meal_plan_ordinal`, `cancellation_flexibility_ordinal`.
  - One-hot `property_type`; multi-hot `amenities` + `property_facilities` via
    existing [encoders.py](../../tourism_pricing_analytics/features/encoders.py)
    with a frequency floor (keep dimensions modest; effective sample is ~154
    properties).
  - Geo: raw lat/lon -> GBM only; OLS uses `nearest_poi_km` /
    `nearby_poi_count`.
  - Drop identifiers/leakage/free-text (`property_name`, `room_name`,
    `block_id`, `room_id`, `*_text`, `captured_at`, raw price columns,
    `house_rules`, `quantity_options`).
- **Model A: OLS** (`statsmodels`, HC3): market-wide elasticities/premia for
  talking points (star, review, size, season, cancellation, meal). Report
  coefficients, R2, condition number.
- **Model B: gradient boosting** (`sklearn`) with `GroupKFold` by
  `property_url`; report out-of-sample R2/MAE (log and EUR/night). Parsimonious
  and regularized given the small effective sample.
- **Use 1: feature-adjusted comps**: adjust each peer's price to the client's
  feature profile (model-implied delta) so the Phase 2 benchmark can be reported
  "like-for-like," not just raw.
- **Use 2: price-gap decomposition** `explain_price_gap(client, competitor)`:
  split the observed gap into **feature-explained** (`shap.TreeExplainer` on
  Model B, attributing the predicted difference to features) **+ unexplained
  residual** (actual - predicted = brand / photos / pricing power / mispricing).
  The residual is called out as the most actionable signal.
- `scripts/run_hedonic.py` -> `data/modelling/hedonic_report.md`: OLS coefficient
  table, CV metrics, a sample feature-adjusted benchmark, and a sample
  explained+residual gap breakdown.

## Phase 4: Competitor Price Movement Dashboard

Build a v1 monitoring layer for repeated Booking.com scrapes. This adds
movement tracking and transparent pricing signals; it is still **positioning and
monitoring, not demand optimization**.

Defaults locked:

- Scrape cadence: daily.
- First external covariate source: manual CSV.
- First productized output: the existing local dashboard.
- Market movement is property-weighted: compute each property's median first,
  then compute peer-market medians so properties with many room/rate rows do not
  overweight the market.

### Historical stores

Add two generated, append-only local Parquet stores under `data/modelling/`:

- `price_observations.parquet`: one observed available Booking.com rate offer
  per scrape snapshot.
- `offer_presence.parquet`: one searched property/window per snapshot,
  including availability and scrape status.

`price_observations.parquet` carries the existing modelling offer fields plus
snapshot/query context:

- `snapshot_date`, `captured_at`, `run_id`
- `property_url`, `property_name`, `room_id`, `room_name`, `block_id`
- `checkin`, `checkout`, `lead_time_days`, `stay_length_days`
- `adults`, `children`, `rooms`, `currency`, `market`
- `price_per_night`, `current_price_value`
- `property_type`, `latitude`, `longitude`

`offer_presence.parquet` carries the same snapshot/query/property/window
identity fields plus:

- `availability_status`: `available`, `no_available_offer`, `scrape_failed`
- optional `failure_reason`

Deduplication keys must include snapshot date, property URL, stay window,
occupancy, currency, market, and for price rows also `room_id` and `block_id`.
These stores are generated operating history, not committed project fixtures.

Add `scripts/append_price_observations.py`:

- Inputs: `--run-dir`, `--observations-out`, `--presence-out`.
- Reuse the existing run feature pipeline instead of creating a parallel parser.
- Append to existing Parquet, dedupe by key, and write atomically.

### Movement analytics

Add `tourism_pricing_analytics/analysis/movement.py` with these public helpers:

- `load_price_observations(path)`
- `load_offer_presence(path)`
- `load_demand_covariates(path)`
- `build_price_movement_table(observations, presence, subject_url, windows,
  peer_property_urls)`
- `market_pressure_index(movements)`
- `movement_reason_codes(row, market_context, covariates)`

Movement compares each snapshot with the immediately previous comparable
snapshot for the same property/window/query context. Peer sets should reuse the
existing comparable-peer logic from Phase 2.

Movement output includes current and previous price, EUR and percent change,
peer median movement, rank movement, reason codes, and an action payload:

- `recommended_action`: `Hold`, `Increase test`, `Discount test`, `Watch`, or
  `No signal`
- `rationale`: one sentence
- `confidence`: `high`, `medium`, or `low`
- `confidence_flags`: coverage/history warnings

Availability statuses in movement output:

- `available`: available in current and previous comparable snapshot.
- `newly_available`: no available offer previously, available now.
- `disappeared`: available previously, no available offer now.
- `still_unavailable`: no available offer in both snapshots.
- `unknown`: current or previous scrape failed or context was not observed.

V1 reason codes:

- `market_firming`
- `market_softening`
- `property_specific_increase`
- `property_specific_discount`
- `lead_time_compression`
- `availability_compression`
- `nearby_undercutters_discounting`
- `premium_not_feature_supported`
- `possible_price_headroom`
- `low_confidence_low_history`
- `external_covariates_missing`
- `search_demand_rising`
- `search_demand_softening`
- `holiday_or_event_pressure`
- `weather_possible_factor`

### Manual covariates

Add optional CSV support at `data/modelling/demand_covariates.csv`.

Schema:

- `date`
- `checkin`
- `market`
- `google_trends_index`
- `holiday_flag`
- `event_flag`
- `weather_temp_c`
- `weather_rain_mm`
- `notes`

Join covariates by `checkin` and `market`. Missing file is valid and should
produce the user-facing status: `No external covariates loaded.` Covariates are
context labels only in v1; do not train causal or predictive demand models.

### Dashboard integration

Extend the existing stdlib dashboard in `scripts/run_dashboard.py`.

New CLI args:

- `--observations-path`, default `data/modelling/price_observations.parquet`
- `--presence-path`, default `data/modelling/offer_presence.parquet`
- `--covariates-path`, default `data/modelling/demand_covariates.csv`

New route:

- `/api/movements`
- Query params: `subject_url`, `lead_time_days`, `stay_length_days`, `season`,
  `max_peers`
- Returns subject movement, peer movement rows, market pressure summary, reason
  codes, action payload, and confidence flags.

Keep `/api/meta` and `/api/benchmark` backward compatible. Add a compact
**Price Movements** tab with market-pressure KPIs, competitor movement table,
subject-vs-peer timeline, and action panel. If observation history is missing or
has fewer than two comparable snapshots, render a clear low-history state
without breaking the existing benchmark tab.

### Phase 4 implementation steps

Each step should end with the full relevant verification sweep and a focused
commit before moving on.

1. **Schema contracts and fixtures.** Define the observation and presence schema
   constants, dedupe keys, validation errors, and small synthetic test fixtures.
   Add tests for required columns, date parsing, positive prices, valid
   availability statuses, and query-context identity.
2. **Observation store append path.** Add `scripts/append_price_observations.py`
   for `price_observations.parquet` only. Reuse the existing feature-building
   pipeline, normalize rows to the observation schema, append to existing
   Parquet, dedupe by the observation key, and write atomically.
3. **Presence store append path.** Extend the append script to create
   `offer_presence.parquet` from the same run context. Capture `available`,
   `no_available_offer`, and `scrape_failed` states without inferring
   unavailable rows from missing price rows alone.
4. **History loaders and validators.** Add movement-history loaders in
   `analysis/movement.py` for observations, presence, and optional covariates.
   Missing covariates must be safe; missing observation history should return a
   clear low-history condition for dashboard use.
5. **Snapshot comparison core.** Build previous-snapshot joins for the same
   property/window/query context. Compute current/previous prices, EUR change,
   percent change, and the five availability states: `available`,
   `newly_available`, `disappeared`, `still_unavailable`, and `unknown`.
6. **Peer market movement.** Reuse the Phase 2 comparable-peer logic to select
   peers, then compute property-weighted peer medians and rank changes by
   snapshot/window. Add regression tests proving multi-room properties do not
   overweight peer medians.
7. **Reason codes and actions.** Add market-pressure summaries, reason codes,
   recommended action, rationale, confidence, and confidence flags. Keep all
   rules transparent and deterministic; covariates add context labels only.
8. **Movement API service layer.** Extend the dashboard service with loaded
   history/covariates and a JSON-safe `/api/movements` payload. Keep `/api/meta`
   and `/api/benchmark` unchanged and working when history files are absent.
9. **Price Movements tab.** Add the compact dashboard tab: market-pressure KPIs,
   competitor movement table, subject-vs-peer timeline, action panel, and
   low-history/empty states. Avoid broad dashboard redesign.
10. **Real-run validation and docs.** Run the append script on available local
    runs, inspect output shapes and sample movement rows, update
    `data/modelling/README.md` with the exact commands, and commit only docs or
    small fixtures -- not large generated history files.

## Tests

Tests live under `tests/`, focus on pure logic, and use seed `10001`.

- `test_export_modelling_table.py`: synthetic run dir -> export -> reload; row
  count + nested columns survive the Parquet round-trip.
- `test_analysis_loader.py`: dtype coercion, the `price_per_night` invariant
  (passes valid, raises on doctored row), `nearby_poi`/`subscore` derivations.
- `test_segment.py`: self-catering filter keeps the right types; drops hotels and
  the `"6"` glitch.
- `test_competitors.py`: `haversine_km` vs known distances, similarity ordering,
  deterministic ranking, weight extremes (geo-only vs sim-only), and
  `peer_price_benchmark` accepts both a URL row and a spec dict and returns a
  sensible distribution + percentile.
- `test_hedonic.py`: design-matrix shape/columns, log-target positivity,
  impute + missingness flags, `max_persons` excluded, no identifier/leakage
  columns in `X`, `GroupKFold` groups never straddle train/test, and
  `explain_price_gap` parts (explained + residual) sum to the observed gap.
- `test_price_observations.py`: synthetic run dir -> observations/presence
  stores; appends a second snapshot; dedupes repeated rows; preserves query
  context so occupancy/currency/market rows do not merge.
- `test_movement.py`: previous-snapshot joins, EUR and percent changes,
  property-weighted peer medians, rank changes, availability states, reason
  codes, recommended actions, and low-confidence flags.
- `test_movement_covariates.py`: missing covariates CSV is safe; valid CSV joins
  by `checkin` and `market`; search demand, holiday/event, and weather labels
  appear when applicable.
- `test_dashboard.py`: `/api/meta` remains backward compatible;
  `/api/movements` returns JSON-safe payloads; dashboard HTML includes the
  Price Movements tab and mount points.

## Verification

End-to-end, per `CLAUDE.md` full sweep after each phase:

1. `pip install -e ".[dev]"` picks up new dependencies.
2. `python -m py_compile` new scripts + `analysis/` modules.
3. `python -m unittest discover -s tests` -- full suite green.
4. Run scripts against the real run dir: `export_modelling_table.py` ->
   `run_eda.py` -> `run_competitors.py` -> `run_hedonic.py`. Confirm:
   committed Parquet has 5,331 rows; segment + villa-coverage match EDA; a
   peer-set benchmark renders for a sample client (URL and spec); OLS premia
   have sane signs; GBM out-of-sample R2/MAE reported; an explained+residual gap
   example renders and the parts reconcile to the observed gap.
5. Commit each phase at its milestone, only after its sweep passes. Update
   `session_notes.md` only when asked.

## Out Of Scope

Future plans:

- **Varied-occupancy re-scrape** for whole-villa / large-party pricing (the
  2-guest data under-serves villas).
- **Recurring scrape cadence + demand-aware pricing** (price-move and
  availability/`scarcity_text` time series) beyond the Phase 4 monitoring layer
  -- the real unlock for dynamic weekly/monthly *optimization* rather than
  positioning.
- **Clustering-based market segmentation** (will reuse Phase 2 proximity/
  similarity). All consume the same committed Parquet/history contracts.
