import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlsplit

from playwright.sync_api import Page

from tourism_pricing_analytics.scraping.booking.models import FailureCategory


# HTTP statuses Booking.com serves for bot mitigation rather than real content:
# 202 ("Accepted") is the soft-block/challenge interstitial, 403/429 are hard
# blocks/rate limits. These pages often render enough boilerplate to match the
# property-page markers below, so without an explicit status check they fall
# through to selector_drift and masquerade as DOM changes. The HTTP status is a
# more reliable block signal than the scraped page text on a challenge page.
BLOCKED_STATUS_CODES = frozenset({202, 403, 429})

BLOCKED_CHALLENGE_PATTERNS = [
    "captcha",
    "security check",
    "verify you are human",
    "verify you're human",
    "access denied",
    "unusual traffic",
    "are you a human",
    "bot detection",
    "px-captcha",
    "cf-chl",
]

TEMPORARY_ERROR_PATTERNS = [
    "temporarily unavailable",
    "temporary error",
    "technical issue",
    "server error",
    "service unavailable",
    "bad gateway",
    "gateway timeout",
]

EMPTY_AVAILABILITY_PATTERNS = [
    "no availability",
    "not available for your dates",
    "not available on our site",
    "sold out",
    "fully booked",
    "change your dates",
    "try different dates",
    "no rooms available",
    "we're sorry, but it is not possible",
    # No-room-table "not bookable" pages: HTTP 200 with no room table at all and
    # a sorry/no-reservations marker. Previously misclassified as selector_drift.
    "isn't taking reservations",
    "not taking reservations",
    "not possible to make reservations",
]

PROPERTY_PAGE_PATTERNS = [
    "booking.com",
    "property highlights",
    "availability",
    "room type",
    "select rooms",
    "guest reviews",
    "facilities",
    "hprt-table",
    "hp_availability",
    "availability_target",
]


@dataclass(frozen=True)
class PageFailureClassification:
    category: FailureCategory
    reason: str


class VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data.strip():
            self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts)


def normalize_page_text(html: str | None) -> str:
    if html is None:
        return ""
    parser = VisibleTextParser()
    parser.feed(html)
    visible_text = parser.get_text() or html
    # Booking renders curly typographic apostrophes (U+2018/U+2019) in messages
    # such as "this property isn't taking reservations", so fold them to a plain
    # ASCII apostrophe before pattern matching.
    visible_text = visible_text.replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", visible_text).strip().lower()


def classify_page_failure(
    html: str | None,
    *,
    final_url: str | None,
    requested_url: str,
    expected_selector_count: int,
    fallback_selector_count: int = 0,
    status_code: int | None = None,
) -> PageFailureClassification | None:
    if expected_selector_count > 0:
        return None

    page_text = normalize_page_text(html)

    if _contains_any(page_text, BLOCKED_CHALLENGE_PATTERNS):
        return PageFailureClassification(
            category="blocked_challenge",
            reason="Page content matched a blocked, captcha, or human-verification pattern.",
        )

    if status_code in BLOCKED_STATUS_CODES:
        return PageFailureClassification(
            category="blocked_challenge",
            reason=(
                f"HTTP {status_code} indicates a bot-mitigation block or "
                "challenge interstitial, not scraper selector drift."
            ),
        )

    if status_code is not None and status_code >= 500:
        return PageFailureClassification(
            category="temporary_booking_error",
            reason="HTTP status indicates a temporary Booking.com error.",
        )

    if final_url is not None and _is_redirect(final_url, requested_url):
        return PageFailureClassification(
            category="redirect",
            reason="Final page URL differs from the requested property path or host.",
        )

    if _contains_any(page_text, EMPTY_AVAILABILITY_PATTERNS):
        return PageFailureClassification(
            category="empty_availability",
            reason="Page content indicates no available rooms for the requested search.",
        )

    if _contains_any(page_text, TEMPORARY_ERROR_PATTERNS):
        return PageFailureClassification(
            category="temporary_booking_error",
            reason="Page content indicates a temporary Booking.com error.",
        )

    if _looks_partial(page_text):
        return PageFailureClassification(
            category="partial_load",
            reason="Page content is too small or incomplete to classify reliably.",
        )

    if fallback_selector_count > 0 or _contains_any(page_text, PROPERTY_PAGE_PATTERNS):
        return PageFailureClassification(
            category="selector_drift",
            reason="Page appears loaded, but expected scraper selectors were not found.",
        )

    return PageFailureClassification(
        category="partial_load",
        reason="Page loaded without recognizable Booking.com content or target selectors.",
    )


def classify_playwright_page_failure(
    page: Page,
    *,
    requested_url: str,
    expected_selector: str,
    fallback_selectors: list[str] | None = None,
    status_code: int | None = None,
) -> PageFailureClassification | None:
    fallback_selectors = fallback_selectors or []
    expected_selector_count = page.locator(expected_selector).count()
    fallback_selector_count = sum(
        page.locator(selector).count() for selector in fallback_selectors
    )
    return classify_page_failure(
        page.content(),
        final_url=page.url,
        requested_url=requested_url,
        expected_selector_count=expected_selector_count,
        fallback_selector_count=fallback_selector_count,
        status_code=status_code,
    )


def _contains_any(page_text: str, patterns: list[str]) -> bool:
    return any(pattern in page_text for pattern in patterns)


def _is_redirect(final_url: str, requested_url: str) -> bool:
    final_parts = urlsplit(final_url)
    requested_parts = urlsplit(requested_url)
    if final_parts.netloc.lower() != requested_parts.netloc.lower():
        return True
    return final_parts.path.rstrip("/") != requested_parts.path.rstrip("/")


def _looks_partial(page_text: str) -> bool:
    if len(page_text) < 500:
        return True
    return "<html" in page_text and "</html>" not in page_text
