import json
import logging
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TypedDict
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from playwright.sync_api import Locator, Page, Playwright, sync_playwright

from config import CONFIG_DIR, ROOT


DEFAULT_CONFIG_PATH = CONFIG_DIR / "booking_scraper_config.json"


class VisibleCandidate(TypedDict):
    selector: str
    index: int
    outer_html: str


@dataclass(frozen=True)
class ViewportConfig:
    width: int
    height: int


@dataclass(frozen=True)
class BrowserConfig:
    headless: bool
    slow_mo_ms: int
    user_agent: str
    viewport: ViewportConfig


@dataclass(frozen=True)
class DefaultSearchConfig:
    group_adults: int
    group_children: int
    no_rooms: int


@dataclass(frozen=True)
class TimeoutConfig:
    opened_scan_wait_ms: int
    final_wait_ms: int


@dataclass(frozen=True)
class ScrollConfig:
    rounds: int
    min_delta: int
    max_delta: int


@dataclass(frozen=True)
class PropertyTarget:
    name: str
    url: str


@dataclass(frozen=True)
class ScraperConfig:
    seed: int
    output_root: Path
    lead_times: list[int]
    stay_lengths: list[int]
    browser: BrowserConfig
    default_search: DefaultSearchConfig
    timeouts: TimeoutConfig
    scroll: ScrollConfig
    common_opened_selectors: list[str]
    properties: list[PropertyTarget]


def load_scraper_config(config_path: Path = DEFAULT_CONFIG_PATH) -> ScraperConfig:
    raw_config = json.loads(config_path.read_text(encoding="utf-8"))

    viewport = ViewportConfig(**raw_config["browser"]["viewport"])
    browser = BrowserConfig(
        headless=raw_config["browser"]["headless"],
        slow_mo_ms=raw_config["browser"]["slow_mo_ms"],
        user_agent=raw_config["browser"]["user_agent"],
        viewport=viewport,
    )
    default_search = DefaultSearchConfig(**raw_config["default_search"])
    timeouts = TimeoutConfig(**raw_config["timeouts_ms"])
    scroll = ScrollConfig(**raw_config["scroll"])
    properties = [PropertyTarget(**item) for item in raw_config["properties"]]

    if not properties:
        raise ValueError("At least one property target must be configured.")

    output_root = Path(raw_config["output_root"])
    if not output_root.is_absolute():
        output_root = ROOT / output_root

    return ScraperConfig(
        seed=raw_config["seed"],
        output_root=output_root,
        lead_times=list(raw_config["lead_times"]),
        stay_lengths=list(raw_config["stay_lengths"]),
        browser=browser,
        default_search=default_search,
        timeouts=timeouts,
        scroll=scroll,
        common_opened_selectors=list(raw_config["common_opened_selectors"]),
        properties=properties,
    )


def build_property_url(base_url: str, params: dict[str, int | str | None] | None = None) -> str:
    split_url = urlsplit(base_url)
    query_params = dict(parse_qsl(split_url.query, keep_blank_values=True))

    if params:
        for key, value in params.items():
            if value is None:
                query_params.pop(key, None)
            else:
                query_params[key] = str(value)

    return urlunsplit(
        (
            split_url.scheme,
            split_url.netloc,
            split_url.path,
            urlencode(query_params),
            split_url.fragment,
        )
    )


def create_run_dir(output_root: Path) -> Path:
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    run_dir = output_root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def create_property_output_dir(run_dir: Path, property_index: int, target: PropertyTarget) -> Path:
    property_dir = run_dir / f"{property_index:03d}_{slugify(target.name)}"
    property_dir.mkdir(parents=True, exist_ok=False)
    return property_dir


def setup_logging(log_path: Path) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_path, encoding="utf-8"),
        ],
        force=True,
    )


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


def get_outer_html(locator: Locator) -> str | None:
    try:
        return locator.evaluate("el => el.outerHTML")
    except Exception:
        logging.exception("failed to get outerHTML")
        return None


def get_visible_candidates(page: Page, selectors: list[str]) -> list[VisibleCandidate]:
    visible: list[VisibleCandidate] = []

    for selector in selectors:
        locator = page.locator(selector)
        count = locator.count()
        logging.debug("selector %r matched %d elements", selector, count)

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
    page: Page,
    before_candidates: list[VisibleCandidate],
    selectors: list[str],
    wait_ms: int,
) -> Locator | None:
    logging.info("Waiting %d ms before scanning for opened element", wait_ms)
    page.wait_for_timeout(wait_ms)

    before_html_set = {item["outer_html"] for item in before_candidates}
    logging.debug("Baseline visible candidates: %d", len(before_html_set))

    for selector in selectors:
        locator = page.locator(selector)
        count = locator.count()
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


def save_element_dom(
    element: Locator,
    output_dir: Path,
    filename_prefix: str = "opened",
) -> Path | None:
    outer_html = get_outer_html(element)
    if outer_html is None:
        logging.error("Could not save element DOM because outerHTML extraction failed")
        return None

    filepath = output_dir / f"{filename_prefix}.html"
    return save_text_file(outer_html, filepath)


def save_full_page_dom(
    page: Page,
    output_dir: Path,
    filename: str = "full_page_after_click.html",
) -> Path:
    filepath = output_dir / filename
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


def click_trigger_and_capture(
    page: Page,
    trigger: Locator,
    idx: int,
    output_dir: Path,
    scraper_config: ScraperConfig,
) -> None:
    logging.info("Processing trigger %d", idx)

    before_candidates = get_visible_candidates(page, scraper_config.common_opened_selectors)

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
        scraper_config.common_opened_selectors,
        wait_ms=scraper_config.timeouts.opened_scan_wait_ms,
    )

    padded_idx = f"{idx:03d}"

    if opened is None:
        logging.warning(
            "No obvious modal/popup detected after trigger %d; saving full page DOM",
            idx,
        )
        save_full_page_dom(page, output_dir, filename=f"full_page_after_click_{padded_idx}.html")
        click_left_edge_to_close(page)
        return

    logging.info("Opened element detected for trigger %d", idx)
    save_element_dom(opened, output_dir, filename_prefix=f"opened_element_{padded_idx}")
    save_full_page_dom(page, output_dir, filename=f"full_page_after_click_{padded_idx}.html")

    click_left_edge_to_close(page)


def scrape_property(
    page: Page,
    target: PropertyTarget,
    output_dir: Path,
    scraper_config: ScraperConfig,
) -> None:
    property_url = build_property_url(target.url)
    logging.info("Navigating to %s", property_url)

    page.goto(property_url, wait_until="domcontentloaded")
    human_pause(1.0, 2.0)
    noisy_scroll(page, scraper_config.scroll)

    rd_buttons = page.locator('[href^="#RD"]')
    count = rd_buttons.count()
    logging.info("Found %d RD buttons for %s", count, target.name)

    for i in range(count):
        try:
            trigger = rd_buttons.nth(i)
            if trigger.is_visible():
                click_trigger_and_capture(page, trigger, i, output_dir, scraper_config)
            else:
                logging.debug("Skipping trigger %d because it is not visible", i)
        except Exception:
            logging.exception("Unexpected error on trigger %d", i)

    page.wait_for_timeout(scraper_config.timeouts.final_wait_ms)


def run(playwright: Playwright, scraper_config: ScraperConfig, run_dir: Path) -> None:
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

        for property_index, target in enumerate(scraper_config.properties, start=1):
            output_dir = create_property_output_dir(run_dir, property_index, target)
            logging.info("Property output directory: %s", output_dir)
            logging.info("Starting property %d/%d: %s", property_index, len(scraper_config.properties), target.name)
            scrape_property(page, target, output_dir, scraper_config)

    finally:
        logging.info("closing browser")
        browser.close()


def main() -> None:
    scraper_config = load_scraper_config()
    random.seed(scraper_config.seed)

    run_dir = create_run_dir(scraper_config.output_root)
    setup_logging(run_dir / "scrape_debug.log")

    logging.info("Run output directory: %s", run_dir)
    logging.info("Starting scraper")
    logging.info("Configured property count: %d", len(scraper_config.properties))
    logging.info("Configured lead times: %s", scraper_config.lead_times)
    logging.info("Configured stay lengths: %s", scraper_config.stay_lengths)
    logging.info(
        "Default search config: adults=%d children=%d rooms=%d",
        scraper_config.default_search.group_adults,
        scraper_config.default_search.group_children,
        scraper_config.default_search.no_rooms,
    )

    with sync_playwright() as playwright:
        run(playwright, scraper_config, run_dir)

    logging.info("Finished")


if __name__ == "__main__":
    main()
