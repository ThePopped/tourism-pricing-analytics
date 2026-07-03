# Modelling Table Export

`modelling_table.parquet` is the durable downstream analytics input built from
completed Booking.com scrape runs:

- Source runs:
  - `saved_dom/runs/headed8_full_20260703_113337`
  - `saved_dom/runs/headed8_retry_challenges_20260703_133957`
  - `saved_dom/runs/stavros_targeted_20260703`
- Export command:
  `.\.venv\Scripts\python.exe scripts\export_modelling_table.py --run-dir saved_dom\runs\headed8_full_20260703_113337 --run-dir saved_dom\runs\headed8_retry_challenges_20260703_133957 --run-dir saved_dom\runs\stavros_targeted_20260703`
- Export date: 2026-07-03
- Shape: 4,702 rows x 53 columns
- Properties: 295, including Stavros Villas & Apartments
- Grain: one row per available Booking.com rate offer
- Price unit: EUR/night for 2 guests, computed as
  `current_price_value / stay_length_days`

The export combines runs in the order provided. Later runs replace earlier rows
for the same `property_url`, so a retry run can cleanly supersede a full run for
the properties it revisited, and a targeted client run can ensure the dashboard
has same-window subject data. Source run directories are generated local data and
remain git-ignored. This Parquet file is committed so analysis code has a stable
input without requiring the full scrape artifacts.

`hedonic_training_table.parquet` is the broader committed training table used
for the feature-adjustment model. The local Gerani table above remains the
comparable/peer market for Stavros, while the hedonic model trains on the
broader Chania/Crete property set to improve out-of-sample stability:

- Source commit: `d9b5feb` (`data/modelling/modelling_table.parquet` at that point)
- Shape: 5,331 rows x 53 columns
- Self-catering training segment: 1,583 rows across 154 properties

`competitive_pricing_workbook.xlsx` is a client-facing export built from the
same table, comparable benchmark, and hedonic adjustment helpers:

- Client subject: Stavros Villas & Apartments
- Export command:
  `.\.venv\Scripts\python.exe scripts\export_pricing_workbook.py --subject-url https://www.booking.com/hotel/gr/stavros-villas-amp-apartments.en-gb.html --training-path data\modelling\hedonic_training_table.parquet`
- Sheets: summary, benchmark windows, peer set, raw peer rows, adjusted peer
  rows, and gap decomposition

`positioning_narrative.md` is a single client-facing positioning narrative that
turns the raw figures in `competitor_report.md` and `hedonic_report.md` into
plain-language prose for a non-technical operator:

- Client subject: Stavros Villas & Apartments
- Run command:
  `.\.venv\Scripts\python.exe scripts\run_positioning_narrative.py --subject-url https://www.booking.com/hotel/gr/stavros-villas-amp-apartments.en-gb.html --training-path data\modelling\hedonic_training_table.parquet`
- Reuses the same hedonic report payload as the workbook and dashboard, then
  renders a bottom line, peer set, price position, a feature-justified vs
  unexplained premium split, a recommendation, and interpretation caveats.

`scripts\run_dashboard.py` serves an interactive local view over this same
table and the comparable/hedonic helpers:

- Run command: `.\.venv\Scripts\python.exe scripts\run_dashboard.py`
- Zero extra dependencies: a stdlib `http.server` app that fits the hedonic
  model once at startup from `hedonic_training_table.parquet`, then re-runs
  only the local peer benchmark per selection.
- Pick a self-catering subject property and benchmark window in the browser to
  see peer price position, the feature-adjusted benchmark, and the price-gap
  decomposition.

Nested fields are JSON-encoded strings in Parquet for deterministic round trips:

- `quantity_options`
- `bed_types`
- `amenities`
- `review_subscores`
- `property_facilities`
- `nearby_poi`
- `house_rules`
- `languages_spoken`

Downstream loaders should decode those columns before feature engineering that
needs list or dictionary structure.

## Movement History

Local generated history stores back the dashboard's Price Movements tab
(`/api/movements`):

- `price_observations.parquet`: append-only available rate-offer observations by
  snapshot.
- `offer_presence.parquet`: append-only searched property/window presence rows,
  including availability and scrape status.
- `demand_covariates.csv`: optional manually maintained external context joined
  by `checkin` and `market`. When absent, the dashboard reports
  `No external covariates loaded.` and covariates act as context labels only.

Both Parquet stores are generated operating history and are git-ignored; only
this documentation (and any small fixtures) is promoted to the repository.
Rebuild them locally from scrape runs under `saved_dom/runs/`.

### Rebuild command

Append one run to the default stores
(`data/modelling/price_observations.parquet` and
`data/modelling/offer_presence.parquet`):

```powershell
.\.venv\Scripts\python.exe scripts\append_price_observations.py --run-dir saved_dom\runs\20260629_180820_565010
```

Use `--latest` to append the most recent run automatically, or
`--observations-out` / `--presence-out` to target alternate paths. The append is
idempotent: rows dedupe by snapshot/property/window/occupancy identity (plus
`room_id`/`block_id` for observations), so re-running a run is safe.

### Dashboard table rebuild command

Build the current combined dashboard table from the July 3 full run, recovery
retry, and targeted Stavros scrape:

```powershell
.\.venv\Scripts\python.exe scripts\export_modelling_table.py `
  --run-dir saved_dom\runs\headed8_full_20260703_113337 `
  --run-dir saved_dom\runs\headed8_retry_challenges_20260703_133957 `
  --run-dir saved_dom\runs\stavros_targeted_20260703
```

### Validation (2026-07-01)

Appending the local runs surfaced a data-quality gate in
`normalize_price_observations`: runs with non-numeric `latitude`/`longitude`
(the `20260603`-`20260621_185648` batch) or null `room_id`
(`20260622_105842`, `20260623_222416`) are rejected rather than written. Four
runs appended cleanly:

- `20260621_213828_860429`, `20260621_220852_666082` (snapshot `2026-06-21`)
- `20260622_092716_253958` (snapshot `2026-06-22`)
- `20260629_180820_565010` (snapshot `2026-06-29`)

Resulting store shapes:

- `price_observations.parquet`: 2,282 rows x 22 columns, 77 properties across
  the three snapshot dates.
- `offer_presence.parquet`: 1,950 rows x 19 columns (`available` 513,
  `no_available_offer` 1,437).

These runs used lead-time-relative checkin windows, so absolute stay dates
mostly differ across snapshots; comparable cross-snapshot movement concentrates
on the `2026-07-06` checkin shared by the `2026-06-22` and `2026-06-29`
snapshots. This is expected until a fixed-window daily cadence lands, and the
movement table degrades to the `unknown` availability state (rendered as the
low-history dashboard case) where no comparable previous snapshot exists.

Sample `/api/movements` result for subject
`samonas-orange-villa-diktamos` (stay 4, lead time 7) over that overlap:
market pressure **firming (+38.2 index points)**, subject offer **available at
EUR 206.75/night, down 12.0%** from EUR 235.00, recommended action
**Increase test** (medium confidence) with reason codes `market_firming`,
`property_specific_discount`, `lead_time_compression`, `possible_price_headroom`,
and `external_covariates_missing`. The payload is JSON-safe (`allow_nan=False`).

### Validation (2026-07-03)

The headed 8-worker full Chania scrape completed, then a headed 4-worker retry
revisited challenged/aborted properties. A one-property headed Stavros scrape was
run afterward because the generated Chania candidate config had previously
dropped baseline/client targets. The config generator now preserves baseline
targets first.

Current local generated history stores after appending the fresh Stavros run:

- `price_observations.parquet`: 8,723 rows x 22 columns.
- `offer_presence.parquet`: 9,576 rows x 19 columns.

For Stavros, the Price Movements tab has enough snapshots overall, but movement
signals are only meaningful where the selected window has current and previous
subject/peer prices. On 2026-07-03 the `60/4` and `60/7` windows have usable
movement signals; `7/4`, `7/7`, `30/4`, and `30/7` are limited by scrape misses,
newly available state, unavailable state, or missing previous peer medians.
