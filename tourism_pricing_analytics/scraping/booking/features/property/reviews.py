"""Guest-review extractor: overall score, review count, and category subscores.

The overall badge (``review-score-right-component``) renders as e.g.
``Scored 9.1 9.1 Rated superb Superb 242 reviews``; the leading decimal is the
score and ``N reviews`` is the count. Each ``review-subscore`` element renders as
``Category Score`` (e.g. ``Location 9.7``, ``Free WiFi 10``), captured into a
``{category: score}`` map. All fields are best-effort; a missing badge or
section simply contributes nothing.
"""

import re

from tourism_pricing_analytics.scraping.booking.features.base import PropertyFeatureContext
from tourism_pricing_analytics.scraping.booking.parsing import get_locator_text


_SCORE_RE = re.compile(r"(\d+(?:\.\d+)?)")
_COUNT_RE = re.compile(r"([\d,]+)\s+reviews?", re.IGNORECASE)
# "Location 9.7", "Free WiFi 10" -> leading label, trailing numeric score.
_SUBSCORE_RE = re.compile(r"^(?P<name>.+?)\s+(?P<score>\d+(?:\.\d+)?)$")


class ReviewsExtractor:
    name = "reviews"

    def extract(self, ctx: PropertyFeatureContext) -> dict:
        out: dict = {}

        badge = get_locator_text(
            ctx.page.locator('[data-testid="review-score-right-component"]')
        )
        if badge:
            score_match = _SCORE_RE.search(badge)
            if score_match:
                out["review_score"] = float(score_match.group(1))
            count_match = _COUNT_RE.search(badge)
            if count_match:
                out["review_count"] = int(count_match.group(1).replace(",", ""))

        subscore_locator = ctx.page.locator('[data-testid="review-subscore"]')
        subscores: dict[str, float] = {}
        for index in range(subscore_locator.count()):
            text = get_locator_text(subscore_locator.nth(index))
            if not text:
                continue
            match = _SUBSCORE_RE.match(text)
            if not match:
                continue
            try:
                subscores[match.group("name").strip()] = float(match.group("score"))
            except ValueError:
                continue
        if subscores:
            out["review_subscores"] = subscores

        return out
