import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from tourism_pricing_analytics.analysis.eda import (
    modelling_table_summary,
    numeric_distribution,
)
from tourism_pricing_analytics.analysis.loader import (
    ModellingTableError,
    load_modelling_table,
    validate_modelling_table,
)
from tourism_pricing_analytics.analysis.segment import (
    property_type_counts,
    segment_self_catering,
    self_catering_property_types,
)


def sample_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "property_name": "Apartment One",
                "property_url": "https://example.test/a",
                "checkin": "2026-07-10",
                "checkout": "2026-07-14",
                "lead_time_days": 7,
                "stay_length_days": 4,
                "room_id": "101",
                "block_id": "101_a",
                "current_price_value": 400.0,
                "price_per_night": 100.0,
                "quantity_options": json.dumps(["0", "1 (EUR 400)"]),
                "amenities": json.dumps(["Kitchen", "Balcony"]),
                "review_subscores": json.dumps({"Cleanliness": 9.0}),
                "property_type": "Apartment",
                "latitude": 35.51,
                "longitude": 24.01,
                "room_size_sqm": 45.0,
                "bed_count": 2.0,
                "star_rating": None,
                "review_score": 9.2,
                "review_count": 100.0,
            },
            {
                "property_name": "Villa Two",
                "property_url": "https://example.test/v",
                "checkin": "2026-08-01",
                "checkout": "2026-08-08",
                "lead_time_days": 30,
                "stay_length_days": 7,
                "room_id": "201",
                "block_id": "201_a",
                "current_price_value": 1400.0,
                "price_per_night": 200.0,
                "quantity_options": json.dumps(["0", "1 (EUR 1400)"]),
                "amenities": json.dumps(["Pool"]),
                "review_subscores": json.dumps({"Location": 8.5}),
                "property_type": "Villa",
                "latitude": 35.52,
                "longitude": 24.02,
                "room_size_sqm": 85.0,
                "bed_count": None,
                "star_rating": 4.0,
                "review_score": 8.8,
                "review_count": 40.0,
            },
            {
                "property_name": "Hotel Three",
                "property_url": "https://example.test/h",
                "checkin": "2026-08-01",
                "checkout": "2026-08-05",
                "lead_time_days": 30,
                "stay_length_days": 4,
                "room_id": "301",
                "block_id": "301_a",
                "current_price_value": 600.0,
                "price_per_night": 150.0,
                "quantity_options": json.dumps(["0", "1 (EUR 600)"]),
                "amenities": json.dumps(["Restaurant"]),
                "review_subscores": json.dumps({"Staff": 9.0}),
                "property_type": "Hotel",
                "latitude": 35.53,
                "longitude": 24.03,
                "room_size_sqm": None,
                "bed_count": 1.0,
                "star_rating": 5.0,
                "review_score": 9.5,
                "review_count": 200.0,
            },
        ]
    )


class AnalysisLoaderTests(unittest.TestCase):
    def test_load_modelling_table_decodes_json_and_parses_dates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "table.parquet"
            sample_frame().to_parquet(path, index=False)

            loaded = load_modelling_table(path)

            self.assertEqual(loaded.shape[0], 3)
            self.assertEqual(loaded.loc[0, "amenities"], ["Kitchen", "Balcony"])
            self.assertEqual(loaded.loc[0, "review_subscores"], {"Cleanliness": 9.0})
            self.assertTrue(pd.api.types.is_datetime64_any_dtype(loaded["checkin"]))

    def test_validate_rejects_missing_required_columns(self) -> None:
        frame = sample_frame().drop(columns=["price_per_night"])
        with self.assertRaisesRegex(ModellingTableError, "Missing required columns"):
            validate_modelling_table(frame)

    def test_validate_rejects_bad_per_night_math(self) -> None:
        frame = sample_frame()
        frame.loc[0, "price_per_night"] = 10.0
        with self.assertRaisesRegex(ModellingTableError, "price_per_night"):
            validate_modelling_table(frame)


class AnalysisSegmentTests(unittest.TestCase):
    def test_self_catering_segment_matches_agreed_property_types(self) -> None:
        frame = sample_frame()
        segmented = segment_self_catering(frame)

        self.assertEqual(set(self_catering_property_types()), {"Apartment", "Aparthotel", "Holiday home", "Villa"})
        self.assertEqual(segmented["property_type"].tolist(), ["Apartment", "Villa"])

    def test_property_type_counts_are_sorted_and_null_safe(self) -> None:
        frame = sample_frame()
        frame.loc[0, "property_type"] = None

        self.assertEqual(
            property_type_counts(frame),
            {"(missing)": 1, "Hotel": 1, "Villa": 1},
        )


class AnalysisEdaTests(unittest.TestCase):
    def test_numeric_distribution_uses_non_null_values(self) -> None:
        distribution = numeric_distribution(sample_frame(), "room_size_sqm")

        self.assertEqual(distribution["count"], 2)
        self.assertEqual(distribution["min"], 45.0)
        self.assertEqual(distribution["max"], 85.0)

    def test_modelling_table_summary_is_json_ready(self) -> None:
        summary = modelling_table_summary(sample_frame())

        self.assertEqual(summary["rows"], 3)
        self.assertEqual(summary["properties"], 3)
        self.assertEqual(summary["checkin_min"], "2026-07-10")
        self.assertEqual(summary["lead_time_days"], [7, 30])
        self.assertEqual(summary["self_catering"]["rows"], 2)
        self.assertEqual(summary["property_type_counts"]["Hotel"], 1)
        json.dumps(summary, sort_keys=True)


if __name__ == "__main__":
    unittest.main()
