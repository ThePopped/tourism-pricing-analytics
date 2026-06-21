"""One-off helper to capture a real Booking.com discounted-rate page as a fixture.

Navigates to a Selected Suites dated page known (from run 20260621_115932_254135)
to surface discounted rates with ``.bui-price-display__original`` strikethrough
prices, then saves the full DOM to the sample fixture directory so the price
parser can be regression-tested against a real discounted layout.
"""

import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from playwright.sync_api import sync_playwright

from tourism_pricing_analytics.scraping.booking.browser import navigate_to_page
from tourism_pricing_analytics.scraping.booking.config import load_scraper_config
from tourism_pricing_analytics.scraping.booking.io import save_full_page_dom
from tourism_pricing_analytics.scraping.booking.urls import build_dated_url

TARGET_URL = "https://www.booking.com/hotel/gr/selected-suites.en-gb.html"
CHECKIN = date(2026, 6, 28)
CHECKOUT = date(2026, 7, 2)
FIXTURE_DIR = PROJECT_ROOT / "data" / "sample" / "raw_html"
FIXTURE_NAME = "selected_suites_discounted_page.html"


def main() -> None:
    scraper_config = load_scraper_config()
    dated_url = build_dated_url(
        TARGET_URL,
        checkin=CHECKIN,
        checkout=CHECKOUT,
        default_search=scraper_config.default_search,
    )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=scraper_config.browser.headless,
            slow_mo=scraper_config.browser.slow_mo_ms,
        )
        try:
            context = browser.new_context(
                user_agent=scraper_config.browser.user_agent,
                viewport={
                    "width": scraper_config.browser.viewport.width,
                    "height": scraper_config.browser.viewport.height,
                },
            )
            page = context.new_page()
            navigate_to_page(page, dated_url, scraper_config, scroll_page=False)
            page.wait_for_timeout(scraper_config.timeouts.final_wait_ms)
            original_count = page.locator(".bui-price-display__original").count()
            row_count = page.locator("tr.js-rt-block-row").count()
            print(f"price rows: {row_count}; discounted (original) prices: {original_count}")
            save_full_page_dom(page, FIXTURE_DIR, FIXTURE_NAME)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
