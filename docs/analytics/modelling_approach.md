# Post-Scraping Modelling Approach (As Built)

This document explains how the committed downstream analytics actually work:
the method, why each choice was made, what gets produced, and how to read the
numbers. It describes the code that exists today, not a future plan. For the
original design rationale and staged build plan, see
[pricing_analytics_roadmap.md](pricing_analytics_roadmap.md).

## What the analytics do

Given the Booking.com scrape, the goal is **actionable competitive-positioning
advice for one Chania self-catering operator** (apartments and villas): where
their nightly price sits versus comparable competitors, who those competitors
are, and how much of any price gap is explained by features versus left
unexplained.

Three framing decisions drive everything and are deliberate, not incidental:

- **Positioning, not optimization.** Every observation is a *listed asking
  price for an available offer* -- not a transacted price and not demand. So
  the deliverable is "where you sit versus comparable supply," not a
  revenue-optimal price. True optimization would need demand/occupancy signal
  from recurring scrapes, which is out of scope.
- **Comparables-first; hedonic is the adjustment/explanation layer.** The peer
  price benchmark is the headline because it is intuitive and directly
  defensible. The hedonic model exists only to (a) feature-adjust comps to
  like-for-like and (b) decompose a price gap into explained + residual parts.
  It is intentionally *not* the centerpiece.
- **2-guest pricing, controlled by construction.** The scrape used
  `group_adults=2`, so the entire dataset is 2-guest nightly prices. This makes
  occupancy a clean control (apples-to-apples) and removes any per-person/
  per-bed normalization: the benchmark unit is simply **EUR/night for a 2-guest
  booking**. Whole-villa / large-party pricing is therefore *under-served* (all
  villas were captured at 2 guests) and is flagged wherever a villa is the
  subject.

## Pipeline at a glance

```text
modelling_table.parquet            committed durable input (one row per rate offer)
  -> loader.load_modelling_table   decode nested JSON, parse dates, validate invariants
  -> segment.segment_self_catering keep Apartment/Aparthotel/Holiday home/Villa
  -> competitors (Phase 2)         peer set + price benchmark        [HEADLINE]
  -> hedonic     (Phase 3)         feature-adjusted comps + gap split [SUPPORT]
  -> outputs                       reports / workbook / dashboard / narrative
```

| Stage | Module | Produces |
| --- | --- | --- |
| Load + validate | [loader.py](../../tourism_pricing_analytics/analysis/loader.py) | clean in-memory frame |
| Segment | [segment.py](../../tourism_pricing_analytics/analysis/segment.py) | self-catering rows |
| Comparables | [competitors.py](../../tourism_pricing_analytics/analysis/competitors.py) | peer set, price benchmark, percentile |
| Hedonic | [hedonic.py](../../tourism_pricing_analytics/analysis/hedonic.py) | OLS premia, GBM, adjusted comps, gap split |
| Narrative | [narrative.py](../../tourism_pricing_analytics/analysis/narrative.py) | plain-language client report |

## Input contract

`data/modelling/modelling_table.parquet` is the durable input (5,331 rows x 53
columns, one row per available rate offer; provenance in
[data/modelling/README.md](../../data/modelling/README.md)).
[load_modelling_table](../../tourism_pricing_analytics/analysis/loader.py)
decodes JSON-encoded nested columns (amenities, subscores, facilities, nearby
POIs, etc.), parses dates, and enforces invariants before any analysis runs:
required/non-null columns present, `checkout > checkin`, strictly positive
prices and stay lengths, and `price_per_night == current_price_value /
stay_length_days`. Bad data fails fast rather than silently biasing a model.

The **self-catering segment** ([segment.py](../../tourism_pricing_analytics/analysis/segment.py))
keeps `Apartment`, `Aparthotel`, `Holiday home`, `Villa` (with `Guest house`
behind a flag), dropping hotels/resorts and parser glitches. This is the
training and benchmarking population.

## Stage 1 -- Comparables benchmark (headline)

Implemented in [competitors.py](../../tourism_pricing_analytics/analysis/competitors.py).

**Method.** Collapse the segment to one profile per property
(`build_property_profiles`), then score every candidate against the subject by a
weighted blend (default 50/50) of:

- **Geographic similarity** -- `haversine_km` great-circle distance, mapped to
  `1 - distance/max_distance_km` (default `max_distance_km = 8`).
- **Feature similarity** -- a weighted mix of property-type match, room size,
  bed count, review score, star rating, and amenity/facility Jaccard overlap
  (`FEATURE_COMPONENT_WEIGHTS`). Each component is skipped when missing on
  either side, so missingness never silently scores as "identical."

`rank_competitors` returns the top-`k` peers; the weights reduce to pure
proximity or pure similarity at the extremes. `peer_price_benchmark` then
matches peer **price rows** to the subject's exact `(checkin, lead_time,
stay_length)` windows and reports the peer EUR/night distribution (min, p10,
p25, median, mean, p75, p90, max), the subject's **percentile position**, and
the gap to the peer median. Clients can be an in-data Booking URL **or** a
hand-entered spec dict (`ComparableClientSpec`) for properties outside the
scrape.

**Why.** A peer-set range ("comparable listings on your dates ask EUR X-Y; you
sit at the Nth percentile") is the most intuitive, defensible, directly
actionable statement the data honestly supports.

**Outputs / interpretation.** `subject_percentile_vs_peers` and
`price_gap_to_peer_median(_pct)` are the headline numbers. Quality `flags`
("weak_peer_set", "sparse_peer_price_coverage", "villa_2_guest_undercoverage",
"no_subject_price_rows", ...) tell you when a benchmark rests on thin coverage
and should be read with caution.

## Stage 2 -- Hedonic model (support)

Implemented in [hedonic.py](../../tourism_pricing_analytics/analysis/hedonic.py).
Target is `log(price_per_night)`; groups are `property_url`.

### Design matrix

Built once into a frozen `HedonicFeatureMeta` (so future rows transform exactly
like training rows). Features:

- **Numeric property attributes:** `room_size_sqm`, `bed_count`, `star_rating`,
  `review_score`, `review_count`, `nearest_poi_km`, `nearby_poi_count`.
- **Booking-window covariates:** `lead_time_days`, `stay_length_days`,
  `checkin_month`, `checkin_is_weekend`.
- **Ordinals:** `meal_plan_ordinal`, `cancellation_flexibility_ordinal`.
- **Review subscores:** one `subscore_*` column per key found.
- **Categoricals (one-hot):** `property_type`, `crete_season`.
- **Multi-hot text:** `amenity__*`, `facility__*`, kept above a frequency floor
  (`min_token_frequency = 25`) to control dimensionality against ~154
  properties.
- **Raw geo:** `latitude`, `longitude` (GBM only -- see below).
- **Missingness flags:** `<col>_missing` for any numeric with nulls, with median
  imputation of the underlying value. Missingness is itself signal.

Identifiers, raw price columns, free text, `max_persons` (constant at 2), etc.
are excluded, and a leakage guard raises if any reaches the matrix.

### Two models, one matrix

- **Model A -- OLS** (`statsmodels`, HC3 robust SEs) for **interpretable
  market premia**. Uses a reduced feature set: drops raw lat/lon, drops the
  reference level of each categorical, and drops the amenity/facility multi-hot.
- **Model B -- gradient boosting** (`sklearn`, seed 10001) using the **full**
  feature set, evaluated with **GroupKFold by `property_url`** so no property
  appears in both train and test. Out-of-sample R2/MAE reported in log and EUR.

### Two uses

- **Feature-adjusted comps** (`feature_adjusted_peer_prices`): predict each peer
  twice -- as itself and with the client's feature profile substituted in -- and
  multiply the peer's **actual** price by `exp(client_pred - peer_pred)`. This
  anchors on real prices and applies only the *model-implied ratio*, so common
  model error largely cancels.
- **Price-gap decomposition** (`explain_price_gap`): `observed_gap =
  feature_explained_gap + residual_gap`, where the explained part is the
  difference of GBM predictions and the residual is `observed - explained`. The
  **residual** (brand, photos, pricing power, mispricing) is the most actionable
  signal. Per-feature attribution of the gap uses `shap.TreeExplainer` on Model
  B (`top_feature_contributions_log_points`), and degrades gracefully to an
  empty list if SHAP is unavailable.

## Outputs and how to read them

| Artifact | Built by | Contents |
| --- | --- | --- |
| `data/modelling/competitor_report.md` | `scripts/run_competitors.py` | peer set + benchmark range for a client |
| `data/modelling/hedonic_report.md` | `scripts/run_hedonic.py` | OLS premia, CV metrics, adjusted benchmark, sample gap split |
| `data/modelling/competitive_pricing_workbook.xlsx` | `scripts/export_pricing_workbook.py` | client-facing multi-sheet export |
| `data/modelling/positioning_narrative.md` | `scripts/run_positioning_narrative.py` | plain-language narrative for a non-technical operator |
| local dashboard | `scripts/run_dashboard.py` | interactive stdlib HTTP view over the same helpers |

Reading the metrics:

- **GBM out-of-sample R2 (log) ~ 0.31, MAE ~ EUR 53/night.** Measurable
  features explain only ~31% of cross-property price variation out of sample; a
  typical single-listing prediction is off by ~EUR 53. Treat model output as a
  *well-informed adjustment, not an exact valuation*. The feature-adjusted comps
  and gap split are more robust than this R2 alone implies, because they use
  *ratios/differences* anchored on real prices, where common error cancels.
- **OLS coefficients are log-points** (~ percentage premia): e.g. a `+0.13`
  `star_rating` coefficient ~ a ~13% premium per star. Use them for talking
  points, not point prediction.

### Interpretation caveats (important)

- **`subscore_value_for_money` is endogenous.** Booking's value-for-money
  rating reacts to price (a high price depresses perceived value), so its large
  negative OLS coefficient is largely mechanical, not an actionable premium.
  Discount it (and similar price-reactive subscores) when reading OLS premia.
- **OLS condition number is extremely large** (~1e17) due to unscaled,
  collinear numeric features. Individual OLS coefficient magnitudes/signs among
  correlated subscores are numerically unstable; standardizing inputs would fix
  this. Lean on the GBM-based adjustment for anything quantitative.
- **Asking prices, not demand.** No conclusion here speaks to occupancy or
  revenue. A high percentile means "priced above comparable supply," which may
  be defended pricing power *or* over-pricing risk -- the data cannot tell which
  without demand signal.
- **Villas are under-served** at 2-guest occupancy; villa subjects carry a
  `villa_2_guest_undercoverage` flag.

## Reproduce

```powershell
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python -m unittest discover -s tests
.\.venv\Scripts\python.exe scripts\run_competitors.py
.\.venv\Scripts\python.exe scripts\run_hedonic.py
.\.venv\Scripts\python.exe scripts\run_positioning_narrative.py
.\.venv\Scripts\python.exe scripts\export_pricing_workbook.py
.\.venv\Scripts\python.exe scripts\run_dashboard.py
```
