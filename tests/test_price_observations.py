import unittest

import pandas as pd

from tourism_pricing_analytics.analysis.movement import (
    AVAILABILITY_STATUS_AVAILABLE,
    AVAILABILITY_STATUS_FAILED,
    AVAILABILITY_STATUS_NO_OFFER,
    OBSERVATION_DEDUPE_KEY,
    OFFER_PRESENCE_COLUMNS,
    PRESENCE_DEDUPE_KEY,
    PRICE_OBSERVATION_COLUMNS,
    MovementHistoryError,
    normalize_offer_presence,
    normalize_price_observations,
    validate_offer_presence,
    validate_price_observations,
)


def sample_price_observation(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "snapshot_date": "2026-06-30",
        "captured_at": "2026-06-30T09:15:00",
        "run_id": "20260630_091500_000000",
        "property_url": "https://example.test/apartment-one",
        "property_name": "Apartment One",
        "room_id": "101",
        "room_name": "Sea View Studio",
        "block_id": "101_2026-07-15_2026-07-19",
        "checkin": "2026-07-15",
        "checkout": "2026-07-19",
        "lead_time_days": 15,
        "stay_length_days": 4,
        "adults": 2,
        "children": 0,
        "rooms": 1,
        "currency": "EUR",
        "market": "Chania",
        "price_per_night": 125.0,
        "current_price_value": 500.0,
        "property_type": "Apartment",
        "latitude": 35.515,
        "longitude": 24.018,
    }
    row.update(overrides)
    return row


def sample_offer_presence(**overrides: object) -> dict[str, object]:
    row = {
        column: value
        for column, value in sample_price_observation().items()
        if column not in {"room_id", "room_name", "block_id", "price_per_night", "current_price_value"}
    }
    row["availability_status"] = AVAILABILITY_STATUS_AVAILABLE
    row["failure_reason"] = None
    row.update(overrides)
    return row


class PriceObservationContractTests(unittest.TestCase):
    def test_price_observation_schema_lists_required_columns(self) -> None:
        self.assertIn("snapshot_date", PRICE_OBSERVATION_COLUMNS)
        self.assertIn("captured_at", PRICE_OBSERVATION_COLUMNS)
        self.assertIn("property_url", PRICE_OBSERVATION_COLUMNS)
        self.assertIn("room_id", PRICE_OBSERVATION_COLUMNS)
        self.assertIn("block_id", PRICE_OBSERVATION_COLUMNS)
        self.assertIn("price_per_night", PRICE_OBSERVATION_COLUMNS)
        self.assertIn("current_price_value", PRICE_OBSERVATION_COLUMNS)

        frame = pd.DataFrame([sample_price_observation()])
        validate_price_observations(frame)

    def test_price_observation_requires_contract_columns(self) -> None:
        frame = pd.DataFrame([sample_price_observation()]).drop(columns=["currency"])

        with self.assertRaisesRegex(MovementHistoryError, "missing required columns: currency"):
            validate_price_observations(frame)

    def test_price_observation_normalizes_dates(self) -> None:
        frame = pd.DataFrame([sample_price_observation()])

        normalized = normalize_price_observations(frame)

        self.assertEqual(normalized.loc[0, "snapshot_date"], pd.Timestamp("2026-06-30"))
        self.assertEqual(normalized.loc[0, "checkin"], pd.Timestamp("2026-07-15"))
        self.assertEqual(normalized.loc[0, "checkout"], pd.Timestamp("2026-07-19"))
        self.assertEqual(normalized.loc[0, "captured_at"], pd.Timestamp("2026-06-30T09:15:00"))

    def test_price_observation_rejects_bad_dates(self) -> None:
        invalid_date = pd.DataFrame([sample_price_observation(checkin="not-a-date")])
        with self.assertRaisesRegex(MovementHistoryError, "unparsable date"):
            validate_price_observations(invalid_date)

        invalid_window = pd.DataFrame(
            [sample_price_observation(checkin="2026-07-19", checkout="2026-07-19")]
        )
        with self.assertRaisesRegex(MovementHistoryError, "checkout must be after checkin"):
            validate_price_observations(invalid_window)

    def test_price_observation_requires_positive_prices(self) -> None:
        frame = pd.DataFrame([sample_price_observation(price_per_night=0)])

        with self.assertRaisesRegex(MovementHistoryError, "prices must be positive"):
            validate_price_observations(frame)

    def test_observation_dedupe_key_preserves_query_context(self) -> None:
        rows = [
            sample_price_observation(),
            sample_price_observation(),
            sample_price_observation(adults=3),
            sample_price_observation(currency="USD"),
            sample_price_observation(market="Rethymno"),
        ]
        deduped = pd.DataFrame(rows).drop_duplicates(subset=list(OBSERVATION_DEDUPE_KEY))

        for column in ["adults", "children", "rooms", "currency", "market"]:
            self.assertIn(column, OBSERVATION_DEDUPE_KEY)
        self.assertIn("room_id", OBSERVATION_DEDUPE_KEY)
        self.assertIn("block_id", OBSERVATION_DEDUPE_KEY)
        self.assertEqual(len(deduped), 4)


class OfferPresenceContractTests(unittest.TestCase):
    def test_presence_schema_lists_required_columns(self) -> None:
        self.assertIn("snapshot_date", OFFER_PRESENCE_COLUMNS)
        self.assertIn("property_url", OFFER_PRESENCE_COLUMNS)
        self.assertIn("checkin", OFFER_PRESENCE_COLUMNS)
        self.assertIn("availability_status", OFFER_PRESENCE_COLUMNS)
        self.assertIn("failure_reason", OFFER_PRESENCE_COLUMNS)

        frame = pd.DataFrame([sample_offer_presence()])
        validate_offer_presence(frame)

    def test_presence_accepts_all_v1_availability_statuses(self) -> None:
        frame = pd.DataFrame(
            [
                sample_offer_presence(availability_status=AVAILABILITY_STATUS_AVAILABLE),
                sample_offer_presence(availability_status=AVAILABILITY_STATUS_NO_OFFER),
                sample_offer_presence(
                    availability_status=AVAILABILITY_STATUS_FAILED,
                    failure_reason="timeout",
                ),
            ]
        )

        validate_offer_presence(frame)

    def test_presence_rejects_invalid_availability_status(self) -> None:
        frame = pd.DataFrame([sample_offer_presence(availability_status="sold_out")])

        with self.assertRaisesRegex(MovementHistoryError, "invalid availability_status"):
            validate_offer_presence(frame)

    def test_presence_normalizes_dates(self) -> None:
        frame = pd.DataFrame([sample_offer_presence()])

        normalized = normalize_offer_presence(frame)

        self.assertEqual(normalized.loc[0, "snapshot_date"], pd.Timestamp("2026-06-30"))
        self.assertEqual(normalized.loc[0, "checkin"], pd.Timestamp("2026-07-15"))
        self.assertEqual(normalized.loc[0, "checkout"], pd.Timestamp("2026-07-19"))
        self.assertEqual(normalized.loc[0, "captured_at"], pd.Timestamp("2026-06-30T09:15:00"))

    def test_presence_dedupe_key_preserves_query_context_without_offer_identity(self) -> None:
        rows = [
            sample_offer_presence(),
            sample_offer_presence(),
            sample_offer_presence(rooms=2),
            sample_offer_presence(currency="USD"),
            sample_offer_presence(market="Rethymno"),
        ]
        deduped = pd.DataFrame(rows).drop_duplicates(subset=list(PRESENCE_DEDUPE_KEY))

        for column in ["adults", "children", "rooms", "currency", "market"]:
            self.assertIn(column, PRESENCE_DEDUPE_KEY)
        self.assertNotIn("room_id", PRESENCE_DEDUPE_KEY)
        self.assertNotIn("block_id", PRESENCE_DEDUPE_KEY)
        self.assertEqual(len(deduped), 4)


if __name__ == "__main__":
    unittest.main()
