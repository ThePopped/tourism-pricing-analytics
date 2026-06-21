"""Per-room amenities extractor.

Captures every ``.hprt-facilities-facility`` entry as a raw string list, in DOM
order. No filtering or encoding happens here (the size token ``25 m²`` is part of
this list as-is); multi-hot encoding and vocabulary handling are deferred to the
downstream feature-derivation layer where the full dataset is visible.
"""

from tourism_pricing_analytics.scraping.booking.features.base import RoomFeatureContext
from tourism_pricing_analytics.scraping.booking.parsing import get_locator_text


class AmenitiesExtractor:
    name = "amenities"

    def extract(self, ctx: RoomFeatureContext) -> dict:
        facilities = ctx.room_cell.locator(".hprt-facilities-facility")
        amenities: list[str] = []
        for index in range(facilities.count()):
            text = get_locator_text(facilities.nth(index))
            if text:
                amenities.append(text)

        if not amenities:
            return {}
        return {"amenities": amenities}
