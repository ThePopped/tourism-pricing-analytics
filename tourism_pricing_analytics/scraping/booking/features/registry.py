"""The feature-extractor registry.

Each list is the ordered set of extractors run for that scope. Adding a feature
means appending its extractor here; the runner reads these lists and needs no
other change. Both lists are intentionally empty at Phase 0 scaffolding — room
extractors land in Phase 1 and property extractors in Phase 3.
"""

from tourism_pricing_analytics.scraping.booking.features.base import FeatureExtractor


ROOM_EXTRACTORS: list[FeatureExtractor] = []
PROPERTY_EXTRACTORS: list[FeatureExtractor] = []
