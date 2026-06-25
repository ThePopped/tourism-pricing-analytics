import json
import unittest

import pandas as pd

from scripts.run_hedonic import build_report_payload, render_markdown_report
from tourism_pricing_analytics.analysis.hedonic import (
    build_design_matrix,
    explain_price_gap,
    feature_adjusted_peer_prices,
    fit_hedonic_models,
    group_kfold_splits,
)


def _row(
    property_url: str,
    property_name: str,
    checkin: str,
    price_per_night: float,
    *,
    property_type: str = "Apartment",
    latitude: float = 35.5,
    longitude: float = 24.0,
    room_size_sqm: float | None = 50.0,
    bed_count: float | None = 2.0,
    review_score: float | None = 9.0,
    star_rating: float | None = 4.0,
) -> dict[str, object]:
    return {
        "property_name": property_name,
        "property_url": property_url,
        "checkin": pd.Timestamp(checkin),
        "checkout": pd.Timestamp(checkin) + pd.Timedelta(days=4),
        "lead_time_days": 7,
        "stay_length_days": 4,
        "room_id": f"{property_url}-room",
        "room_name": "Deluxe Apartment",
        "block_id": f"{property_url}-{checkin}",
        "occupancy_text": "2 adults",
        "conditions_text": "Free cancellation",
        "current_price_text": f"EUR {price_per_night * 4}",
        "original_price_text": None,
        "current_price_value": price_per_night * 4,
        "original_price_value": None,
        "price_per_night": price_per_night,
        "captured_at": pd.Timestamp("2026-06-23"),
        "checkin_month": pd.Timestamp(checkin).month,
        "checkin_is_weekend": pd.Timestamp(checkin).dayofweek >= 5,
        "crete_season": "Peak",
        "meal_plan_ordinal": 0,
        "cancellation_flexibility_ordinal": 2.0,
        "room_size_sqm": room_size_sqm,
        "bed_count": bed_count,
        "max_persons": 2.0,
        "amenities": ["Kitchen", "Balcony", "Sea view"],
        "star_rating": star_rating,
        "review_score": review_score,
        "review_count": 100.0,
        "property_type": property_type,
        "latitude": latitude,
        "longitude": longitude,
        "review_subscores": {"Cleanliness": 9.0, "Location": 8.8},
        "property_facilities": ["Free WiFi", "Parking"],
        "nearby_poi": [
            {"poi_name": "Beach", "distance": 0.8, "unit": "km"},
            {"poi_name": "Airport", "distance": 10.0, "unit": "km"},
        ],
        "house_rules": {},
        "quantity_options": [],
    }


def sample_hedonic_frame() -> pd.DataFrame:
    rows = []
    specs = [
        ("subject", "Subject Stay", 150.0, 35.500, 24.000, 52.0, 2.0, 9.2, 4.0),
        ("near", "Near Peer", 120.0, 35.501, 24.001, 48.0, 2.0, 8.8, 4.0),
        ("middle", "Middle Peer", 180.0, 35.520, 24.000, 70.0, 3.0, 9.0, 4.0),
        ("villa", "Villa Peer", 260.0, 35.530, 24.010, 110.0, 4.0, 9.5, 5.0),
        ("small", "Small Peer", 95.0, 35.490, 23.990, 32.0, 1.0, 8.3, 3.0),
        ("missing", "Missing Peer", 130.0, 35.505, 24.002, None, None, None, None),
    ]
    for url, name, base_price, lat, lon, size, beds, score, stars in specs:
        rows.append(
            _row(
                url,
                name,
                "2026-07-01",
                base_price,
                property_type="Villa" if url == "villa" else "Apartment",
                latitude=lat,
                longitude=lon,
                room_size_sqm=size,
                bed_count=beds,
                review_score=score,
                star_rating=stars,
            )
        )
        rows.append(
            _row(
                url,
                name,
                "2026-08-01",
                base_price + 15.0,
                property_type="Villa" if url == "villa" else "Apartment",
                latitude=lat,
                longitude=lon,
                room_size_sqm=size,
                bed_count=beds,
                review_score=score,
                star_rating=stars,
            )
        )
    rows.append(_row("hotel", "Hotel", "2026-07-01", 200.0, property_type="Hotel"))
    return pd.DataFrame(rows)


class HedonicDesignMatrixTests(unittest.TestCase):
    def test_design_matrix_has_log_target_and_no_leakage_columns(self) -> None:
        X, y, groups, meta = build_design_matrix(sample_hedonic_frame(), min_token_frequency=1)

        self.assertEqual(X.shape[0], sample_hedonic_frame().shape[0])
        self.assertAlmostEqual(y.iloc[0], 5.010635294096255)
        self.assertEqual(groups.iloc[0], "subject")
        self.assertIn("room_size_sqm", X.columns)
        self.assertIn("room_size_sqm_missing", X.columns)
        self.assertIn("bed_count_missing", X.columns)
        self.assertIn("subscore_cleanliness", X.columns)
        self.assertIn("nearby_poi_count", X.columns)
        self.assertIn("property_type__apartment", X.columns)
        self.assertIn("amenity__kitchen", X.columns)
        self.assertNotIn("max_persons", X.columns)
        self.assertNotIn("property_url", X.columns)
        self.assertNotIn("price_per_night", X.columns)
        self.assertNotIn("latitude", meta.ols_feature_columns)
        self.assertIn("latitude", meta.gbm_feature_columns)

    def test_group_kfold_never_splits_one_property_across_train_and_test(self) -> None:
        _, _, groups, _ = build_design_matrix(sample_hedonic_frame(), min_token_frequency=1)
        for train_idx, test_idx in group_kfold_splits(groups, n_splits=3):
            train_groups = set(groups.iloc[train_idx])
            test_groups = set(groups.iloc[test_idx])
            self.assertFalse(train_groups & test_groups)


class HedonicModelTests(unittest.TestCase):
    def test_adjusted_peer_prices_and_gap_explanation_are_consistent(self) -> None:
        frame = sample_hedonic_frame()
        bundle = fit_hedonic_models(frame, min_token_frequency=1)
        peer_rows = frame.loc[frame["property_url"].isin(["near", "middle"])].copy()

        adjusted = feature_adjusted_peer_prices("subject", peer_rows, frame, bundle)
        self.assertEqual(adjusted.shape[0], peer_rows.shape[0])
        self.assertIn("feature_adjusted_price_per_night", adjusted.columns)
        self.assertTrue(adjusted["feature_adjusted_price_per_night"].notna().all())

        explanation = explain_price_gap(
            frame.loc[frame["property_url"] == "subject"].iloc[0],
            frame.loc[frame["property_url"] == "near"].iloc[0],
            frame,
            bundle,
        )
        self.assertAlmostEqual(
            explanation["observed_gap"],
            explanation["feature_explained_gap"] + explanation["residual_gap"],
        )
        json.dumps(explanation, sort_keys=True)

    def test_hedonic_report_renders(self) -> None:
        payload = build_report_payload(
            sample_hedonic_frame(),
            source_table="synthetic.parquet",
            client="subject",
            windows=[{"checkin": "2026-07-01", "lead_time_days": 7, "stay_length_days": 4}],
            max_peers=3,
            min_token_frequency=1,
        )
        report = render_markdown_report(payload)

        self.assertIn("# Hedonic Price Adjustment", report)
        self.assertIn("Feature-Adjusted Comparable Benchmark", report)
        self.assertIn("Price Gap Decomposition", report)


if __name__ == "__main__":
    unittest.main()
