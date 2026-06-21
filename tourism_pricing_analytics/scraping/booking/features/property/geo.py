"""Property geo-coordinate extractor.

Booking carries the property's coordinates in a ``data-atlas-latlng="lat,lng"``
attribute on the header map link. Parse it into separate float fields; anything
malformed yields no field rather than a bad coordinate.
"""

from tourism_pricing_analytics.scraping.booking.features.base import PropertyFeatureContext
from tourism_pricing_analytics.scraping.booking.parsing import get_locator_attribute


class GeoExtractor:
    name = "geo"

    def extract(self, ctx: PropertyFeatureContext) -> dict:
        raw = get_locator_attribute(
            ctx.page.locator("[data-atlas-latlng]"), "data-atlas-latlng"
        )
        if not raw or "," not in raw:
            return {}
        lat_text, lng_text = raw.split(",", 1)
        try:
            return {"latitude": float(lat_text), "longitude": float(lng_text)}
        except ValueError:
            return {}
