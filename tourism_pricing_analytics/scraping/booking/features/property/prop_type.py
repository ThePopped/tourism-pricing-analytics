"""Property-type extractor.

The current breadcrumb renders the type in parentheses, e.g.
``Elia Palatino Hotel (Hotel) (Greece) deals``; the first parenthetical is the
accommodation type. Best-effort: no breadcrumb yields no field.
"""

import re

from tourism_pricing_analytics.scraping.booking.features.base import PropertyFeatureContext
from tourism_pricing_analytics.scraping.booking.parsing import get_locator_text


_TYPE_RE = re.compile(r"\(([^)]+)\)")


class PropertyTypeExtractor:
    name = "prop_type"

    def extract(self, ctx: PropertyFeatureContext) -> dict:
        text = get_locator_text(ctx.page.locator('[data-testid="breadcrumb-current"]'))
        if not text:
            return {}
        match = _TYPE_RE.search(text)
        if match:
            return {"property_type": match.group(1).strip()}
        return {}
