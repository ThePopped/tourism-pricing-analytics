"""Maximum occupancy extractor.

Reads the room's occupancy cell, which states capacity as either
``Max persons: N`` or ``Sleeps: A - B guests``. Returns the upper bound as
``max_persons``; omits the field when neither form is present.
"""

import re

from tourism_pricing_analytics.scraping.booking.features.base import RoomFeatureContext
from tourism_pricing_analytics.scraping.booking.parsing import get_locator_text


_MAX_PERSONS_RE = re.compile(r"Max persons:\s*(\d+)", re.IGNORECASE)
_SLEEPS_RANGE_RE = re.compile(r"Sleeps:\s*\d+\s*[-–]\s*(\d+)", re.IGNORECASE)
_SLEEPS_SINGLE_RE = re.compile(r"Sleeps:\s*(\d+)", re.IGNORECASE)


class OccupancyExtractor:
    name = "occupancy"

    def extract(self, ctx: RoomFeatureContext) -> dict:
        occupancy = ctx.row.locator("td.hprt-table-cell-occupancy").first
        text = get_locator_text(occupancy)
        if not text:
            return {}

        for pattern in (_MAX_PERSONS_RE, _SLEEPS_RANGE_RE, _SLEEPS_SINGLE_RE):
            match = pattern.search(text)
            if match:
                return {"max_persons": int(match.group(1))}
        return {}
