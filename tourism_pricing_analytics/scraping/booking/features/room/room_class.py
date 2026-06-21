"""Best-effort room class extractor.

Derives a coarse room class from the room name by matching a known vocabulary
(most specific first). This is intentionally best-effort: an unrecognised name
yields no field rather than a guess, and any downstream use should treat it as a
hint, not an authoritative label.
"""

from tourism_pricing_analytics.scraping.booking.features.base import RoomFeatureContext
from tourism_pricing_analytics.scraping.booking.parsing import get_locator_text


# Ordered most specific first so e.g. "Junior Suite" wins over "Suite".
_ROOM_CLASSES = (
    "Junior Suite",
    "Presidential Suite",
    "Executive Suite",
    "Suite",
    "Penthouse",
    "Deluxe",
    "Superior",
    "Executive",
    "Classic",
    "Standard",
    "Economy",
    "Comfort",
    "Family",
    "Studio",
    "Villa",
    "Bungalow",
    "Apartment",
    "Maisonette",
    "Twin",
    "Double",
    "Single",
)


class RoomClassExtractor:
    name = "room_class"

    def extract(self, ctx: RoomFeatureContext) -> dict:
        link = ctx.room_cell.locator(".hprt-roomtype-link").first
        name = get_locator_text(link)
        if not name:
            return {}

        lowered = name.lower()
        for room_class in _ROOM_CLASSES:
            if room_class.lower() in lowered:
                return {"room_class": room_class}
        return {}
