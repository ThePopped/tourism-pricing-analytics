"""Automated discovery of Booking.com self-catering listing candidates.

The pure parser :func:`listings.parse_listings` turns a single saved
search-results page into :class:`ListingCandidate` rows. This module adds the
automation that was previously manual (hand-saving ``listings_chania.html``): it
builds geographically scoped, type-filtered search URLs, paginates them with
Booking's ``offset`` parameter, and unions the per-page candidates into a
deduplicated target list that feeds ``scripts/generate_full_config.py``.

Browser-coupled functions are kept thin. Every decision -- URL building, the
pagination stop condition, blocked-page detection, and dedup/merge -- is a pure
function so it can be unit-tested against fixtures without a live browser.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urlencode, urlsplit, urlunsplit

from playwright.sync_api import BrowserContext, Page

from tourism_pricing_analytics.scraping.booking.browser import navigate_to_page
from tourism_pricing_analytics.scraping.booking.listings import (
    ListingCandidate,
    parse_listings,
)
from tourism_pricing_analytics.scraping.booking.models import (
    DefaultSearchConfig,
    ScraperConfig,
)
from tourism_pricing_analytics.scraping.booking.urls import canonicalize_property_url


SEARCH_RESULTS_URL = "https://www.booking.com/searchresults.en-gb.html"

# Self-catering property-type filter codes (Booking ``ht_id``), aligned with the
# downstream self-catering segment: Apartments (201), Villas (213), Holiday
# homes (220). Aparthotels self-classify under Apartments, so they are captured
# too; non self-catering noise is filtered downstream by the property page's own
# ``property_type``.
SELF_CATERING_HT_IDS = (201, 213, 220)

# Booking renders 25 property cards per search-results page.
PAGE_SIZE = 25

# The Gerani west-coast strip: the subject village plus its immediate coastal
# neighbours, west of Chania town. The subject "Stavros Villas & Apartments" is
# named for a person, not Stavros/Akrotiri; it actually sits in Gerani.
DEFAULT_SEARCH_AREAS = (
    "Gerani, Chania, Crete, Greece",
    "Platanias, Chania, Crete, Greece",
    "Maleme, Chania, Crete, Greece",
    "Agia Marina, Chania, Crete, Greece",
    "Kontomari, Chania, Crete, Greece",
    "Tavronitis, Chania, Crete, Greece",
    "Kolymbari, Chania, Crete, Greece",
)

# Substrings that mark a bot wall / challenge / redirect rather than results.
_BLOCKED_MARKERS = (
    "are you human",
    "captcha",
    "access denied",
    "unusual traffic",
    "/sorry/",
    "px-captcha",
)


@dataclass(frozen=True)
class DiscoveryConfig:
    """Controls the geographic scope, type filter, and crawl caps.

    ``max_per_area`` bounds the paginated crawl of a single destination;
    ``max_total`` caps the merged, deduplicated candidate set across all areas.
    ``max_pages_per_area`` is a hard safety stop independent of the data so a
    runaway search can never loop forever.
    """

    areas: tuple[str, ...] = DEFAULT_SEARCH_AREAS
    ht_ids: tuple[int, ...] = SELF_CATERING_HT_IDS
    max_per_area: int = 75
    max_total: int = 100
    max_pages_per_area: int = 8
    page_size: int = PAGE_SIZE

    def __post_init__(self) -> None:
        if not self.areas:
            raise ValueError("At least one search area is required.")
        if self.max_per_area <= 0:
            raise ValueError("max_per_area must be positive")
        if self.max_total <= 0:
            raise ValueError("max_total must be positive")
        if self.max_pages_per_area <= 0:
            raise ValueError("max_pages_per_area must be positive")
        if self.page_size <= 0:
            raise ValueError("page_size must be positive")


def build_search_url(
    destination: str,
    *,
    default_search: DefaultSearchConfig,
    offset: int = 0,
    ht_ids: Iterable[int] = SELF_CATERING_HT_IDS,
    base_url: str = SEARCH_RESULTS_URL,
) -> str:
    """Return a paginated, type-filtered Booking.com search URL for a destination.

    Discovery searches are intentionally dateless: we only need stable property
    URLs, and adding check-in/check-out would gate results on availability and
    drop relevant-but-unavailable listings. Occupancy mirrors the scrape's
    controlled 2-guest design via ``default_search``.
    """

    params: dict[str, str | int] = {
        "ss": destination,
        "group_adults": default_search.group_adults,
        "group_children": default_search.group_children,
        "no_rooms": default_search.no_rooms,
    }
    ht_id_list = list(ht_ids)
    if ht_id_list:
        params["nflt"] = ";".join(f"ht_id={code}" for code in ht_id_list)
    if offset:
        params["offset"] = offset

    split = urlsplit(base_url)
    return urlunsplit((split.scheme, split.netloc, split.path, urlencode(params), ""))


def detect_blocked_page(*, title: str | None, html: str | None) -> bool:
    """Return True when the page looks like a bot wall / challenge, not results."""

    haystack = f"{title or ''} {html or ''}".lower()
    return any(marker in haystack for marker in _BLOCKED_MARKERS)


def should_stop_pagination(
    *,
    new_candidate_count: int,
    page_card_count: int,
    pages_fetched: int,
    max_pages: int,
    page_size: int,
) -> bool:
    """Return True when the paginated crawl of one area should stop.

    Stops on any of: the hard page cap reached, a short final page (fewer cards
    than a full page), or Booking starting to repeat already-collected
    properties (no new candidates on the latest page).
    """

    if pages_fetched >= max_pages:
        return True
    if page_card_count < page_size:
        return True
    if new_candidate_count == 0:
        return True
    return False


def merge_candidates(
    area_candidates: Iterable[ListingCandidate],
    *,
    exclude_urls: Iterable[str] = (),
    max_total: int | None = None,
) -> list[ListingCandidate]:
    """Union per-area candidates into a deterministic, deduplicated target list.

    Canonicalizes URLs, drops any in ``exclude_urls`` (already-configured targets
    and the subject), collapses duplicates to the first occurrence (preserving
    discovery order), and truncates to ``max_total``.
    """

    excluded = {canonicalize_property_url(url) for url in exclude_urls}
    seen: set[str] = set()
    merged: list[ListingCandidate] = []
    for candidate in area_candidates:
        canonical = canonicalize_property_url(candidate.url)
        if canonical in excluded or canonical in seen:
            continue
        seen.add(canonical)
        merged.append(candidate)
        if max_total is not None and len(merged) >= max_total:
            break
    return merged


def collect_area_candidates(
    page: Page,
    destination: str,
    scraper_config: ScraperConfig,
    config: DiscoveryConfig,
) -> list[ListingCandidate]:
    """Paginate one destination's search results into candidate rows.

    Thin orchestration over :func:`navigate_to_page` and the pure
    :func:`parse_listings`; stops via :func:`should_stop_pagination` or when a
    bot wall is detected, and never exceeds ``config.max_per_area``.
    """

    collected: list[ListingCandidate] = []
    seen: set[str] = set()

    for page_index in range(config.max_pages_per_area):
        offset = page_index * config.page_size
        url = build_search_url(
            destination,
            default_search=scraper_config.default_search,
            offset=offset,
            ht_ids=config.ht_ids,
        )
        navigate_to_page(page, url, scraper_config, scroll_page=True)

        if detect_blocked_page(title=page.title(), html=page.content()):
            logging.warning(
                "Blocked/challenge page detected for %s at offset %d; stopping area",
                destination,
                offset,
            )
            break

        page_candidates = parse_listings(page.content())
        new_candidates = [
            candidate
            for candidate in page_candidates
            if canonicalize_property_url(candidate.url) not in seen
        ]
        for candidate in new_candidates:
            seen.add(canonicalize_property_url(candidate.url))
            collected.append(candidate)

        logging.info(
            "Area %s offset %d: %d cards, %d new (%d collected)",
            destination,
            offset,
            len(page_candidates),
            len(new_candidates),
            len(collected),
        )

        if len(collected) >= config.max_per_area:
            break
        if should_stop_pagination(
            new_candidate_count=len(new_candidates),
            page_card_count=len(page_candidates),
            pages_fetched=page_index + 1,
            max_pages=config.max_pages_per_area,
            page_size=config.page_size,
        ):
            break

    return collected[: config.max_per_area]


def discover_candidates(
    context: BrowserContext,
    scraper_config: ScraperConfig,
    config: DiscoveryConfig,
    *,
    exclude_urls: Iterable[str] = (),
) -> list[ListingCandidate]:
    """Crawl every configured area and return the merged candidate target list."""

    page = context.new_page()
    area_candidates: list[ListingCandidate] = []
    try:
        for destination in config.areas:
            discovered = collect_area_candidates(page, destination, scraper_config, config)
            logging.info("Discovered %d candidates for area %s", len(discovered), destination)
            area_candidates.extend(discovered)
    finally:
        if not page.is_closed():
            page.close()

    return merge_candidates(
        area_candidates,
        exclude_urls=exclude_urls,
        max_total=config.max_total,
    )
