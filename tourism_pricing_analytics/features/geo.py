"""Location features for the hedonic model.

Raw ``latitude``/``longitude`` are almost useless to a tree model on their own:
two properties a few hundred metres apart on the same beach differ by tiny
coordinate deltas the trees cannot turn into a "close to the sea" signal. This
module converts coordinates plus the scraped Booking.com POI blocks into
interpretable distance features -- distance to the nearest beach, to Chania's
centre, to the airport, to the nearest town, and to the nearest top attraction.

Two sources feed each feature, in order of preference:

1. **Scraped POI distances** -- Booking lists nearby beaches / attractions /
   airports with distances, so use those where the relevant category is present.
2. **Haversine to a curated anchor set** -- a small, hand-maintained dictionary
   of Chania-region landmark coordinates, used as the consistent fallback so
   every property (coordinates are 100% populated) gets a value even when a POI
   category is missing.

``haversine_km`` is reused from :mod:`competitors` so there is a single
great-circle implementation in the codebase.
"""

from __future__ import annotations

import math
from typing import Iterable, Mapping, Sequence

import pandas as pd

from tourism_pricing_analytics.analysis.competitors import haversine_km

Coord = tuple[float, float]

# --- Curated Chania-region anchors -----------------------------------------
# Approximate landmark coordinates (lat, lon) maintained by hand. They span the
# scraped coverage strip -- Maleme/Gerani on the west to Akrotiri/Souda on the
# east -- plus a couple of inland/southern landmarks. Anchors may sit just
# outside the property bounding box; they are reference points, not properties.
# The client's subject property is in Gerani (west coast), so that beach/town is
# deliberately included.

CHANIA_CENTRE: Coord = (35.5175, 24.0190)  # Venetian harbour / old town
CHANIA_AIRPORT: Coord = (35.5317, 24.1497)  # CHQ, Akrotiri peninsula

CURATED_BEACHES: dict[str, Coord] = {
    "maleme": (35.5290, 23.8330),
    "gerani": (35.5075, 23.9195),
    "platanias": (35.5125, 23.9410),
    "agia_marina": (35.5150, 23.9640),
    "agioi_apostoloi": (35.5165, 23.9905),
    "nea_chora": (35.5155, 24.0085),
    "kalamaki": (35.5015, 24.0350),
    "kalathas": (35.5680, 24.1245),
    "stavros": (35.5960, 24.1235),
    "marathi": (35.5470, 24.1730),
}

CURATED_TOWNS: dict[str, Coord] = {
    "chania": (35.5138, 24.0180),
    "platanias": (35.5105, 23.9400),
    "maleme": (35.5290, 23.8330),
    "souda": (35.4870, 24.0700),
    "mournies": (35.4820, 24.0230),
    "vamos": (35.4060, 24.2010),
}

CURATED_ATTRACTIONS: dict[str, Coord] = {
    "venetian_harbour": (35.5185, 24.0155),
    "municipal_market": (35.5140, 24.0195),
    "samaria_gorge": (35.3080, 23.9070),
    "lake_kournas": (35.3320, 24.2760),
}

# Scraped POI ``category`` substrings (matched case-insensitively).
BEACH_KEYWORDS: tuple[str, ...] = ("beach",)
AIRPORT_KEYWORDS: tuple[str, ...] = ("airport",)
ATTRACTION_KEYWORDS: tuple[str, ...] = ("attraction",)

# Feature columns produced by :func:`add_location_features`. Ordered to keep the
# design matrix stable across runs.
GEO_DISTANCE_FEATURES: tuple[str, ...] = (
    "nearest_beach_km",
    "chania_centre_km",
    "airport_km",
    "urban_centre_km",
    "top_attraction_km",
)


def _is_missing(value: object) -> bool:
    if value is None or value is pd.NA:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return False


def _coord_or_none(value: object) -> float | None:
    if _is_missing(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number):
        return None
    return number


def _poi_distance_km(item: Mapping[str, object]) -> float | None:
    """Return a scraped POI distance in km, converting from metres when needed."""

    distance = _coord_or_none(item.get("distance"))
    if distance is None:
        return None
    unit = str(item.get("unit") or "km").lower()
    if unit in {"m", "meter", "meters", "metre", "metres"}:
        distance = distance / 1000.0
    return distance


def nearest_category_km(
    nearby_poi: object,
    keywords: Sequence[str],
) -> float | None:
    """Smallest scraped POI distance (km) whose category matches any keyword."""

    if not isinstance(nearby_poi, (list, tuple)):
        return None
    lowered = tuple(keyword.lower() for keyword in keywords)
    best: float | None = None
    for item in nearby_poi:
        if not isinstance(item, Mapping):
            continue
        category = str(item.get("category") or "").lower()
        if not any(keyword in category for keyword in lowered):
            continue
        distance = _poi_distance_km(item)
        if distance is None:
            continue
        if best is None or distance < best:
            best = distance
    return best


def nearest_anchor_km(
    latitude: object,
    longitude: object,
    anchors: Iterable[Coord],
) -> float | None:
    """Smallest haversine distance (km) from a point to any curated anchor."""

    lat = _coord_or_none(latitude)
    lon = _coord_or_none(longitude)
    if lat is None or lon is None:
        return None
    best: float | None = None
    for anchor_lat, anchor_lon in anchors:
        distance = haversine_km(lat, lon, anchor_lat, anchor_lon)
        if best is None or distance < best:
            best = distance
    return best


def _min_present(*values: float | None) -> float | None:
    present = [value for value in values if value is not None]
    return min(present) if present else None


def location_features(
    latitude: object,
    longitude: object,
    nearby_poi: object,
) -> dict[str, float | None]:
    """Distance features for one property from coordinates + scraped POI."""

    beach = _min_present(
        nearest_category_km(nearby_poi, BEACH_KEYWORDS),
        nearest_anchor_km(latitude, longitude, CURATED_BEACHES.values()),
    )
    airport = _min_present(
        nearest_category_km(nearby_poi, AIRPORT_KEYWORDS),
        nearest_anchor_km(latitude, longitude, (CHANIA_AIRPORT,)),
    )
    attraction = _min_present(
        nearest_category_km(nearby_poi, ATTRACTION_KEYWORDS),
        nearest_anchor_km(latitude, longitude, CURATED_ATTRACTIONS.values()),
    )
    centre = nearest_anchor_km(latitude, longitude, (CHANIA_CENTRE,))
    urban = nearest_anchor_km(latitude, longitude, CURATED_TOWNS.values())
    return {
        "nearest_beach_km": beach,
        "chania_centre_km": centre,
        "airport_km": airport,
        "urban_centre_km": urban,
        "top_attraction_km": attraction,
    }


def add_location_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Add :data:`GEO_DISTANCE_FEATURES` columns, leaving existing ones intact."""

    out = frame.copy()
    missing = [column for column in GEO_DISTANCE_FEATURES if column not in out]
    if not missing:
        return out

    latitudes = out["latitude"] if "latitude" in out else pd.Series(index=out.index, dtype=float)
    longitudes = out["longitude"] if "longitude" in out else pd.Series(index=out.index, dtype=float)
    poi = out["nearby_poi"] if "nearby_poi" in out else pd.Series([None] * len(out), index=out.index)

    computed = [
        location_features(lat, lon, poi_value)
        for lat, lon, poi_value in zip(latitudes, longitudes, poi)
    ]
    for column in missing:
        out[column] = [row[column] for row in computed]
    return out
