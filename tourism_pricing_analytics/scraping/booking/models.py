from dataclasses import dataclass
from pathlib import Path
from typing import Literal


FailureCategory = Literal[
    "empty_availability",
    "selector_drift",
    "redirect",
    "blocked_challenge",
    "partial_load",
    "temporary_booking_error",
    "navigation_error",
    "extraction_error",
]

ScrapeStage = Literal["room_inventory", "price_rows"]


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


@dataclass(frozen=True)
class RoomInventoryRecord:
    property_name: str
    property_url: str
    room_id: str
    room_name: str
    captured_at: str


@dataclass(frozen=True)
class PriceRowRecord:
    property_name: str
    property_url: str
    checkin: str
    checkout: str
    lead_time_days: int
    stay_length_days: int
    room_id: str | None
    room_name: str | None
    block_id: str | None
    occupancy_text: str | None
    conditions_text: str | None
    scarcity_text: str | None
    current_price_text: str | None
    original_price_text: str | None
    current_price_value: float | None
    original_price_value: float | None
    price_per_night: float | None
    quantity_options: list[str]
    captured_at: str


@dataclass(frozen=True)
class ScrapeFailureRecord:
    property_name: str
    property_url: str
    scrape_stage: ScrapeStage
    category: FailureCategory
    reason: str
    requested_url: str
    final_url: str | None
    checkin: str | None
    checkout: str | None
    lead_time_days: int | None
    stay_length_days: int | None
    status_code: int | None
    snapshot_filename: str | None
    exception_type: str | None
    exception_message: str | None
    captured_at: str
