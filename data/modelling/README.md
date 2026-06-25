# Modelling Table Export

`modelling_table.parquet` is the durable downstream analytics input built from
the completed Booking.com scrape run:

- Source run: `saved_dom/runs/20260623_222416_346202`
- Export command: `.\.venv\Scripts\python.exe scripts\export_modelling_table.py`
- Export date: 2026-06-25
- Shape: 5,331 rows x 53 columns
- Grain: one row per available Booking.com rate offer
- Price unit: EUR/night for 2 guests, computed as
  `current_price_value / stay_length_days`

The source run directory is generated local data and remains git-ignored. This
Parquet file is committed so analysis code has a stable input without requiring
the full scrape artifacts.

`competitive_pricing_workbook.xlsx` is a client-facing export built from the
same table, comparable benchmark, and hedonic adjustment helpers:

- Export command: `.\.venv\Scripts\python.exe scripts\export_pricing_workbook.py`
- Sheets: summary, benchmark windows, peer set, raw peer rows, adjusted peer
  rows, and gap decomposition

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
