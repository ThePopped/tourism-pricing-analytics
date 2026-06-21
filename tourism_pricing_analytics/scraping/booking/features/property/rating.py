"""Property class (star) rating extractor.

Booking renders the official class rating as a set of star/square icons with an
accessible label like ``Rated 4 stars`` / ``4 out of 5``. Many properties have
no official class rating at all (it is simply not rendered), so this is strictly
best-effort: no rating element means no field, never a guess.
"""

import re

from tourism_pricing_analytics.scraping.booking.features.base import PropertyFeatureContext
from tourism_pricing_analytics.scraping.booking.parsing import get_locator_attribute


_RATING_SELECTORS = (
    '[data-testid="rating-stars"]',
    '[data-testid="rating-squares"]',
    '[data-testid="rating-circles"]',
)
_STARS_RE = re.compile(r"(\d(?:\.\d)?)")


class StarRatingExtractor:
    name = "rating"

    def extract(self, ctx: PropertyFeatureContext) -> dict:
        for selector in _RATING_SELECTORS:
            label = get_locator_attribute(ctx.page.locator(selector), "aria-label")
            if not label:
                continue
            match = _STARS_RE.search(label)
            if match:
                value = float(match.group(1))
                if 0 < value <= 5:
                    return {"star_rating": value}
        return {}
