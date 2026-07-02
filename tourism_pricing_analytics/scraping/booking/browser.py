import logging
import random
import time

from playwright.sync_api import Browser, BrowserContext, Page, Route

from tourism_pricing_analytics.scraping.booking.models import ScraperConfig, ScrollConfig
from tourism_pricing_analytics.scraping.booking.parsing import get_locator_text


# Resource types that carry no data we extract. Prices, room/property text, the
# facilities markup, and the photo-count label are all HTML/XHR; images, media,
# and fonts only inflate the renderer's working set. Aborting them cuts per-page
# memory ~40-50% and speeds navigation, which is what lets several headless
# workers coexist on a RAM-constrained host without pagefile thrash. Stylesheets
# are kept because visibility checks (is_visible) and scroll-into-view depend on
# layout.
BLOCKED_RESOURCE_TYPES: frozenset[str] = frozenset({"image", "media", "font"})

# Chromium launch flags that lower each worker's footprint. --disable-dev-shm-usage
# avoids the small /dev/shm tmpfs (writes to disk-backed temp instead of failing),
# the renderer/process caps and js heap cap bound per-tab growth, and disabling
# extensions/background networking trims idle overhead.
MEMORY_SAVING_BROWSER_ARGS: tuple[str, ...] = (
    "--disable-dev-shm-usage",
    "--renderer-process-limit=1",
    "--js-flags=--max-old-space-size=512",
    "--disable-extensions",
    "--disable-background-networking",
)


# A single BrowserContext/Page reused across a worker's whole slice (~800
# navigations) grows without bound: the Chromium renderer never fully reclaims
# session history, detached DOM and caches, and Playwright retains the Request/
# Route objects that route interception creates for every request tied to the
# page's lifetime. Closing the context (all its pages + renderer) and opening a
# fresh one every N properties releases both sides, keeping each worker flat
# instead of ramping to ~600 MB.
#
# The cadence is expressed in *properties*, but the two phases differ sharply in
# navigations per property: room inventory is ~1, the price phase is ~15 (one per
# date window). Recycling every 10 properties in the price phase means ~150
# navigations of object churn between recycles, and CPython holds that high-water
# mark as RSS even after the context is freed. So the price phase recycles far
# more often to keep the per-cycle peak (and thus the plateau) low.
CONTEXT_RECYCLE_EVERY_N_PROPERTIES: int = 10
PRICE_CONTEXT_RECYCLE_EVERY_N_PROPERTIES: int = 3


def should_block_resource(resource_type: str) -> bool:
    """Return True for request resource types safe to abort for memory savings."""

    return resource_type in BLOCKED_RESOURCE_TYPES


def block_heavy_resources(context: BrowserContext) -> None:
    """Abort image/media/font requests on every page in the context."""

    def _route(route: Route) -> None:
        if should_block_resource(route.request.resource_type):
            route.abort()
        else:
            route.continue_()

    context.route("**/*", _route)


def new_scraper_context(browser: Browser, scraper_config: ScraperConfig) -> BrowserContext:
    """Create a browser context with the memory-saving resource blocking applied."""

    context = browser.new_context(
        user_agent=scraper_config.browser.user_agent,
        viewport={
            "width": scraper_config.browser.viewport.width,
            "height": scraper_config.browser.viewport.height,
        },
    )
    block_heavy_resources(context)
    return context


def recycle_context(
    browser: Browser,
    context: BrowserContext,
    scraper_config: ScraperConfig,
) -> tuple[BrowserContext, Page]:
    """Close the current context and return a fresh context and page.

    Releases the accumulated renderer working set and Playwright network object
    graph that grow across many navigations on a long-lived context. Closing is
    best-effort so a teardown error never aborts the scrape.
    """

    try:
        context.close()
    except Exception:
        logging.debug("Failed to close context during recycle", exc_info=True)
    new_context = new_scraper_context(browser, scraper_config)
    return new_context, new_context.new_page()


def should_recycle_context(property_index: int, recycle_every: int) -> bool:
    """True when the context should be recycled before processing this property.

    Recycling happens at property boundaries only (never mid-property, so all of
    a property's date windows share one context). Index 0 is skipped because the
    caller supplies a fresh context for the first property.
    """

    if recycle_every <= 0:
        return False
    return property_index > 0 and property_index % recycle_every == 0


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


# The whole-property facilities section (and the "Languages spoken" group nested
# inside it) is lazy-loaded further down the page than the fixed-round
# noisy_scroll reaches, so it stays empty unless we explicitly bring it into view.
_FACILITIES_ANCHOR_SELECTORS = (
    '[data-testid="property-facilities-block-container"]',
    "#hp_facilities_box",
)
_FACILITIES_CONTENT_SELECTOR = '[data-testid="facility-group-container"]'


def ensure_property_facilities_loaded(page: Page, timeout_ms: int = 3000) -> bool:
    """Best-effort scroll the lazy-loaded facilities section into view.

    Returns True once a facility group is attached. Never raises: a miss leaves
    the property-feature extractors to record null, as designed.
    """
    for anchor_selector in _FACILITIES_ANCHOR_SELECTORS:
        try:
            anchor = page.locator(anchor_selector).first
            if anchor.count() == 0:
                continue
            anchor.scroll_into_view_if_needed(timeout=timeout_ms)
            human_pause(0.4, 0.9)
            try:
                page.locator(_FACILITIES_CONTENT_SELECTOR).first.wait_for(
                    state="attached", timeout=timeout_ms
                )
            except Exception:
                logging.debug("Facilities content did not attach after scroll", exc_info=True)
            return page.locator(_FACILITIES_CONTENT_SELECTOR).count() > 0
        except Exception:
            logging.debug(
                "Facilities scroll attempt failed for %s", anchor_selector, exc_info=True
            )
    logging.info("No facilities section anchor found to scroll into view")
    return False


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
    pauses = scraper_config.pauses
    human_pause(pauses.post_nav_min_ms / 1000, pauses.post_nav_max_ms / 1000)
    dismiss_cookie_banner(page)
    if scroll_page:
        noisy_scroll(page, scraper_config.scroll)
    return response.status if response is not None else None
