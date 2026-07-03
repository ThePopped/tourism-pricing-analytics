"""Tests for curated high-value amenity/quality binaries (Phase C).

Covers the word-boundary matcher (synonyms match, lookalike tokens like
"kitchenware" do not), the combined amenity+facility source, and the hedonic
wiring: curated columns enter the design matrix / OLS set always-on, while
constant-across-training features are dropped.
"""

import unittest

import numpy as np
import pandas as pd

from tourism_pricing_analytics.analysis.hedonic import _fit_feature_meta
from tourism_pricing_analytics.features.quality import (
    CURATED_QUALITY_FEATURES,
    QUALITY_FEATURE_COLUMNS,
    quality_flags,
)


class QualityMatcherTests(unittest.TestCase):
    def test_matches_synonyms(self):
        flags = quality_flags({"ocean view", "outdoor swimming pool"})
        self.assertEqual(flags["hq__sea_view"], 1)
        self.assertEqual(flags["hq__pool"], 1)

    def test_kitchen_matches_but_kitchenware_does_not(self):
        self.assertEqual(quality_flags({"kitchen"})["hq__kitchen"], 1)
        self.assertEqual(quality_flags({"kitchenette"})["hq__kitchen"], 1)
        self.assertEqual(quality_flags({"kitchenware"})["hq__kitchen"], 0)

    def test_absent_features_are_zero(self):
        flags = quality_flags({"free wifi"})
        self.assertTrue(all(value == 0 for value in flags.values()))

    def test_phrase_not_matched_across_separate_tokens(self):
        # "private" and "entrance" as distinct tokens must not spuriously fire
        # the "private entrance" phrase.
        flags = quality_flags({"private", "entrance to garden"})
        self.assertEqual(flags["hq__private_entrance"], 0)

    def test_all_curated_columns_present(self):
        flags = quality_flags(set())
        self.assertEqual(set(flags), set(QUALITY_FEATURE_COLUMNS))
        self.assertEqual(len(QUALITY_FEATURE_COLUMNS), len(CURATED_QUALITY_FEATURES))


def _training_frame() -> pd.DataFrame:
    # Mix of amenity/facility content so some curated features vary and one
    # (air conditioning) is constant across every row.
    amenities = [
        ["Sea view", "Balcony", "Air conditioning"],
        ["Outdoor swimming pool", "Kitchen", "Air conditioning"],
        ["Beachfront", "Washing machine", "Air conditioning"],
        ["Garden view", "Private entrance", "Air conditioning"],
    ]
    facilities = [
        ["Free parking"],
        ["Hot tub"],
        ["Terrace"],
        ["Free WiFi"],
    ]
    return pd.DataFrame(
        {
            "property_url": ["a", "b", "c", "d"],
            "price_per_night": [100.0, 150.0, 200.0, 120.0],
            "amenities": amenities,
            "property_facilities": facilities,
        }
    )


class QualityWiringTests(unittest.TestCase):
    def test_curated_columns_enter_design_matrix(self):
        meta = _fit_feature_meta(_training_frame(), min_token_frequency=25)
        # Varying curated features are present even with a high frequency floor
        # that suppresses the generic multi-hot.
        self.assertIn("hq__pool", meta.feature_columns)
        self.assertIn("hq__sea_view", meta.feature_columns)
        self.assertIn("hq__beachfront", meta.feature_columns)

    def test_constant_feature_is_dropped(self):
        meta = _fit_feature_meta(_training_frame(), min_token_frequency=25)
        # Air conditioning appears in every row -> no variance -> dropped.
        self.assertNotIn("hq__air_conditioning", meta.feature_columns)

    def test_curated_columns_are_in_ols_set(self):
        meta = _fit_feature_meta(_training_frame(), min_token_frequency=25)
        self.assertIn("hq__pool", meta.ols_feature_columns)

    def test_kept_features_recorded_on_meta(self):
        meta = _fit_feature_meta(_training_frame(), min_token_frequency=25)
        self.assertIn("hq__pool", meta.quality_features)
        self.assertNotIn("hq__air_conditioning", meta.quality_features)


if __name__ == "__main__":
    unittest.main()
