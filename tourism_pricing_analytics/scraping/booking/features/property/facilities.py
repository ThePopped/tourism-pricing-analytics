"""Whole-property facilities extractor.

Captures the hotel-level amenity set (distinct from per-room amenities) as a raw
flat list of facility names, gathered from every ``facility-group-container``'s
list items in DOM order. The "Languages spoken" group is skipped here because it
is captured separately by the misc extractor. No encoding happens at scrape time;
multi-hot is fit downstream over the full dataset, exactly like room amenities.
"""

from tourism_pricing_analytics.scraping.booking.features.base import PropertyFeatureContext
from tourism_pricing_analytics.scraping.booking.parsing import get_locator_text


class FacilitiesExtractor:
    name = "facilities"

    def extract(self, ctx: PropertyFeatureContext) -> dict:
        groups = ctx.page.locator('[data-testid="facility-group-container"]')
        facilities: list[str] = []
        for group_index in range(groups.count()):
            group = groups.nth(group_index)
            heading = (get_locator_text(group.locator("h3")) or "").strip().lower()
            if heading.startswith("languages spoken"):
                continue
            items = group.locator("li")
            for item_index in range(items.count()):
                text = get_locator_text(items.nth(item_index))
                if text:
                    facilities.append(text)

        if not facilities:
            return {}
        return {"property_facilities": facilities}
