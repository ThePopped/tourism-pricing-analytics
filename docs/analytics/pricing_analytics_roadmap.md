# Competitive Pricing Analytics Roadmap

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
  availability/`scarcity_text` time series) -- the real unlock for dynamic
  weekly/monthly *optimization* rather than positioning.
- **Clustering-based market segmentation** (will reuse Phase 2 proximity/
  similarity) and **dashboarding**. All consume the same committed Parquet.
