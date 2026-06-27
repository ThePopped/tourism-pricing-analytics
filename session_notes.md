# Session Notes

## Active Focus

The Booking.com scraper scale-up is complete and stable. The downstream
competitive pricing analytics roadmap is implemented through Phase 3, and three
productization deliverables now sit on top of it: a client-facing Excel workbook
export, a small interactive local dashboard, and a single plain-language
positioning narrative report.

The agreed analytics direction remains **comparables-first**, with hedonic
modelling as the adjustment and explanation layer:

- Headline deliverable: peer-set price benchmarking from geographic proximity
  plus feature similarity.
- Hedonic model role: feature-adjust comparable prices and decompose price gaps
  into feature-explained and residual components.
- Interpretation: listed Booking.com asking prices for available offers, not
  transacted prices or demand. The output is competitive positioning, not
  revenue optimization.
- Pricing unit: EUR/night for a 2-guest Booking.com search. Large-party villa
  pricing remains under-served until a future varied-occupancy scrape.
- Analysis population: self-catering rows with `property_type` in `Apartment`,
  `Aparthotel`, `Holiday home`, and `Villa`; `Guest house` is optional.

## Downstream Analytics Status

### Phase 0: Durable Modelling Table Export

Status: **complete and committed** as `d9b5feb Add durable modelling table export`.

Implemented:

- Added downstream analytics dependencies in `pyproject.toml`: `pandas`,
  `numpy`, `scikit-learn`, `statsmodels`, `pyarrow`, and `shap`.
- Added `scripts/export_modelling_table.py`.
- Added committed durable output at `data/modelling/modelling_table.parquet`.
- Added `data/modelling/README.md` with provenance and table contract.
- Added `tests/test_export_modelling_table.py`.

Current durable table:

- Source run: `saved_dom/runs/20260623_222416_346202`
- Shape: 5,331 rows x 53 columns
- Grain: one row per available Booking.com rate offer
- Price unit: EUR/night for 2 guests
- Nested columns are JSON-encoded in Parquet and decoded by the analysis loader.

### Phase 1: Analysis Foundation

Status: **complete and committed** as `b579e36 Add analysis foundation`.

Implemented package: `tourism_pricing_analytics/analysis/`

- `loader.py`: loads and validates the committed Parquet table, verifies
  price-per-night math, decodes nested JSON columns, and parses temporal columns.
- `segment.py`: defines the agreed self-catering analysis population and stable
  property-type counts.
- `eda.py`: produces deterministic JSON-ready exploratory summaries.
- `scripts/summarize_modelling_table.py`: prints a deterministic EDA summary.
- `tests/test_analysis_foundation.py`: covers loader, segmentation, and EDA
  behavior.

Real-data Phase 1 summary:

- Full table: 5,331 rows, 53 columns, 287 properties with price availability.
- Self-catering segment: 1,583 rows across 154 properties.
- Check-in range: 2026-06-30 to 2026-08-22.
- Lead times: 7, 30, 60 days.
- Stay lengths: 4 and 7 nights.
- Self-catering median price: 163.75 EUR/night.
- Self-catering mean price: about 185.94 EUR/night.

### Pricing Analytics Roadmap

Status: **committed** as `4e121e7 Add pricing analytics roadmap`.

The roadmap lives at `docs/analytics/pricing_analytics_roadmap.md`.

Roadmap phases:

- Phase 0: durable modelling table export.
- Phase 1: analysis foundation.
- Phase 2: comparables benchmark as the headline deliverable.
- Phase 3: hedonic adjustment and price-gap explanation.

### Phase 2A: In-Data Comparable Benchmark Foundation

Status: **complete and committed** as `12125ed Add comparable benchmark analysis`.

Implemented:

- Added `tourism_pricing_analytics/analysis/competitors.py`.
- Built deterministic comparable-set selection over the self-catering segment.
- Scored peer properties using geographic proximity plus profile similarity.
- Matched peer price rows to the subject property's scraped contexts using
  `checkin`, `lead_time_days`, and `stay_length_days`.
- Returned peer price distributions, subject price distributions, subject
  percentile versus peers, price gap to peer median, coverage flags, candidate
  peer properties, and matched peer price rows.
- Added `scripts/run_comparable_benchmark.py`.
- Added synthetic comparable benchmark tests.

### Phase 2B: Comparable Benchmark Roadmap Contract

Status: **complete and committed** as `f14e430 Complete comparable benchmark contract`.

Implemented:

- Added roadmap-compatible public API:
  - `feature_similarity(client, candidates)`
  - `rank_competitors(client, df, *, w_geo, w_sim, k)`
  - `peer_price_benchmark(client, df, windows, *, k)`
- Added `ComparableClientSpec` and mapping parsing so benchmarks can run for an
  in-data Booking URL or a hand-entered apartment/villa spec.
- Added explicit benchmark windows for `checkin`, `lead_time_days`,
  `stay_length_days`, `crete_season`, and other table columns.
- Added missing-safe `bed_count` profile similarity.
- Added `scripts/run_competitors.py`, which writes
  `data/modelling/competitor_report.md` and can optionally write JSON.
- Expanded `tests/test_comparable_benchmark.py`.

Real-data Phase 2B report:

- Output: `data/modelling/competitor_report.md`
- Default subject: Anna's House
- Peer rows: 75
- Peer properties with prices: 9
- Peer IQR: EUR 122.00 to EUR 224.00
- Peer median: EUR 159.00
- Subject median: EUR 306.73
- Subject percentile vs peers: 92.0%
- Gap to peer median: EUR 147.73, about 92.9%
- Flags: none

### Phase 3: Hedonic Adjustment And Gap Explanation

Status: **complete and committed** as `26ee7fb Add hedonic price adjustment analysis`.

Implemented:

- Added `tourism_pricing_analytics/analysis/hedonic.py`.
- Built `build_design_matrix()` for `log(price_per_night)` on the self-catering
  segment, grouped by `property_url`.
- Included numeric features with median imputation and missingness flags:
  `room_size_sqm`, `bed_count`, `star_rating`, `review_score`, `review_count`,
  derived `nearest_poi_km`, derived `nearby_poi_count`, and flattened
  `subscore_*` fields.
- Included window covariates: `lead_time_days`, `stay_length_days`,
  `crete_season`, `checkin_month`, and `checkin_is_weekend`.
- Included ordinals where present: `meal_plan_ordinal` and
  `cancellation_flexibility_ordinal`.
- One-hot encoded `property_type` and `crete_season`.
- Multi-hot encoded `amenities` and `property_facilities` with a frequency
  floor for gradient boosting.
- Excluded identifiers, leakage columns, raw price columns, free text, and
  `max_persons` from the design matrix.
- Trained:
  - OLS with HC3 robust errors for interpretable market premia.
  - Gradient boosting with `GroupKFold` by `property_url` for predictive
    adjustment.
- Added `feature_adjusted_peer_prices()`.
- Added `explain_price_gap()`, splitting observed gaps into feature-explained
  and residual components.
- Added `scripts/run_hedonic.py`, which writes
  `data/modelling/hedonic_report.md` and can optionally write JSON.
- Added `tests/test_hedonic.py`.
- Exported hedonic helpers from `tourism_pricing_analytics/analysis/__init__.py`.

Real-data Phase 3 report:

- Output: `data/modelling/hedonic_report.md`
- Training rows: 1,583
- Training properties: 154
- Grouped CV folds: 5
- GBM mean log R2: 0.311
- GBM mean log MAE: 0.285
- GBM mean EUR/night MAE: EUR 53.32
- OLS R2: 0.625
- Default subject: Anna's House
- Raw peer median: EUR 159.00
- Feature-adjusted peer median: EUR 237.70

Notes:

- The OLS condition number remains high, so use the OLS coefficient table as
  directional talking points rather than a causal model. The grouped GBM output
  is the preferred adjustment engine.

### Productization And Quality Hardening 1

Status: **complete and committed** as
`7eada1b Harden analytics reports and property type parsing`.

Implemented:

- Added report-level contract tests in `tests/test_report_outputs.py` for the
  competitor and hedonic markdown reports.
- Added `data/modelling/client_spec_example.json`, a hand-entered apartment
  profile compatible with `scripts/run_competitors.py --spec-path`.
- Tightened `PropertyTypeExtractor` so property-name parentheticals such as
  `MYLOS (6)` and adult-only labels do not become `property_type`, with parser
  regression tests.

### Productization: Pricing Workbook Export

Status: **complete and committed** as
`dad29b4 Add competitive pricing workbook export`.

Implemented:

- Added `scripts/export_pricing_workbook.py`, which builds a client-facing
  `.xlsx` from the modelling table plus the comparable and hedonic helpers. The
  writer is hand-rolled OOXML (zipped sheet/styles XML) so it adds **no** new
  dependency such as openpyxl.
- Committed output at `data/modelling/competitive_pricing_workbook.xlsx`.
- Sheets: summary, benchmark windows, peer set, raw peer rows, adjusted peer
  rows, and gap decomposition.
- Added `tests/test_pricing_workbook_export.py`.
- Reuses `build_report_payload` from `scripts/run_hedonic.py` as the single
  source of payload assembly.

### Productization: Local Competitive Pricing Dashboard

Status: **complete and committed** as
`82f6b90 Add local competitive pricing dashboard`.

This is the chosen "small dashboard" deliverable from the prior open product
fork. It is a **zero-dependency** local app, consistent with the project's
minimal-dependency philosophy and able to run offline (PyPI is blocked in the
sandbox, so Streamlit/Flask were intentionally avoided).

Implemented:

- Added `tourism_pricing_analytics/analysis/dashboard.py` with the pure,
  testable pieces:
  - `subject_catalog(frame)`: deterministic self-catering subject list with
    type, price-row count, and median price; ordered to match the report
    runners' default subject.
  - `window_options(frame)`: distinct `lead_time_days`, `stay_length_days`,
    `crete_season`, and `checkin` values for the UI selectors.
  - `shape_dashboard_payload(report_payload)`: compacts a full hedonic report
    payload into a JSON-safe front-end payload (KPIs, peer/adjusted
    distributions, ranked peer table, gap decomposition, top OLS premia).
  - `render_index_html()`: the static single-page HTML/JS shell (inline CSS, an
    SVG price-position scale, vanilla-JS fetch and render). No template engine.
- Added `scripts/run_dashboard.py`, a stdlib `http.server` (`ThreadingHTTPServer`)
  app that:
  - Loads the modelling table and fits the hedonic model **once** at startup via
    a cached `DashboardService`.
  - Serves `/` (the page), `/api/meta` (subject catalog + window options), and
    `/api/benchmark` (per-selection peer benchmark, reusing the cached bundle).
  - Returns clean JSON errors (400 for an invalid subject, 404 for unknown
    routes). Flags `--host`, `--port`, `--min-token-frequency`, `--no-browser`.
- Let `scripts/run_hedonic.build_report_payload` accept an optional pre-fit
  `bundle` (backward compatible) so the dashboard avoids refitting per request.
- Exported the dashboard helpers from
  `tourism_pricing_analytics/analysis/__init__.py`.
- Added `tests/test_dashboard.py`: catalog ordering/segmentation, window
  options, payload shaping/JSON-safety, HTML shell mount points, and the
  cached-bundle service (verifies the bundle is reused, not refit).
- Documented the runner in `data/modelling/README.md`.

Real-data dashboard validation (live `http.server` run over the committed
Parquet):

- Catalog: 154 self-catering subjects; default subject Anna's House.
- Window options: lead times 7/30/60, stays 4/7, seasons peak/shoulder.
- Index served at 200 (~13 KB HTML).
- Sample benchmark (lead_time=30, stay=4, max_peers=10): peer median EUR 209.75,
  feature-adjusted peer median EUR 264.18, subject median EUR 418.00, subject
  percentile 100.0%, 9 peers, no flags.
- Error paths confirmed: invalid `subject_url` returned HTTP 400 JSON; unknown
  route returned HTTP 404.

### Productization: Client-Facing Positioning Narrative

Status: **complete and committed** as
`c729bf4 Add client-facing positioning narrative report`.

This is the previously open "markdown narrative refinement" deliverable: it
turns the raw technical numbers in `competitor_report.md` and `hedonic_report.md`
into a single plain-language positioning narrative for a non-technical operator.

Implemented:

- Added `tourism_pricing_analytics/analysis/narrative.py` with a pure,
  missing-safe `render_positioning_narrative(payload)`. It consumes the existing
  hedonic report payload (no data load or model fit) and renders sections:
  Bottom line, Who you are compared against, Your price position today, Is the
  premium justified?, Recommendation, and How to read these numbers.
- The position is classified by the **residual premium share**, i.e. the
  subject's price above (or below) the feature-matched comparable median as a
  fraction of that median. This isolates the actionable gap after crediting the
  subject for its stronger features: `>15%` over reads as an unjustified
  premium, `5-15%` mixed, `-5%..5%` fair, below `-5%` underpriced. (An earlier
  draft compared residual vs feature magnitudes and mislabeled a clear premium
  as "modest/defensible"; the residual-share read is the corrected logic.)
- Distribution-level gap decomposition in the report: feature-justified premium
  = adjusted peer median - raw peer median; unexplained premium = subject median
  - adjusted peer median.
- Added `scripts/run_positioning_narrative.py`, reusing `build_report_payload`
  from `scripts/run_hedonic.py` (same assembly as the workbook and dashboard).
  It writes `data/modelling/positioning_narrative.md` and can optionally write
  JSON. Same CLI surface as `run_hedonic.py` (subject URL or hand-entered spec,
  windows, peer/distance/token-frequency flags).
- Exported `render_positioning_narrative` from
  `tourism_pricing_analytics/analysis/__init__.py`.
- Added `tests/test_narrative.py` (synthetic-payload tests for all sections,
  premium vs underpriced language, distribution decomposition, and
  missing-figure safety) and extended `tests/test_report_outputs.py` with a
  contract test for the committed narrative file.
- Documented the runner in `data/modelling/README.md`.

Real-data narrative (default subject Anna's House):

- Output: `data/modelling/positioning_narrative.md`
- Position: priced above comparable rivals, at the very top of the peer set,
  ~92.9% over the peer median.
- Feature-justified premium: EUR 78.70; unexplained premium: EUR 69.03 (~29%
  above the feature-matched comparable median) -> classified as an unjustified
  premium to defend or watch.

Verification passed (full sweep):

- `.\.venv\Scripts\python.exe -m compileall tourism_pricing_analytics scripts notebooks config.py`
- `.\.venv\Scripts\python.exe -m unittest discover -s tests`: 228 tests OK.

## Next Recommended Step

The core roadmap, the first hardening pass, and all three deliverable formats
(workbook export, local dashboard, and positioning narrative) are implemented.
Remaining suggested next steps:

- **Dashboard polish (optional).** Possible follow-ups: hand-entered spec input
  in the UI (the helpers already support spec clients), CSV/workbook download
  buttons from the running app, a checkin-date selector alongside lead
  time/stay/season, or surfacing the positioning narrative text in the UI.
- **Varied-occupancy villa scrape.** Current villa prices are still 2-guest
  offers, so large-party villa pricing is under-served. Returns to ingestion.
- **Recurring scrape cadence.** Only worth it if the goal shifts from
  competitive positioning to demand-aware price optimization.

## Scraper Current Status

The scraper is stable and complete for the current phase of the project.

Current architecture:

- Reusable Booking.com scraper modules live under
  `tourism_pricing_analytics/scraping/booking/`.
- `notebooks/property_page_scraper.py` remains a thin manual entrypoint.
- `scripts/run_full_scrape.py` is the sharded full-run driver.
- Layer 1 feature extraction writes room and property feature streams.
- Layer 2 browser-free feature building lives under
  `tourism_pricing_analytics/features/`.
- Durable downstream analysis starts from
  `data/modelling/modelling_table.parquet`.

Latest full live run: `saved_dom/runs/20260623_222416_346202`

- Target set: 438 Chania-region properties.
- Acceptance gate: PASS.
- `validation_report.json`: `is_valid: true`, 0 issues.
- Aggregate output: 1,777 room inventory rows, 5,331 price rows, 773 room
  feature rows, 429 property feature rows, 1,633 failure records.
- Coverage: 429 properties returned inventory/features; 287 had price
  availability for the configured July-August windows; 9 returned no data.
- Resumability: 438/438 complete, 0 pending.
- Data quality: no non-positive or near-zero prices; `price_per_night` matches
  `current_price_value / stay_length_days`; no rows missing `checkin`,
  `checkout`, `stay_length_days`, or `captured_at`.
- Duplicate interpretation: repeated `(property_url, room_id, checkin,
  checkout)` keys are legitimate distinct rate offers; including `block_id`
  resolves collisions.
- Null `room_id`: 12 / 5,331 rows after Layer 2 name-to-id reconciliation.

## Current Package Structure

High-level modules:

- `tourism_pricing_analytics/scraping/booking/`: Booking.com scraper
  configuration, URLs, parsing, browser orchestration, retry/resume/sharding,
  persistence, validation, listings parsing, and runner logic.
- `tourism_pricing_analytics/scraping/booking/features/`: Layer 1 room and
  property extractors.
- `tourism_pricing_analytics/features/`: Layer 2 browser-free modelling-table
  feature build.
- `tourism_pricing_analytics/analysis/`: downstream loader, segmentation, EDA,
  comparable benchmark logic, hedonic adjustment logic, dashboard helpers, and
  the positioning narrative renderer.
- `scripts/export_modelling_table.py`: durable Parquet export.
- `scripts/summarize_modelling_table.py`: deterministic EDA summary.
- `scripts/run_comparable_benchmark.py`: deterministic JSON comparable benchmark
  runner for in-data subject URLs.
- `scripts/run_competitors.py`: roadmap Phase 2 markdown/JSON competitor report
  runner for URL or hand-entered spec clients.
- `scripts/run_hedonic.py`: roadmap Phase 3 markdown/JSON hedonic adjustment
  report runner.
- `scripts/run_positioning_narrative.py`: client-facing plain-language
  positioning narrative runner.
- `scripts/export_pricing_workbook.py`: client-facing `.xlsx` workbook export.
- `scripts/run_dashboard.py`: zero-dependency local `http.server` dashboard over
  the modelling table and analysis helpers.
- `scripts/run_full_scrape.py`: sharded full scrape entrypoint.

## Known Issues And Interpretation Limits

- **2-guest-only prices.** The current table should be interpreted as EUR/night
  for 2 guests. Do not use `max_persons` as a meaningful occupancy feature for
  the current modelling pass because it is effectively fixed by scrape
  construction.
- **Large villas are under-served.** All villa prices were scraped for 2 guests,
  so large-party villa pricing needs a varied-occupancy re-scrape.
- **Null room ids.** 12 rows still have null `room_id` after exact
  `(property_url, room_name)` reconciliation. These are honest unattributed rate
  rows rather than fuzzy matches.
- **Historic spurious property types.** The committed modelling table still
  contains historic rows with `property_type == "6"` and adult-only labels from
  the earlier scrape. The self-catering segment excludes them. The extractor is
  now hardened so future scrapes should ignore property-name/adult-only
  parentheticals and keep the actual accommodation label.
- **Sparse bed fields.** Structured bed information is absent on many Booking
  room blocks, so `bed_types` and `bed_count` are sparse by design.
- **Missing ratings and policy times.** Some properties have no official
  star/class rating or check-in/out time fields.
- **OLS collinearity.** The OLS model has a high condition number. Treat its
  coefficients as descriptive premia, not causal estimates.
- **Dashboard is local-only.** `scripts/run_dashboard.py` binds to localhost and
  has no auth; it is a single-user analyst tool, not a hosted service. The
  one-time hedonic fit at startup costs a few seconds before it serves.
- **Generated scrape outputs remain local.** Treat `saved_dom/runs/` as
  generated data. Promote only small representative HTML files to
  `data/sample/raw_html/`.
- **Booking.com can drift.** Live DOM and availability behavior remain unstable;
  new parser or failure-category bugs should become regression tests.

## Git State Notes

Latest relevant commits:

- `c729bf4 Add client-facing positioning narrative report`
- `82f6b90 Add local competitive pricing dashboard`
- `dad29b4 Add competitive pricing workbook export`
- `d3e2eef Update session notes after hardening pass`
- `7eada1b Harden analytics reports and property type parsing`
- `26ee7fb Add hedonic price adjustment analysis`
- `f14e430 Complete comparable benchmark contract`
- `4e121e7 Add pricing analytics roadmap`
- `12125ed Add comparable benchmark analysis`
- `b579e36 Add analysis foundation`

As of this refresh, `session_notes.md` is intentionally updated by request.
