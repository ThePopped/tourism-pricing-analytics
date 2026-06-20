# Repository Guidelines

## Project Structure & Module Organization

This repository supports tourism pricing analytics for Crete properties, starting with Booking.com scraping.

- `notebooks/property_page_scraper.py`: thin Playwright scraper entrypoint.
- `tourism_pricing_analytics/scraping/booking/`: reusable Booking.com scraping modules for config, URLs, parsing, failure classification, browser orchestration, persistence, and runner logic.
- `config.py`: repository path constants.
- `config/booking_scraper_config.json`: scraper seed, browser settings, date windows, occupancy, and property targets.
- `docs/scraping/`: scraper design notes and refactor plan.
- `tests/`: `unittest` coverage for scraper parsing, config, date, and URL helpers.
- `data/sample/raw_html/`: saved HTML samples for parser exploration.
- `saved_dom/runs/`: local scrape outputs and debug artifacts. Treat these as generated data.

## Build, Test, and Development Commands

```powershell
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python -m unittest discover -s tests
python -m py_compile notebooks\property_page_scraper.py config.py
python notebooks\property_page_scraper.py
```

Use these to activate the environment, install locally with development extras, run tests, compile-check Python, and run the scraper.

## Coding Style & Naming Conventions

Use Python 3 style with 4-space indentation, type hints for new helpers, and small functions with explicit inputs and outputs. Keep constants uppercase, dataclasses in `PascalCase`, and functions/variables in `snake_case`. Prefer deterministic helpers for URL, date, parsing, and serialization. Declare dependencies in `pyproject.toml`. Use random seed `10001`.

## Testing Guidelines

Tests use standard-library `unittest`. Name files `tests/test_*.py` and classes descriptively, for example `ScraperConfigAndUrlTests`. Add unit tests for pure logic first: price parsing, date windows, URLs, serialization, and config loading. For parsers, add fixture tests against saved HTML before scaling live scraping.

After each completed phase of an implementation plan, the next required action is a full, rigorous test sweep of the project code before starting the following phase. This must not be limited to smoke tests. Run the complete relevant test suite, compile checks, fixture/parser coverage, and any rigorous live scraper validation needed to be absolutely certain the project still works end to end at that point.

## Implementation Priorities

Fix data correctness before scale. Add regression tests for scraped-output bugs. Keep reusable scraper logic in package modules and leave `notebooks/property_page_scraper.py` as a thin manual entrypoint. Treat `saved_dom/runs/` as generated output; promote only small representative HTML files to fixtures.

## Commit & Pull Request Guidelines

Use clear, imperative commit subjects, for example `Fix price normalization` or `Add scraper URL tests`. Perform git commits regularly at logical milestones instead of waiting until a long work session is complete. Keep each commit focused on one logical change or completed plan phase, and commit only after the required rigorous test sweep for that phase has passed. Use the body for context, data-shape impact, migration notes, or risks. PRs should include a summary, tests run, linked issue or task when available, and any scraper output evidence.

## Session Notes Policy

Use git commits and PRs for change history. Do not maintain a running change log. Update `session_notes.md` only when requested; replace it entirely rather than appending. Keep long-term relevant issues or next steps.

## Security & Configuration Tips

Do not commit credentials, private client data, or large generated scrape runs. Keep configurable scraper behavior in `config/booking_scraper_config.json`; avoid hard-coding property lists, dates, or browser settings in parser code.
