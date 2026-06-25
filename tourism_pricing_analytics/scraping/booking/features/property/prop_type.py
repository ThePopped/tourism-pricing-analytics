"""Property-type extractor.

The current breadcrumb renders the type in parentheses, e.g.
``Elia Palatino Hotel (Hotel) (Greece) deals``. Property names can also contain
parentheses, so the extractor accepts the first parenthetical that matches a
known Booking accommodation type. Best-effort: no breadcrumb yields no field.
"""

import re

from tourism_pricing_analytics.scraping.booking.features.base import PropertyFeatureContext
from tourism_pricing_analytics.scraping.booking.parsing import get_locator_text


_TYPE_RE = re.compile(r"\(([^)]+)\)")

KNOWN_PROPERTY_TYPES = frozenset(
    {
        "Aparthotel",
        "Apartment",
        "Bed and breakfast",
        "Boat",
        "Campsite",
        "Capsule hotel",
        "Chalet",
        "Country house",
        "Farm stay",
        "Guest house",
        "Holiday home",
        "Homestay",
        "Hostel",
        "Hotel",
        "Inn",
        "Lodge",
        "Luxury tent",
        "Motel",
        "Resort",
        "Riad",
        "Ryokan",
        "Villa",
    }
)
_PROPERTY_TYPE_BY_NORMALIZED = {
    " ".join(value.casefold().split()): value for value in KNOWN_PROPERTY_TYPES
}


def _property_type_from_breadcrumb(text: str | None) -> str | None:
    if not text:
        return None
    for raw_value in _TYPE_RE.findall(text):
        normalized = " ".join(raw_value.casefold().split())
        property_type = _PROPERTY_TYPE_BY_NORMALIZED.get(normalized)
        if property_type is not None:
            return property_type
    return None


class PropertyTypeExtractor:
    name = "prop_type"

    def extract(self, ctx: PropertyFeatureContext) -> dict:
        text = get_locator_text(ctx.page.locator('[data-testid="breadcrumb-current"]'))
        property_type = _property_type_from_breadcrumb(text)
        if property_type is not None:
            return {"property_type": property_type}
        return {}
