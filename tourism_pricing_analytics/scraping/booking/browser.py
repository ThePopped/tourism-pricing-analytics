import logging
import random
import time

from playwright.sync_api import BrowserContext, Page

from tourism_pricing_analytics.scraping.booking.models import ScraperConfig, ScrollConfig
from tourism_pricing_analytics.scraping.booking.parsing import get_locator_text


def human_pause(a: float = 0.2, b: float = 0.7) -> None:
    duration = random.uniform(a, b)
    logging.debug("sleeping for %.2f", duration)
    time.sleep(duration)


def noisy_scroll(page: Page, scroll_config: ScrollConfig) -> None:
    logging.info("Scrolling page with %d rounds", scroll_config.rounds)

    for round_num in range(scroll_config.rounds):
        delta = random.randint(scroll_config.min_delta, scroll_config.max_delta)
        logging.debug("scroll round %d, wheel diff=%d", round_num + 1, delta)
        page.mouse.wheel(0, delta)
        human_pause(0.2, 0.5)


def dismiss_cookie_banner(page: Page) -> bool:
    buttons_to_try = [
        page.get_by_role("button", name="Decline"),
        page.get_by_role("button", name="Accept"),
    ]

    for locator in buttons_to_try:
        try:
            if locator.count() > 0 and locator.first.is_visible():
                label = get_locator_text(locator.first) or "cookie button"
                locator.first.click()
                logging.info("Dismissed cookie banner using %s", label)
                human_pause(0.3, 0.6)
                return True
        except Exception:
            logging.debug("Cookie dismissal attempt failed", exc_info=True)

    return False


def ensure_page(context: BrowserContext, page: Page | None) -> Page:
    if page is None or page.is_closed():
        logging.warning("Creating a new Playwright page after page closure")
        return context.new_page()
    return page


def navigate_to_page(
    page: Page,
    url: str,
    scraper_config: ScraperConfig,
    scroll_page: bool = True,
) -> int | None:
    logging.info("Navigating to %s", url)
    response = page.goto(url, wait_until="domcontentloaded")
    human_pause(1.0, 2.0)
    dismiss_cookie_banner(page)
    if scroll_page:
        noisy_scroll(page, scraper_config.scroll)
    return response.status if response is not None else None
