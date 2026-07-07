"""Phase 2 (Layer 2) unit tests: browser-free derivation, encoding, and join.

These exercise the pure feature functions over small synthetic record sets: no
Playwright, no live page. They assert the Tier A calendar/meal/cancellation
derivations, multi-hot/ordinal encoding behaviour (including unseen values), and
the price_rows ⋈ room_features ⋈ property_features join — including the
(property_url, room_name) -> room_id reconciliation for Booking "bbasic" rows.
"""

import unittest

from tourism_pricing_analytics.features.build_features import (
    build_features,
    build_room_name_index,
    resolve_room_id,
)
from tourism_pricing_analytics.features.cancellation import cancellation_features
from tourism_pricing_analytics.features.encoders import (
    add_amenity_multi_hot,
    build_amenity_vocabulary,
    is_room_size_token,
    multi_hot,
    normalize_amenity,
    ordinal_encode,
)
from tourism_pricing_analytics.features.meal_plan import (
    MEAL_PLAN_ORDINALS,
    meal_plan_features,
)
from tourism_pricing_analytics.features.seasonality import (
    crete_season,
    seasonality_features,
)


class SeasonalityTests(unittest.TestCase):
    def test_peak_summer_weekday(self) -> None:
        # 2026-07-15 is a Wednesday in ISO week 29.
        features = seasonality_features("2026-07-15")
        self.assertEqual(features["checkin_month"], 7)
        self.assertEqual(features["checkin_iso_week"], 29)
        self.assertEqual(features["checkin_day_of_week"], 2)
        self.assertFalse(features["checkin_is_weekend"])
        self.assertEqual(features["crete_season"], "peak")

    def test_weekend_flag_for_saturday_and_sunday(self) -> None:
        self.assertTrue(seasonality_features("2026-06-20")["checkin_is_weekend"])  # Sat
        self.assertTrue(seasonality_features("2026-06-21")["checkin_is_weekend"])  # Sun
        self.assertFalse(seasonality_features("2026-06-19")["checkin_is_weekend"])  # Fri

    def test_season_buckets(self) -> None:
        self.assertEqual(crete_season(8), "peak")
        self.assertEqual(crete_season(5), "shoulder")
        self.assertEqual(crete_season(10), "shoulder")
        self.assertEqual(crete_season(1), "off")
        self.assertEqual(crete_season(12), "off")

    def test_missing_or_malformed_checkin_yields_all_null(self) -> None:
        for value in (None, "", "not-a-date", "2026-13-40"):
            features = seasonality_features(value)
            self.assertEqual(
                features,
                {
                    "checkin_month": None,
                    "checkin_iso_week": None,
                    "checkin_day_of_week": None,
                    "checkin_is_weekend": None,
                    "crete_season": None,
                },
            )


class MealPlanTests(unittest.TestCase):
    def test_breakfast_included(self) -> None:
        result = meal_plan_features("Breakfast included")
        self.assertEqual(result, {"meal_plan": "breakfast", "meal_plan_ordinal": 1})

    def test_board_levels_outrank_breakfast(self) -> None:
        self.assertEqual(meal_plan_features("Half board included")["meal_plan"], "half_board")
        self.assertEqual(meal_plan_features("Full board")["meal_plan"], "full_board")

    def test_all_inclusive_wins_over_contained_breakfast(self) -> None:
        result = meal_plan_features("All inclusive (breakfast, lunch, dinner)")
        self.assertEqual(result["meal_plan"], "all_inclusive")
        self.assertEqual(result["meal_plan_ordinal"], 4)

    def test_unknown_text_falls_back_to_room_only(self) -> None:
        for value in (None, "", "Free cancellation"):
            result = meal_plan_features(value)
            self.assertEqual(result["meal_plan"], "room_only")
            self.assertEqual(result["meal_plan_ordinal"], 0)

    def test_ordinals_are_monotonic_in_inclusiveness(self) -> None:
        order = ["room_only", "breakfast", "half_board", "full_board", "all_inclusive"]
        values = [MEAL_PLAN_ORDINALS[label] for label in order]
        self.assertEqual(values, sorted(values))


class CancellationTests(unittest.TestCase):
    def test_free_cancellation(self) -> None:
        result = cancellation_features("Free cancellation before 20 June")
        self.assertTrue(result["free_cancellation"])
        self.assertFalse(result["non_refundable"])
        self.assertEqual(result["cancellation_flexibility_ordinal"], 1)

    def test_non_refundable_hyphen_variants(self) -> None:
        for text in ("Non-refundable", "Non refundable rate"):
            result = cancellation_features(text)
            self.assertTrue(result["non_refundable"])
            self.assertFalse(result["free_cancellation"])
            self.assertEqual(result["cancellation_flexibility_ordinal"], 0)

    def test_unknown_text_leaves_flags_off_and_ordinal_null(self) -> None:
        for value in (None, "", "Breakfast included"):
            result = cancellation_features(value)
            self.assertFalse(result["free_cancellation"])
            self.assertFalse(result["non_refundable"])
            self.assertIsNone(result["cancellation_flexibility_ordinal"])


class EncoderTests(unittest.TestCase):
    def test_vocabulary_is_normalized_sorted_and_deduped(self) -> None:
        vocab = build_amenity_vocabulary(
            [
                ["Air conditioning", "Free WiFi"],
                ["free wifi", "  Air  conditioning "],
                ["Balcony"],
            ]
        )
        self.assertEqual(vocab, ["air conditioning", "balcony", "free wifi"])

    def test_multi_hot_aligns_to_vocabulary_and_ignores_unseen(self) -> None:
        vocab = ["air conditioning", "balcony", "free wifi"]
        encoded = multi_hot(["Free WiFi", "Sea view"], vocab)
        # Sea view is not in the vocabulary, so it is silently dropped.
        self.assertEqual(encoded, [0, 0, 1])

    def test_multi_hot_handles_empty_values(self) -> None:
        self.assertEqual(multi_hot([], ["a", "b"]), [0, 0])
        self.assertEqual(multi_hot(None, ["a", "b"]), [0, 0])

    def test_ordinal_encode_defaults_on_unknown_and_null(self) -> None:
        mapping = {"breakfast": 1, "half_board": 2}
        self.assertEqual(ordinal_encode("half_board", mapping), 2)
        self.assertIsNone(ordinal_encode("unseen", mapping))
        self.assertEqual(ordinal_encode(None, mapping, default=-1), -1)

    def test_add_amenity_multi_hot_fits_across_all_rows(self) -> None:
        rows = [
            {"amenities": ["Air conditioning", "Free WiFi"]},
            {"amenities": ["Balcony"]},
            {"amenities": []},
        ]
        vocab = add_amenity_multi_hot(rows)
        self.assertEqual(vocab, ["air conditioning", "balcony", "free wifi"])
        self.assertEqual(rows[0]["amenity__free wifi"], 1)
        self.assertEqual(rows[0]["amenity__balcony"], 0)
        self.assertEqual(rows[1]["amenity__balcony"], 1)
        self.assertEqual(rows[2]["amenity__air conditioning"], 0)

    def test_normalize_amenity_collapses_whitespace_and_case(self) -> None:
        self.assertEqual(normalize_amenity("  Free   WiFi "), "free wifi")

    def test_is_room_size_token_matches_only_pure_size_measurements(self) -> None:
        for token in ("25 m²", "35 m2", "160 m²", "9.5 m²", "  40  m²  "):
            self.assertTrue(is_room_size_token(token), token)
        for token in (
            "Free WiFi",
            "Balcony",
            "Extra long beds (> 2 metres)",
            "Terrace 20 m² view",  # size embedded in a longer amenity, not pure
        ):
            self.assertFalse(is_room_size_token(token), token)

    def test_room_size_token_excluded_from_vocabulary(self) -> None:
        # Booking exposes room size ("25 m²") as a facility row that rides along
        # in the raw amenity list; it must not become an amenity vocab term.
        vocab = build_amenity_vocabulary(
            [
                ["Entire apartment", "35 m²", "Balcony"],
                ["27 m²", "Free WiFi"],
            ]
        )
        self.assertEqual(vocab, ["balcony", "entire apartment", "free wifi"])

    def test_multi_hot_ignores_room_size_tokens(self) -> None:
        vocab = ["balcony", "free wifi"]
        # A size token in the values must not accidentally match or error.
        self.assertEqual(multi_hot(["35 m²", "Free WiFi"], vocab), [0, 1])


class RoomNameIndexTests(unittest.TestCase):
    def test_index_keys_on_property_and_name(self) -> None:
        inventory = [
            {"property_url": "p1", "room_name": "Deluxe Double Room", "room_id": "111"},
            {"property_url": "p2", "room_name": "Deluxe Double Room", "room_id": "222"},
        ]
        index = build_room_name_index(inventory)
        self.assertEqual(index[("p1", "Deluxe Double Room")], "111")
        self.assertEqual(index[("p2", "Deluxe Double Room")], "222")

    def test_first_id_wins_for_duplicate_name(self) -> None:
        inventory = [
            {"property_url": "p1", "room_name": "Suite", "room_id": "first"},
            {"property_url": "p1", "room_name": "Suite", "room_id": "second"},
        ]
        index = build_room_name_index(inventory)
        self.assertEqual(index[("p1", "Suite")], "first")

    def test_records_missing_fields_are_skipped(self) -> None:
        inventory = [
            {"property_url": "p1", "room_name": None, "room_id": "111"},
            {"property_url": "p1", "room_name": "Suite", "room_id": None},
        ]
        self.assertEqual(build_room_name_index(inventory), {})


class ResolveRoomIdTests(unittest.TestCase):
    def setUp(self) -> None:
        self.index = {("p1", "Deluxe Double Room"): "999"}

    def test_existing_id_is_returned_unchanged(self) -> None:
        row = {"property_url": "p1", "room_id": "123", "room_name": "Deluxe Double Room"}
        self.assertEqual(resolve_room_id(row, self.index), "123")

    def test_null_id_is_reconciled_by_name(self) -> None:
        row = {"property_url": "p1", "room_id": None, "room_name": "Deluxe Double Room"}
        self.assertEqual(resolve_room_id(row, self.index), "999")

    def test_unmatched_name_returns_none(self) -> None:
        row = {"property_url": "p1", "room_id": None, "room_name": "Unknown Room"}
        self.assertIsNone(resolve_room_id(row, self.index))


class BuildFeaturesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.price_rows = [
            {
                "property_url": "p1",
                "property_name": "Hotel One",
                "room_id": "111",
                "room_name": "Classic Double Room",
                "checkin": "2026-07-15",
                "conditions_text": "Breakfast included",
                "current_price_value": 200.0,
            },
            {
                # bbasic generic block: null id but a name present in inventory.
                "property_url": "p1",
                "property_name": "Hotel One",
                "room_id": None,
                "room_name": "Deluxe Double Room",
                "checkin": "2026-01-10",
                "conditions_text": "Non-refundable",
                "current_price_value": 150.0,
            },
            {
                # No id and a name not in inventory: stays unattributed.
                "property_url": "p1",
                "property_name": "Hotel One",
                "room_id": None,
                "room_name": "Mystery Room",
                "checkin": "2026-05-01",
                "conditions_text": "Free cancellation",
                "current_price_value": 175.0,
            },
        ]
        self.room_features = [
            {
                "property_url": "p1",
                "property_name": "Hotel One",
                "captured_at": "2026-06-20T00:00:00",
                "room_id": "111",
                "room_size_sqm": 25.0,
                "max_persons": 2,
                "amenities": ["Air conditioning"],
            },
            {
                "property_url": "p1",
                "property_name": "Hotel One",
                "captured_at": "2026-06-20T00:00:00",
                "room_id": "222",
                "room_size_sqm": 30.0,
                "max_persons": 3,
                "amenities": ["Balcony"],
            },
        ]
        self.property_features = [
            {
                "property_url": "p1",
                "property_name": "Hotel One",
                "captured_at": "2026-06-20T00:00:00",
                "star_rating": 4.0,
                "review_score": 8.7,
            }
        ]
        self.room_inventory = [
            {"property_url": "p1", "room_name": "Classic Double Room", "room_id": "111"},
            {"property_url": "p1", "room_name": "Deluxe Double Room", "room_id": "222"},
        ]

    def _build(self):
        return build_features(
            self.price_rows,
            self.room_features,
            self.property_features,
            self.room_inventory,
        )

    def test_cardinality_is_one_row_per_price_row(self) -> None:
        rows = self._build()
        self.assertEqual(len(rows), len(self.price_rows))

    def test_room_and_property_features_join_on_keys(self) -> None:
        row = self._build()[0]
        self.assertEqual(row["room_size_sqm"], 25.0)
        self.assertEqual(row["max_persons"], 2)
        self.assertEqual(row["star_rating"], 4.0)
        self.assertEqual(row["review_score"], 8.7)
        # Price-row identity is preserved, not overwritten by feature records.
        self.assertEqual(row["current_price_value"], 200.0)
        self.assertFalse(row["room_id_reconciled"])

    def test_tier_a_derivations_are_attached(self) -> None:
        row = self._build()[0]
        self.assertEqual(row["crete_season"], "peak")
        self.assertEqual(row["meal_plan"], "breakfast")
        self.assertTrue(row["free_cancellation"] is False)

    def test_null_id_row_is_reconciled_by_name_and_joins_room_features(self) -> None:
        row = self._build()[1]
        self.assertEqual(row["room_id"], "222")
        self.assertTrue(row["room_id_reconciled"])
        self.assertEqual(row["room_size_sqm"], 30.0)
        self.assertEqual(row["max_persons"], 3)
        self.assertEqual(row["crete_season"], "off")
        self.assertTrue(row["non_refundable"])

    def test_unmatched_name_row_has_no_room_features(self) -> None:
        row = self._build()[2]
        self.assertIsNone(row["room_id"])
        self.assertFalse(row["room_id_reconciled"])
        self.assertNotIn("room_size_sqm", row)
        # Property features still join, and Tier A still derives.
        self.assertEqual(row["star_rating"], 4.0)
        self.assertTrue(row["free_cancellation"])
        self.assertEqual(row["crete_season"], "shoulder")

    def test_amenity_multi_hot_over_built_rows(self) -> None:
        rows = self._build()
        vocab = add_amenity_multi_hot(rows)
        self.assertIn("air conditioning", vocab)
        self.assertIn("balcony", vocab)
        self.assertEqual(rows[0]["amenity__air conditioning"], 1)
        self.assertEqual(rows[1]["amenity__balcony"], 1)


if __name__ == "__main__":
    unittest.main()
