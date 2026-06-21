"""The feature-extractor registry.

Each list is the ordered set of extractors run for that scope. Adding a feature
means appending its extractor here; the runner reads these lists and needs no
other change. Room extractors (Tier B) are wired in Phase 1; property extractors
(Tier C) land in Phase 3.
"""

from tourism_pricing_analytics.scraping.booking.features.base import FeatureExtractor
from tourism_pricing_analytics.scraping.booking.features.property.facilities import (
    FacilitiesExtractor,
)
from tourism_pricing_analytics.scraping.booking.features.property.geo import GeoExtractor
from tourism_pricing_analytics.scraping.booking.features.property.misc import MiscExtractor
from tourism_pricing_analytics.scraping.booking.features.property.policies import (
    PoliciesExtractor,
)
from tourism_pricing_analytics.scraping.booking.features.property.prop_type import (
    PropertyTypeExtractor,
)
from tourism_pricing_analytics.scraping.booking.features.property.rating import (
    StarRatingExtractor,
)
from tourism_pricing_analytics.scraping.booking.features.property.reviews import (
    ReviewsExtractor,
)
from tourism_pricing_analytics.scraping.booking.features.property.surroundings import (
    SurroundingsExtractor,
)
from tourism_pricing_analytics.scraping.booking.features.room.amenities import AmenitiesExtractor
from tourism_pricing_analytics.scraping.booking.features.room.beds import BedExtractor
from tourism_pricing_analytics.scraping.booking.features.room.occupancy import OccupancyExtractor
from tourism_pricing_analytics.scraping.booking.features.room.room_class import RoomClassExtractor
from tourism_pricing_analytics.scraping.booking.features.room.size import RoomSizeExtractor


ROOM_EXTRACTORS: list[FeatureExtractor] = [
    RoomSizeExtractor(),
    BedExtractor(),
    OccupancyExtractor(),
    AmenitiesExtractor(),
    RoomClassExtractor(),
]
PROPERTY_EXTRACTORS: list[FeatureExtractor] = [
    StarRatingExtractor(),
    ReviewsExtractor(),
    GeoExtractor(),
    PropertyTypeExtractor(),
    FacilitiesExtractor(),
    SurroundingsExtractor(),
    PoliciesExtractor(),
    MiscExtractor(),
]
