import json
import unittest

import pandas as pd

from tourism_pricing_analytics.analysis.competitors import (
    ComparableBenchmarkConfig,
    ComparableBenchmarkError,
    build_comparable_candidates,
    build_property_profiles,
    comparable_benchmark,
    haversine_km,
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
    room_size_sqm: float = 50.0,
    review_score: float = 9.0,
    star_rating: float = 4.0,
    amenities: list[str] | None = None,
    facilities: list[str] | None = None,
) -> dict[str, object]:
    return {
        "property_name": property_name,
        "property_url": property_url,
        "checkin": pd.Timestamp(checkin),
        "checkout": pd.Timestamp(checkin) + pd.Timedelta(days=4),
        "lead_time_days": 7,
        "stay_length_days": 4,
        "room_id": f"{property_name}-room",
        "block_id": f"{property_name}-{checkin}",
        "current_price_value": price_per_night * 4,
        "price_per_night": price_per_night,
        "property_type": property_type,
        "latitude": latitude,
        "longitude": longitude,
        "room_size_sqm": room_size_sqm,
        "review_score": review_score,
        "review_count": 100.0,
        "star_rating": star_rating,
        "amenities": amenities or ["Kitchen", "Balcony"],
        "property_facilities": facilities or ["Free WiFi", "Parking"],
    }


def sample_competitor_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            _row("subject", "Subject Stay", "2026-07-01", 150.0),
            _row("subject", "Subject Stay", "2026-08-01", 160.0, room_size_sqm=54.0),
            _row("near", "Near Peer", "2026-07-01", 110.0, latitude=35.501, longitude=24.001),
            _row("near", "Near Peer", "2026-08-01", 120.0, latitude=35.501, longitude=24.001),
            _row(
                "middle",
                "Middle Peer",
                "2026-07-01",
                220.0,
                latitude=35.52,
                longitude=24.0,
                room_size_sqm=65.0,
                review_score=8.8,
            ),
            _row(
                "far",
                "Far Peer",
                "2026-07-01",
                90.0,
                latitude=35.8,
                longitude=24.0,
            ),
            _row(
                "hotel",
                "Hotel Peer",
                "2026-07-01",
                80.0,
                property_type="Hotel",
                latitude=35.501,
                longitude=24.001,
            ),
        ]
    )


class ComparableBenchmarkTests(unittest.TestCase):
    def test_haversine_km_returns_zero_for_same_point(self) -> None:
        self.assertEqual(haversine_km(35.5, 24.0, 35.5, 24.0), 0.0)

    def test_property_profiles_are_one_row_per_property(self) -> None:
        profiles = build_property_profiles(sample_competitor_frame())
        subject = profiles.loc[profiles["property_url"] == "subject"].iloc[0]

        self.assertEqual(profiles["property_url"].nunique(), 5)
        self.assertEqual(subject["price_row_count"], 2)
        self.assertEqual(subject["median_price_per_night"], 155.0)
        self.assertEqual(subject["median_room_size_sqm"], 52.0)
        self.assertIn("kitchen", subject["feature_tokens"])

    def test_comparable_candidates_rank_by_distance_and_features(self) -> None:
        config = ComparableBenchmarkConfig(max_peers=2, max_distance_km=5.0)
        candidates = build_comparable_candidates(
            sample_competitor_frame().query("property_type != 'Hotel'"),
            "subject",
            config,
        )

        self.assertEqual(candidates["property_url"].tolist(), ["near", "middle"])
        self.assertLess(candidates.loc[0, "distance_km"], candidates.loc[1, "distance_km"])
        self.assertNotIn("far", candidates["property_url"].tolist())
        self.assertGreater(candidates.loc[0, "overall_similarity"], candidates.loc[1, "overall_similarity"])

    def test_benchmark_matches_peer_rows_to_subject_contexts(self) -> None:
        config = ComparableBenchmarkConfig(
            max_peers=2,
            min_peers=3,
            max_distance_km=5.0,
            min_peer_price_rows=4,
        )
        benchmark = comparable_benchmark(sample_competitor_frame(), "subject", config)

        self.assertEqual(benchmark["subject"]["median_price_per_night"], 155.0)
        self.assertEqual(benchmark["peer_set"]["candidate_properties"], 2)
        self.assertEqual(benchmark["coverage"]["subject_contexts"], 2)
        self.assertEqual(benchmark["coverage"]["matched_peer_contexts"], 2)
        self.assertEqual(benchmark["peer_price_distribution"]["count"], 3)
        self.assertEqual(benchmark["peer_price_distribution"]["median"], 120.0)
        self.assertEqual(benchmark["subject_percentile_vs_peers"], 66.67)
        self.assertEqual(benchmark["price_gap_to_peer_median"], 35.0)
        self.assertIn("weak_peer_set", benchmark["peer_set"]["flags"])
        self.assertIn("sparse_peer_price_coverage", benchmark["peer_set"]["flags"])
        json.dumps(benchmark, sort_keys=True)

    def test_benchmark_rejects_subject_outside_segment(self) -> None:
        with self.assertRaisesRegex(ComparableBenchmarkError, "analysis segment"):
            comparable_benchmark(sample_competitor_frame(), "hotel")


if __name__ == "__main__":
    unittest.main()
