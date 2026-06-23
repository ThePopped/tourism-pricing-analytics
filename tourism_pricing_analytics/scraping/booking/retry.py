"""Retry policy helpers for transient Booking.com scrape failures."""

import random

from tourism_pricing_analytics.scraping.booking.models import FailureCategory


RETRYABLE_FAILURE_CATEGORIES: frozenset[FailureCategory] = frozenset(
    {
        "blocked_challenge",
        "partial_load",
        "temporary_booking_error",
        "navigation_error",
    }
)


def should_retry(
    category: FailureCategory,
    attempt: int,
    max_attempts: int,
) -> bool:
    """Return whether a failure category should get another attempt.

    ``attempt`` is one-based and represents the attempt that just failed.
    ``max_attempts`` includes the initial attempt, so retries are available
    only while ``attempt < max_attempts``.
    """

    if attempt < 1:
        raise ValueError("attempt must be >= 1")
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    return category in RETRYABLE_FAILURE_CATEGORIES and attempt < max_attempts


def backoff_delay_ms(
    attempt: int,
    *,
    base_backoff_ms: int,
    max_backoff_ms: int,
    jitter_ms: int,
    rng: random.Random | None = None,
) -> int:
    """Return bounded exponential backoff with additive jitter.

    The returned delay is for the retry after the failed one-based ``attempt``.
    """

    if attempt < 1:
        raise ValueError("attempt must be >= 1")
    if base_backoff_ms < 0:
        raise ValueError("base_backoff_ms must be >= 0")
    if max_backoff_ms < 0:
        raise ValueError("max_backoff_ms must be >= 0")
    if jitter_ms < 0:
        raise ValueError("jitter_ms must be >= 0")

    random_source = rng if rng is not None else random
    exponential_delay = base_backoff_ms * (2 ** (attempt - 1))
    bounded_delay = min(exponential_delay, max_backoff_ms)
    jitter = random_source.randint(0, jitter_ms) if jitter_ms else 0
    return min(bounded_delay + jitter, max_backoff_ms)
