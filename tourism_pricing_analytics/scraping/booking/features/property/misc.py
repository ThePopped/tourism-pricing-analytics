"""Misc cheap-win extractor: languages spoken, photo count, sustainability level.

Languages come from the "Languages spoken" facility group's list items. Photo
count and sustainability level are captured opportunistically when their badges
are present; on layouts where they are absent or lazy-loaded they simply yield no
field. Everything here is best-effort and nullable.
"""

import re

from tourism_pricing_analytics.scraping.booking.features.base import PropertyFeatureContext
from tourism_pricing_analytics.scraping.booking.parsing import (
    get_locator_attribute,
    get_locator_text,
)


_PHOTO_COUNT_RE = re.compile(r"(\d[\d,]*)")


class MiscExtractor:
    name = "misc"

    def extract(self, ctx: PropertyFeatureContext) -> dict:
        out: dict = {}

        languages = self._languages(ctx)
        if languages:
            out["languages_spoken"] = languages

        photo_count = self._photo_count(ctx)
        if photo_count is not None:
            out["photo_count"] = photo_count

        sustainability = get_locator_text(
            ctx.page.locator('[data-testid="sustainability-property-badge"]')
        )
        if sustainability:
            out["sustainability_level"] = sustainability

        return out

    def _languages(self, ctx: PropertyFeatureContext) -> list[str]:
        groups = ctx.page.locator('[data-testid="facility-group-container"]')
        for group_index in range(groups.count()):
            group = groups.nth(group_index)
            heading = (get_locator_text(group.locator("h3")) or "").strip().lower()
            if not heading.startswith("languages spoken"):
                continue
            items = group.locator("li")
            languages = [
                text
                for item_index in range(items.count())
                if (text := get_locator_text(items.nth(item_index)))
            ]
            return languages
        return []

    def _photo_count(self, ctx: PropertyFeatureContext) -> int | None:
        for selector in (
            '[data-testid="gallery-cta-count"]',
            '[data-testid="PropertyGalleryGridButton"]',
        ):
            text = get_locator_text(ctx.page.locator(selector)) or get_locator_attribute(
                ctx.page.locator(selector), "aria-label"
            )
            if not text:
                continue
            match = _PHOTO_COUNT_RE.search(text)
            if match:
                return int(match.group(1).replace(",", ""))
        return None
