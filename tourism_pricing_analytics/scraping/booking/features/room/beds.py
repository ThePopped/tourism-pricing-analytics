"""Bed configuration extractor.

Captures the raw bed-type strings (``.rt-bed-type``, e.g. ``2 single beds``) and
a best-effort ``bed_count`` summed from their leading quantities. When no
structured bed elements are present (some room blocks describe beds only in free
text), both fields are omitted rather than guessed.
"""

import re

from tourism_pricing_analytics.scraping.booking.features.base import RoomFeatureContext
from tourism_pricing_analytics.scraping.booking.parsing import get_locator_text


_LEADING_INT = re.compile(r"^\s*(\d+)")


class BedExtractor:
    name = "beds"

    def extract(self, ctx: RoomFeatureContext) -> dict:
        bed_locator = ctx.room_cell.locator(".rt-bed-type")
        bed_types: list[str] = []
        for index in range(bed_locator.count()):
            text = get_locator_text(bed_locator.nth(index))
            if text:
                bed_types.append(text)

        if not bed_types:
            return {}

        result: dict = {"bed_types": bed_types}

        total = 0
        counted = False
        for bed in bed_types:
            match = _LEADING_INT.match(bed)
            if match:
                total += int(match.group(1))
                counted = True
        if counted:
            result["bed_count"] = total

        return result
