"""Surroundings / nearby-POI extractor.

Each ``poi-block`` groups nearby points of interest under a category heading
(Top attractions, Beaches, Closest airports, ...), with list items rendered as
``Name distance unit`` (e.g. ``Firkas Fortress 300 m``, ``Nea Chora Beach 1 km``).
Captured as ``{poi_name, distance, unit, category}`` pairs; distance is a float
in the listed unit. Location is a top price/clustering driver, so this is high
value, but still best-effort: an item that does not parse is skipped.
"""

import re

from tourism_pricing_analytics.scraping.booking.features.base import PropertyFeatureContext
from tourism_pricing_analytics.scraping.booking.parsing import get_locator_text


# Trailing distance + unit (m / km), name is everything before it.
_POI_RE = re.compile(r"^(?P<name>.+?)\s+(?P<distance>[\d.,]+)\s*(?P<unit>km|m)$", re.IGNORECASE)


class SurroundingsExtractor:
    name = "surroundings"

    def extract(self, ctx: PropertyFeatureContext) -> dict:
        blocks = ctx.page.locator('[data-testid="poi-block"]')
        pois: list[dict] = []
        for block_index in range(blocks.count()):
            block = blocks.nth(block_index)
            category = get_locator_text(block.locator("h3"))
            items = block.locator("li")
            for item_index in range(items.count()):
                text = get_locator_text(items.nth(item_index))
                if not text:
                    continue
                match = _POI_RE.match(text)
                if not match:
                    continue
                try:
                    distance = float(match.group("distance").replace(",", ""))
                except ValueError:
                    continue
                pois.append(
                    {
                        "poi_name": match.group("name").strip(),
                        "distance": distance,
                        "unit": match.group("unit").lower(),
                        "category": category,
                    }
                )

        if not pois:
            return {}
        return {"nearby_poi": pois}
