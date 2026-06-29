# Modelling Table Export

`modelling_table.parquet` is the durable downstream analytics input built from
the completed Booking.com scrape run:

- Source run: `saved_dom/runs/20260629_180820_565010`
- Export command:
  `.\.venv\Scripts\python.exe scripts\export_modelling_table.py --run-dir saved_dom\runs\20260629_180820_565010`
- Export date: 2026-06-29
- Shape: 1,653 rows x 53 columns
- Grain: one row per available Booking.com rate offer
- Price unit: EUR/night for 2 guests, computed as
  `current_price_value / stay_length_days`

The source run directory is generated local data and remains git-ignored. This
Parquet file is committed so analysis code has a stable input without requiring
the full scrape artifacts.

`competitive_pricing_workbook.xlsx` is a client-facing export built from the
same table, comparable benchmark, and hedonic adjustment helpers:

- Client subject: Stavros Villas & Apartments
- Export command:
  `.\.venv\Scripts\python.exe scripts\export_pricing_workbook.py --subject-url https://www.booking.com/hotel/gr/stavros-villas-amp-apartments.en-gb.html`
- Sheets: summary, benchmark windows, peer set, raw peer rows, adjusted peer
  rows, and gap decomposition

`positioning_narrative.md` is a single client-facing positioning narrative that
turns the raw figures in `competitor_report.md` and `hedonic_report.md` into
plain-language prose for a non-technical operator:

- Client subject: Stavros Villas & Apartments
- Run command:
  `.\.venv\Scripts\python.exe scripts\run_positioning_narrative.py --subject-url https://www.booking.com/hotel/gr/stavros-villas-amp-apartments.en-gb.html`
- Reuses the same hedonic report payload as the workbook and dashboard, then
  renders a bottom line, peer set, price position, a feature-justified vs
  unexplained premium split, a recommendation, and interpretation caveats.

`scripts\run_dashboard.py` serves an interactive local view over this same
table and the comparable/hedonic helpers:

- Run command: `.\.venv\Scripts\python.exe scripts\run_dashboard.py`
- Zero extra dependencies: a stdlib `http.server` app that fits the hedonic
  model once at startup, then re-runs only the peer benchmark per selection.
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
