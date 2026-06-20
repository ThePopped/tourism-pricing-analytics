import json
from pathlib import Path

from config import CONFIG_DIR, ROOT
from tourism_pricing_analytics.scraping.booking.models import (
    BrowserConfig,
    DefaultSearchConfig,
    PropertyTarget,
    ScraperConfig,
    ScrollConfig,
    TimeoutConfig,
    ViewportConfig,
)


DEFAULT_CONFIG_PATH = CONFIG_DIR / "booking_scraper_config.json"


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
