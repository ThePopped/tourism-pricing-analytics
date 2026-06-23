from dataclasses import dataclass, field
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
class PauseConfig:
    """Jittered politeness pauses, in milliseconds.

    ``post_nav`` is the dwell applied right after a ``goto`` before interacting
    with the page. It keeps a randomized range (not a fixed value) so traffic
    stays human-like even when tuned small for the scale-up run.
    """

    post_nav_min_ms: int = 300
    post_nav_max_ms: int = 800


@dataclass(frozen=True)
class RetryConfig:
    """Retry policy for transient page failures.

    ``max_attempts`` counts the initial try plus retries. A value of 1 disables
    retries while keeping the retry wrapper behavior deterministic for tests.
    """

    max_attempts: int = 3
    base_backoff_ms: int = 1000
    max_backoff_ms: int = 10000
    jitter_ms: int = 500


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
    pauses: PauseConfig = field(default_factory=PauseConfig)
    retry: RetryConfig = field(default_factory=RetryConfig)


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
class RoomFeatureRecord:
    """Per-room characteristics that are stable across dates.

    One record per ``(property_url, room_id)``, written to ``room_features.jsonl``
    and joined to price rows on ``room_id``. Every feature field is best-effort and
    nullable/empty: an extractor that cannot find its signal contributes nothing,
    leaving the default rather than failing the record. Encoding (e.g. amenity
    multi-hot) is deferred to the downstream feature layer.
    """

    property_name: str
    property_url: str
    room_id: str
    captured_at: str
    room_size_sqm: float | None = None
    bed_types: list[str] = field(default_factory=list)
    bed_count: int | None = None
    max_persons: int | None = None
    amenities: list[str] = field(default_factory=list)
    room_class: str | None = None


@dataclass(frozen=True)
class PropertyFeatureRecord:
    """Per-property characteristics that are stable across dates and rooms.

    One record per ``property_url``, written to ``property_features.jsonl`` and
    joined to price rows on ``property_url``. Every feature field is best-effort
    and nullable/empty so a missing or lazy-loaded property section yields a
    default, never a row/run failure. Raw lists/maps are captured here and encoded
    downstream.
    """

    property_name: str
    property_url: str
    captured_at: str
    star_rating: float | None = None
    review_score: float | None = None
    review_count: int | None = None
    property_type: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    review_subscores: dict[str, float] = field(default_factory=dict)
    property_facilities: list[str] = field(default_factory=list)
    nearby_poi: list[dict] = field(default_factory=list)
    checkin_from: str | None = None
    checkin_until: str | None = None
    checkout_from: str | None = None
    checkout_until: str | None = None
    house_rules: dict | None = None
    photo_count: int | None = None
    sustainability_level: str | None = None
    languages_spoken: list[str] = field(default_factory=list)


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
