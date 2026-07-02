"""Tests for the location-feature module (Phase B of the hedonic upgrade).

Covers scraped-POI distance extraction (including metre->km conversion),
haversine-to-anchor fallback, the scraped-vs-anchor min composition, null
handling, and the DataFrame wiring used by the hedonic feature frame.
"""

import math
import unittest

import pandas as pd

from tourism_pricing_analytics.analysis.competitors import haversine_km
from tourism_pricing_analytics.features.geo import (
    CHANIA_CENTRE,
    GEO_DISTANCE_FEATURES,
    add_location_features,
    location_features,
    nearest_anchor_km,
    nearest_category_km,
)


class NearestCategoryTests(unittest.TestCase):
    def test_returns_min_matching_distance_in_km(self):
        poi = [
            {"category": "Beaches in the neighbourhood", "distance": 1.2, "unit": "km"},
            {"category": "Beaches in the neighbourhood", "distance": 300, "unit": "m"},
            {"category": "Top attractions", "distance": 0.1, "unit": "km"},
        ]
        self.assertAlmostEqual(nearest_category_km(poi, ("beach",)), 0.3)

    def test_converts_metres_to_km(self):
        poi = [{"category": "Closest airports", "distance": 15000, "unit": "m"}]
        self.assertAlmostEqual(nearest_category_km(poi, ("airport",)), 15.0)

    def test_no_matching_category_returns_none(self):
        poi = [{"category": "Restaurants & cafes", "distance": 0.2, "unit": "km"}]
        self.assertIsNone(nearest_category_km(poi, ("beach",)))

    def test_non_list_input_returns_none(self):
        self.assertIsNone(nearest_category_km(None, ("beach",)))
        self.assertIsNone(nearest_category_km("[]", ("beach",)))


class NearestAnchorTests(unittest.TestCase):
    def test_matches_haversine_to_single_anchor(self):
        lat, lon = 35.5075, 23.9195
        expected = haversine_km(lat, lon, *CHANIA_CENTRE)
        self.assertAlmostEqual(nearest_anchor_km(lat, lon, (CHANIA_CENTRE,)), expected)

    def test_picks_closest_of_several_anchors(self):
        anchors = [(35.60, 24.10), (35.50, 23.92), (35.20, 24.00)]
        got = nearest_anchor_km(35.5075, 23.9195, anchors)
        expected = min(haversine_km(35.5075, 23.9195, a, b) for a, b in anchors)
        self.assertAlmostEqual(got, expected)

    def test_missing_coordinate_returns_none(self):
        self.assertIsNone(nearest_anchor_km(None, 24.0, (CHANIA_CENTRE,)))
        self.assertIsNone(nearest_anchor_km(35.5, float("nan"), (CHANIA_CENTRE,)))


class LocationFeatureTests(unittest.TestCase):
    def test_prefers_scraped_beach_over_anchor_when_closer(self):
        # Inland point (far from every curated beach) whose scraped beach is 50 m.
        feats = location_features(
            35.3200,
            23.9800,
            [{"category": "Beaches in the neighbourhood", "distance": 50, "unit": "m"}],
        )
        self.assertAlmostEqual(feats["nearest_beach_km"], 0.05)

    def test_falls_back_to_anchor_when_beach_missing(self):
        feats = location_features(35.5075, 23.9195, [])
        self.assertIsNotNone(feats["nearest_beach_km"])
        # With no scraped beach the value must equal the nearest curated beach.
        from tourism_pricing_analytics.features.geo import CURATED_BEACHES

        expected = min(
            haversine_km(35.5075, 23.9195, a, b) for a, b in CURATED_BEACHES.values()
        )
        self.assertAlmostEqual(feats["nearest_beach_km"], expected)

    def test_all_features_present_with_coordinates(self):
        feats = location_features(35.5075, 23.9195, [])
        for column in GEO_DISTANCE_FEATURES:
            self.assertIn(column, feats)
            self.assertIsNotNone(feats[column], column)
            self.assertGreaterEqual(feats[column], 0.0)

    def test_missing_coordinates_yield_only_scraped_signal(self):
        feats = location_features(
            None,
            None,
            [{"category": "Beaches in the neighbourhood", "distance": 0.4, "unit": "km"}],
        )
        self.assertAlmostEqual(feats["nearest_beach_km"], 0.4)
        # Purely anchor-based features have no fallback without coordinates.
        self.assertIsNone(feats["chania_centre_km"])
        self.assertIsNone(feats["urban_centre_km"])


class AddLocationFeaturesTests(unittest.TestCase):
    def test_adds_all_columns(self):
        frame = pd.DataFrame(
            {
                "latitude": [35.3200, 35.5138],
                "longitude": [23.9800, 24.0180],
                "nearby_poi": [
                    [{"category": "Beaches in the neighbourhood", "distance": 0.1, "unit": "km"}],
                    None,
                ],
            }
        )
        out = add_location_features(frame)
        for column in GEO_DISTANCE_FEATURES:
            self.assertIn(column, out)
            self.assertFalse(out[column].isna().any(), column)
        self.assertAlmostEqual(out.loc[0, "nearest_beach_km"], 0.1)

    def test_preserves_existing_columns(self):
        frame = pd.DataFrame(
            {
                "latitude": [35.5],
                "longitude": [24.0],
                "nearby_poi": [None],
                "nearest_beach_km": [1.23],
            }
        )
        out = add_location_features(frame)
        self.assertAlmostEqual(out.loc[0, "nearest_beach_km"], 1.23)


if __name__ == "__main__":
    unittest.main()
