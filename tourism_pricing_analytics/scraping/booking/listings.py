"""Pure parsing of saved Booking.com search-results (listings) pages.

A listings page is a region search such as ``listings_chania.html`` that lists
many properties as cards. This module extracts candidate properties from that
saved HTML so the configured scrape target set can be derived reproducibly
instead of being hand-maintained.

Parsing is deliberately separate from the live scraper: it operates on a static
HTML string with BeautifulSoup, returns plain dataclasses, and has no browser or
network dependency, so it is cheap to unit test against trimmed fixtures.
"""

import re
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup


# Each result is wrapped in a property card; the property link carries this class
# and the title/price/score live on stable data-testid attributes.
PROPERTY_CARD_SELECTOR = '[data-testid="property-card"]'
TITLE_SELECTOR = '[data-testid="title"]'
TITLE_LINK_SELECTOR = 'a[data-testid="title-link"]'
PROPERTY_LINK_CLASS = "bd77474a8e"
PRICE_SELECTOR = '[data-testid="price-and-discounted-price"]'
REVIEW_SCORE_SELECTOR = '[data-testid="review-score"]'
RECOMMENDED_UNITS_SELECTOR = '[data-testid="recommended-units"]'

_HOTEL_PATH_PATTERN = re.compile(r"/hotel/[a-z]{2}/[^/]+\.html$", re.IGNORECASE)


@dataclass(frozen=True)
class ListingCandidate:
    name: str
    url: str
    price_text: str | None
    review_score_text: str | None
    recommended_unit_text: str | None


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"\s+", " ", value).strip()
    return normalized or None


def normalize_listing_url(href: str | None) -> str | None:
    """Return the canonical property URL with tracking query/fragment removed.

    Listing hrefs carry large ``?label=...&checkin=...`` query strings that vary
    per session. Stripping the query and fragment yields the stable
    ``https://www.booking.com/hotel/gr/<slug>.html`` form used in the scraper
    config. Returns ``None`` when the href is not a Booking.com hotel page.
    """

    if not href:
        return None

    parts = urlsplit(href.strip())
    if not parts.path or not _HOTEL_PATH_PATTERN.search(parts.path):
        return None

    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _card_text(card, selector: str) -> str | None:
    element = card.select_one(selector)
    if element is None:
        return None
    return _clean_text(element.get_text(" ", strip=True))


def _card_url(card) -> str | None:
    link = card.select_one(TITLE_LINK_SELECTOR)
    if link is None:
        link = card.find("a", class_=PROPERTY_LINK_CLASS)
    if link is None:
        link = card.select_one('a[href*="/hotel/"]')
    if link is None:
        return None
    return normalize_listing_url(link.get("href"))


def parse_listings(html: str) -> list[ListingCandidate]:
    """Parse all property cards from a saved listings page.

    Cards without a resolvable name or URL are skipped, and duplicate URLs are
    collapsed to the first occurrence so the result preserves listing order.
    """

    soup = BeautifulSoup(html, "html.parser")
    candidates: list[ListingCandidate] = []
    seen_urls: set[str] = set()

    for card in soup.select(PROPERTY_CARD_SELECTOR):
        name = _card_text(card, TITLE_SELECTOR)
        url = _card_url(card)
        if name is None or url is None or url in seen_urls:
            continue

        seen_urls.add(url)
        candidates.append(
            ListingCandidate(
                name=name,
                url=url,
                price_text=_card_text(card, PRICE_SELECTOR),
                review_score_text=_card_text(card, REVIEW_SCORE_SELECTOR),
                recommended_unit_text=_card_text(card, RECOMMENDED_UNITS_SELECTOR),
            )
        )

    return candidates
