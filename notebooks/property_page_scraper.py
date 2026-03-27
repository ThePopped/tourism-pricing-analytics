import logging
import random
import time
from datetime import datetime
from pathlib import Path
from typing import TypedDict

from playwright.sync_api import Locator, Page, Playwright, sync_playwright


SAVE_ROOT = Path("saved_dom")
RUN_DIR: Path | None = None

COMMON_OPENED_SELECTORS: list[str] = [
'[role="dialog"]',
'[aria-modal="true"]',
'.modal',
'.popup',
'.popover',
'.drawer',
'.panel',
'.overlay',
'.lightbox',
'[class*="modal"]',
'[class*="popup"]',
'[class*="drawer"]',
'[class*="overlay"]',
]

URL = "https://www.booking.com/hotel/gr/solimar-aquamarine-platanias-chania.en-gb.html?"


# this script uses Playwright to automate a browser, scroll to a property page,
# and interact with elements that cause modals/popups (like "Read more" buttons).
# It gets finally captures the DOM of the newly opened elements and saves them.
class VisibleCandidate(TypedDict):
    selector: str
    index:int
    outer_html: str


def create_run_dir() -> Path:
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    run_dir = SAVE_ROOT / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def get_run_dir() -> Path:
    if RUN_DIR is None:
        raise RuntimeError("RUN_DIR is not initialized. Call main() first.")
    return RUN_DIR


def setup_logging(log_path: Path) -> None:
    logging.basicConfig(
        level=logging.INFO,

        format="%(asctime)s | %(levelname)s | %(message)s",

        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_path,
                                 encoding="utf-8"),
        ],
        )

# random pause like human behavior
def human_pause(a: float =0.2, 
                b: float =0.7) ->None:
    duration = random.uniform(a, b)


    logging.debug("sleeping for %.2f ", duration)
    time.sleep(duration)


def noisy_scroll(page: Page, rounds: int = 2) -> None:
    logging.info("Scrolling page with %d rounds", rounds)

    for round_num in range(rounds):
        # scroll down with random wheel delta to trigger any lazy loading.
        delta = random.randint(120, 450)
        logging.debug("scroll round %d, wheel diff=%d", round_num + 1, delta)
        page.mouse.wheel(0, delta)
        human_pause(0.2, 0.5)


def get_outer_html(locator: Locator) -> str | None:
    try:
        return locator.evaluate("el => el.outerHTML")
    except Exception:
        logging.exception("failed to get outerHTML")
        return None

# this gets a baseline of currently visible elements that match the common "opened" selectors.
def get_visible_candidates(page: Page, selectors: list[str]) -> list[VisibleCandidate]:
    visible: list[VisibleCandidate] = []

    for selector in selectors:
        locator = page.locator(selector)
        count = locator.count()
        logging.debug("selector %r matched %d elements", 
                      selector,
                        count)
        #  check visibility and outerHTML to create a baseline of what "opened" elements look like before clicking any triggers
        for i in range(count):
            el = locator.nth(i)
            try:
                if el.is_visible():
                    outer_html = get_outer_html(el)
                    if outer_html:
                        visible.append(
                            {
                                "selector": selector,
                                "index": i,
                                "outer_html": outer_html,
                            }
                        )
            except Exception:
                logging.exception(
                    "Error while checking visibility for selector=%r index=%d",
                    selector,
                    i,
                )

    logging.info("Found %d visible candidate opened elements", len(visible))
    return visible


def find_new_opened_element(
    page:Page,
     before_candidates: list[VisibleCandidate],
    selectors: list[str],
    wait_ms:int = 2000,
) -> Locator | None:
    logging.info("Waiting %d ms before scanning for opened element", wait_ms)
    page.wait_for_timeout(wait_ms)

    before_html_set = {item["outer_html"] for item in before_candidates}
    
    logging.debug("Baseline visible candidates: %d", len(before_html_set))

    for selector in selectors:
        locator = page.locator(selector)
        count = locator.count()
        # recheck the same selectors after clicking the trigger to see if any new elements appeared that match the "opened" 
        # patterns and were not in the baseline set.
        logging.debug("Rechecking selector %r with %d matches", selector, count)

        for i in range(count):
            el = locator.nth(i)
            try:
                if el.is_visible():
                    outer_html = get_outer_html(el)
                    if outer_html and outer_html not in before_html_set:
                        logging.info(
                            "Detected new opened element:Selector=%r index=%d",
                            selector,
                            i,
                        )
                        return el
            except Exception:
                logging.exception(
                    "Error scanning opened element selector=%r index=%d",
                    selector,
                    i,
                )

    logging.warning("No new opened element found")
    return None


def save_text_file(content: str, filepath: Path) -> Path:
    filepath.write_text(content, encoding="utf-8")
    logging.info("saved file: %s", filepath)
    return filepath


def save_element_dom(element: Locator, filename_prefix: str = "opened") -> Path | None:
    outer_html = get_outer_html(element)
    if outer_html is None:
        logging.error("Could not save element DOM because outerHTML extraction failed")
        return None

    filepath = get_run_dir() / f"{filename_prefix}.html"
    return save_text_file(outer_html, filepath)


def save_full_page_dom(page: Page, filename: str = "full_page_after_click.html") -> Path:
    filepath = get_run_dir() / filename
    return save_text_file(page.content(), filepath)


def click_left_edge_to_close(page: Page) -> None:
    logging.info("attempting to close overlay by clicking near left edge")

    viewport = page.viewport_size or {"width": 1280, "height": 900}
    height = viewport["height"]

    left_edge_x = random.randint(8, 25)
    left_edge_y = random.randint(
        max(80, int(height * 0.25)),
        max(120, int(height * 0.75)),
    )

    page.mouse.move(
        random.randint(40, 120),
        random.randint(100, height - 100),
        steps=random.randint(10, 25),
    )
    human_pause(0.15, 0.35)

    page.mouse.move(left_edge_x, left_edge_y, steps=random.randint(12, 30))
    human_pause(0.1, 0.25)

    page.mouse.click(left_edge_x, left_edge_y)
    human_pause(0.6, 1.1)

    logging.debug("Clicked at x=%d y=%d to close overlay", left_edge_x, left_edge_y)


def click_trigger_and_capture(page: Page, trigger: Locator, idx: int) -> None:
    logging.info("Processing trigger %d", idx)

    before_candidates = get_visible_candidates(page, COMMON_OPENED_SELECTORS)

    try:
        trigger.scroll_into_view_if_needed()
        human_pause()

        trigger.hover()
        
        human_pause(0.1, 0.3)
        trigger.click()
        logging.info("Clicked trigger %d", idx)
    except Exception:
        logging.exception("Failed clicking trigger %d", idx)
        return

    human_pause(0.8, 1.5)

    opened = find_new_opened_element(
        page,
        before_candidates,
        COMMON_OPENED_SELECTORS,
        wait_ms=1500,
    )

    padded_idx = f"{idx:03d}"

    if opened is None:
        logging.warning(
            "No obvious modal/popup detected after trigger %d; saving full page DOM",
            idx,
        )
        save_full_page_dom(page, filename=f"full_page_after_click_{padded_idx}.html")
        click_left_edge_to_close(page)
        return

    logging.info("Opened element detected for trigger %d", idx)
    save_element_dom(opened, filename_prefix=f"opened_element_{padded_idx}")
    save_full_page_dom(page, filename=f"full_page_after_click_{padded_idx}.html")

    click_left_edge_to_close(page)

# main function to run the scraper
def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(
        headless=False,
        slow_mo=75,
    )
    # using a single context and page for the whole run to keep state and cookies, 
    # which can help with some actions and also makes it easier to debug.
    try:
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )

        page = context.new_page()
        logging.info("Navigating to %s", URL)
        
        page.goto(URL, wait_until="domcontentloaded")

        human_pause(1.0, 2.0)
        noisy_scroll(page)

        #
        rd_buttons = page.locator('[href^="#RD"]')
        count = rd_buttons.count()
        logging.info("Found %d RD buttons", count)

        for i in range(count):
            try:

                trigger = rd_buttons.nth(i)
                if trigger.is_visible():
                    click_trigger_and_capture(page, trigger, i)


                else:
                    logging.debug("Skipping trigger %d because it is not visible", i)
            except Exception:
                logging.exception("Unexpected error on trigger %d", i)

        page.wait_for_timeout(3000)


    finally:
        logging.info("closing  browser")
        browser.close()


def main() -> None:
    global RUN_DIR
    RUN_DIR = create_run_dir()
    setup_logging(RUN_DIR / "scrape_debug.log")
    logging.info("Run output directory: %s", RUN_DIR)
    logging.info("Starting scraper")

    with sync_playwright() as playwright:
        run(playwright)

    logging.info("Finished")

main()