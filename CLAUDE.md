# CLAUDE.md

This file provides implementation guidance for Claude Code and other coding agents working in this repository.

## Project Purpose

This project builds a pricing analytics pipeline for tourism properties in Crete. The current focus is Booking.com ingestion: collect room inventory and dated rate rows, then prepare reliable data for future clustering, hedonic pricing, monitoring, and dashboarding.

## Current Phase

The active implementation area is data ingestion and scraper hardening.

- Current entrypoint: `notebooks/property_page_scraper.py`
- Config: `config/booking_scraper_config.json`
- Tests: `tests/`
- Scraper docs: `docs/scraping/`
- Generated scrape output: `saved_dom/runs/<timestamp>/`

The near-term goal is to protect scraper behavior with unit and fixture tests, then migrate reusable scraper logic from the notebook script into package modules.

## Development Standards

- Use random seed `10001` for reproducible behavior.
- Keep commits focused and use imperative subjects, for example `Fix price normalization`.
- Use regular git commits and pull requests as the source of change history. Commit at logical milestones throughout the work, especially after each completed plan phase, instead of waiting until a long session is complete.
- Add or update tests for parser, config, URL, date, serialization, and data-quality changes.
- Prefer small deterministic helper functions over large browser-coupled blocks.
- Declare new runtime or development dependencies in `pyproject.toml`.
- Do not commit credentials, private client data, or large generated scrape runs.

## Session Notes Policy

`session_notes.md` is a current handoff/status document, not a change log. Update it only when the user requests it. When updating it, replace the file entirely rather than appending to it, while preserving long-term relevant known issues, remaining work, and next recommended steps.

## Environment And Commands

```powershell
.\.venv\Scripts\Activate.ps1
pip install -e .
python -m unittest discover -s tests
python -m py_compile notebooks\property_page_scraper.py config.py
python notebooks\property_page_scraper.py
```

When linting or formatting tools are added, document their commands here and in `AGENTS.md`.

## Scraper Architecture Guidance

The scraper should keep three concerns separate:

1. Browser orchestration: navigation, cookie handling, page loading, retries.
2. Parsing: pure extraction logic for room inventory and price rows.
3. Persistence: JSONL/CSV output and debug artifact writing.

Prefer direct dated URLs over calendar interaction. Keep raw text fields, such as price and rate conditions, alongside normalized numeric values. Preserve Booking identifiers such as `room_id` and `block_id`.

## Testing Guidance

Follow the staged testing plan in `docs/scraping/next_pass_refactor_plan.md`.

- Unit tests first for pure logic: config, date windows, URLs, price parsing, per-night calculation, serialization.
- Fixture parser tests next using saved undated and dated HTML snapshots.
- Rigorous live scraper validation last, with output evidence under `saved_dom/runs/`, covering enough configured properties and date windows to verify the system end to end rather than merely confirming that a smoke test starts.

After each completed phase of an implementation plan, the next required action is a full, rigorous test sweep of the project code before beginning the next phase. Do not skip pieces for speed and do not treat a smoke test as sufficient. Run the complete relevant unit tests, compile checks, fixture/parser tests, serialization checks, and rigorous live scraper validation needed to be absolutely certain everything works thus far. Only commit the completed phase after that full sweep passes.

Any bug found in scraped output should get a regression test before expanding the scrape.

## Error Handling And Data Quality

Classify scraper failures clearly instead of logging all empty results the same way. Use categories such as empty availability, selector drift, redirect, invalid property URL, partial load, blocked page, and temporary Booking.com error. Continue per property/date window where possible, but preserve enough debug HTML to diagnose failures.

Before data moves downstream, check for impossible prices, missing date fields, duplicate room inventory records, and null room ids that need review.

## Package Direction

`notebooks/property_page_scraper.py` can remain the manual entrypoint for now, but reusable logic should move toward:

- `tourism_pricing_analytics/scraping/booking/models.py`
- `tourism_pricing_analytics/scraping/booking/urls.py`
- `tourism_pricing_analytics/scraping/booking/property_inventory.py`
- `tourism_pricing_analytics/scraping/booking/property_prices.py`
- `tourism_pricing_analytics/scraping/booking/io.py`

Do this after fixture tests exist, so behavior is protected during the refactor.
