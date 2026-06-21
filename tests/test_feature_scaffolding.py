"""Phase 0 scaffolding tests for the feature-extraction layer.

Covers the new feature record models, their JSONL serialization, the isolated
extractor runner, and the (intentionally empty) registry. No live scrape path is
exercised: this is pure structure plus a browser-free runner.
"""

import json
import unittest
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from tourism_pricing_analytics.scraping.booking.features.base import run_extractors
from tourism_pricing_analytics.scraping.booking.features.registry import (
    PROPERTY_EXTRACTORS,
    ROOM_EXTRACTORS,
)
from tourism_pricing_analytics.scraping.booking.io import (
    save_property_features,
    save_property_room_features,
)
from tourism_pricing_analytics.scraping.booking.models import (
    PropertyFeatureRecord,
    RoomFeatureRecord,
)
from tourism_pricing_analytics.scraping.booking.validation import load_jsonl_records


class _StubExtractor:
    def __init__(self, name: str, result, *, boom: bool = False) -> None:
        self.name = name
        self._result = result
        self._boom = boom

    def extract(self, ctx: object) -> dict:
        if self._boom:
            raise RuntimeError(f"{self.name} blew up")
        return self._result


class FeatureRecordModelTests(unittest.TestCase):
    def test_room_feature_record_defaults_are_empty_and_nullable(self) -> None:
        record = RoomFeatureRecord(
            property_name="Example Hotel",
            property_url="https://www.booking.com/hotel/gr/example.en-gb.html",
            room_id="12345601",
            captured_at="2026-06-20T18:00:00",
        )
        self.assertEqual(record.bed_types, [])
        self.assertEqual(record.amenities, [])
        self.assertIsNone(record.room_size_sqm)
        self.assertIsNone(record.max_persons)
        self.assertIsNone(record.room_class)

    def test_property_feature_record_defaults_are_empty_and_nullable(self) -> None:
        record = PropertyFeatureRecord(
            property_name="Example Hotel",
            property_url="https://www.booking.com/hotel/gr/example.en-gb.html",
            captured_at="2026-06-20T18:00:00",
        )
        self.assertEqual(record.review_subscores, {})
        self.assertEqual(record.property_facilities, [])
        self.assertEqual(record.nearby_poi, [])
        self.assertEqual(record.languages_spoken, [])
        self.assertIsNone(record.star_rating)
        self.assertIsNone(record.house_rules)

    def test_room_feature_record_round_trips_through_json(self) -> None:
        record = RoomFeatureRecord(
            property_name="Example Hotel",
            property_url="https://www.booking.com/hotel/gr/example.en-gb.html",
            room_id="12345601",
            captured_at="2026-06-20T18:00:00",
            room_size_sqm=28.0,
            bed_types=["1 large double bed"],
            bed_count=1,
            max_persons=2,
            amenities=["Air conditioning", "Free WiFi"],
            room_class="Deluxe",
        )
        restored = json.loads(json.dumps(asdict(record)))
        self.assertEqual(restored["room_id"], "12345601")
        self.assertEqual(restored["amenities"], ["Air conditioning", "Free WiFi"])
        self.assertEqual(restored["room_size_sqm"], 28.0)

    def test_property_feature_record_round_trips_through_json(self) -> None:
        record = PropertyFeatureRecord(
            property_name="Example Hotel",
            property_url="https://www.booking.com/hotel/gr/example.en-gb.html",
            captured_at="2026-06-20T18:00:00",
            star_rating=4.0,
            review_score=8.7,
            review_count=120,
            property_type="Hotel",
            latitude=35.3,
            longitude=25.1,
            review_subscores={"Cleanliness": 9.1, "Location": 9.4},
            property_facilities=["Pool", "Spa"],
            nearby_poi=[{"poi_name": "Beach", "distance": 300.0, "unit": "m"}],
            languages_spoken=["English", "Greek"],
        )
        restored = json.loads(json.dumps(asdict(record)))
        self.assertEqual(restored["review_subscores"], {"Cleanliness": 9.1, "Location": 9.4})
        self.assertEqual(restored["nearby_poi"][0]["poi_name"], "Beach")
        self.assertEqual(restored["languages_spoken"], ["English", "Greek"])


class FeatureRecordIoTests(unittest.TestCase):
    def test_room_features_jsonl_is_written_and_reloadable(self) -> None:
        record = RoomFeatureRecord(
            property_name="Example Hotel",
            property_url="https://www.booking.com/hotel/gr/example.en-gb.html",
            room_id="12345601",
            captured_at="2026-06-20T18:00:00",
            amenities=["Free WiFi"],
        )
        with TemporaryDirectory() as tmp:
            path = save_property_room_features([record], Path(tmp))
            self.assertEqual(path.name, "room_features.jsonl")
            records, issues = load_jsonl_records(path)
        self.assertEqual(issues, [])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["room_id"], "12345601")
        self.assertEqual(records[0]["amenities"], ["Free WiFi"])

    def test_property_features_jsonl_is_written_and_reloadable(self) -> None:
        record = PropertyFeatureRecord(
            property_name="Example Hotel",
            property_url="https://www.booking.com/hotel/gr/example.en-gb.html",
            captured_at="2026-06-20T18:00:00",
            review_score=8.7,
        )
        with TemporaryDirectory() as tmp:
            path = save_property_features([record], Path(tmp))
            self.assertEqual(path.name, "property_features.jsonl")
            records, issues = load_jsonl_records(path)
        self.assertEqual(issues, [])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["review_score"], 8.7)

    def test_empty_feature_lists_write_empty_files(self) -> None:
        with TemporaryDirectory() as tmp:
            room_path = save_property_room_features([], Path(tmp))
            prop_path = save_property_features([], Path(tmp))
            self.assertEqual(room_path.read_text(encoding="utf-8"), "")
            self.assertEqual(prop_path.read_text(encoding="utf-8"), "")


class RunExtractorsTests(unittest.TestCase):
    def test_empty_extractor_list_returns_empty_dict(self) -> None:
        self.assertEqual(run_extractors([], ctx=object()), {})

    def test_merges_results_in_order(self) -> None:
        extractors = [
            _StubExtractor("a", {"x": 1}),
            _StubExtractor("b", {"y": 2}),
        ]
        self.assertEqual(run_extractors(extractors, ctx=object()), {"x": 1, "y": 2})

    def test_later_extractor_overrides_earlier_key(self) -> None:
        extractors = [
            _StubExtractor("a", {"x": 1}),
            _StubExtractor("b", {"x": 2}),
        ]
        self.assertEqual(run_extractors(extractors, ctx=object()), {"x": 2})

    def test_failing_extractor_is_isolated(self) -> None:
        extractors = [
            _StubExtractor("a", {"x": 1}),
            _StubExtractor("boom", None, boom=True),
            _StubExtractor("c", {"z": 3}),
        ]
        with self.assertLogs(level="ERROR") as captured:
            result = run_extractors(extractors, ctx=object())
        self.assertEqual(result, {"x": 1, "z": 3})
        self.assertTrue(any("boom" in line for line in captured.output))

    def test_falsy_result_contributes_nothing(self) -> None:
        extractors = [
            _StubExtractor("a", {}),
            _StubExtractor("b", None),
            _StubExtractor("c", {"z": 3}),
        ]
        self.assertEqual(run_extractors(extractors, ctx=object()), {"z": 3})


class RegistryTests(unittest.TestCase):
    def test_room_and_property_extractors_registered(self) -> None:
        # Tier B room extractors are wired in Phase 1; Tier C property extractors
        # arrive in Phase 3.
        room_names = {extractor.name for extractor in ROOM_EXTRACTORS}
        self.assertEqual(
            room_names,
            {"room_size", "beds", "occupancy", "amenities", "room_class"},
        )
        property_names = {extractor.name for extractor in PROPERTY_EXTRACTORS}
        self.assertEqual(
            property_names,
            {
                "rating",
                "reviews",
                "geo",
                "prop_type",
                "facilities",
                "surroundings",
                "policies",
                "misc",
            },
        )

    def test_all_extractors_have_name_and_extract(self) -> None:
        for extractor in [*ROOM_EXTRACTORS, *PROPERTY_EXTRACTORS]:
            self.assertIsInstance(extractor.name, str)
            self.assertTrue(callable(extractor.extract))


if __name__ == "__main__":
    unittest.main()
