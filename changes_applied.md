# Changes Applied

## 2026-06-03

- Updated `docs/scraping/scraper_design.md` with live Booking.com findings confirmed via Playwright MCP, including the undated room-inventory flow, dated price-table flow, and stable DOM patterns for search results and property pages.
- Added `docs/scraping/next_pass_refactor_plan.md` with a phased implementation plan for refactoring `notebooks/property_page_scraper.py` into a structured room-inventory and dated-price extractor.
- Implemented Phase 1 of the scraper refactor by adding `config/booking_scraper_config.json`, extending `config.py` with config/output paths, and refactoring `notebooks/property_page_scraper.py` to load centralized settings, seed randomness with `10001`, build property URLs in one place, and iterate over an explicit property target list with per-property output folders.
