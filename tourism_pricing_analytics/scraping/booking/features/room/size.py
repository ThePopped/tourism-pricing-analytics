"""Room size (m²) extractor.

Booking has no dedicated element for room size; it appears as one of the
``.hprt-facilities-facility`` entries, e.g. ``25 m²``. Extract the numeric value
from the first facility matching the m² pattern.
"""

import re

from tourism_pricing_analytics.scraping.booking.features.base import RoomFeatureContext
from tourism_pricing_analytics.scraping.booking.parsing import get_locator_text


# Match "25 m²" (U+00B2 superscript two) and the "25 m2" fallback form.
_SIZE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*m(?:²|2)", re.IGNORECASE)


class RoomSizeExtractor:
    name = "room_size"

    def extract(self, ctx: RoomFeatureContext) -> dict:
        facilities = ctx.room_cell.locator(".hprt-facilities-facility")
        for index in range(facilities.count()):
            text = get_locator_text(facilities.nth(index))
            if not text:
                continue
            match = _SIZE_RE.search(text)
            if match:
                value = float(match.group(1).replace(",", "."))
                return {"room_size_sqm": value}
        return {}
