import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from scripts.append_price_observations import (
    append_history_from_run,
    append_offer_presence,
    append_price_observations,
    append_price_observations_from_run,
    build_offer_presence_from_run,
    build_price_observations_from_run,
)
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


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
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


def create_synthetic_run(run_dir: Path, *, captured_at: str, price: float) -> None:
    run_dir.mkdir(parents=True)
    write_jsonl(
        run_dir / "price_rows.jsonl",
        [
            {
                "property_name": "Apartment One",
                "property_url": "https://example.test/apartment-one",
                "checkin": "2026-07-15",
                "checkout": "2026-07-19",
                "lead_time_days": 15,
                "stay_length_days": 4,
                "room_id": "101",
                "room_name": "Sea View Studio",
                "block_id": "101_2026-07-15_2026-07-19",
                "occupancy_text": "2 adults",
                "conditions_text": "Free cancellation",
                "scarcity_text": None,
                "current_price_text": f"EUR {price}",
                "original_price_text": None,
                "current_price_value": price,
                "original_price_value": None,
                "price_per_night": price / 4,
                "quantity_options": ["0", "1"],
                "captured_at": captured_at,
            }
        ],
    )
    write_jsonl(
        run_dir / "room_inventory.jsonl",
        [
            {
                "property_name": "Apartment One",
                "property_url": "https://example.test/apartment-one",
                "room_id": "101",
                "room_name": "Sea View Studio",
                "captured_at": captured_at,
            }
        ],
    )
    write_jsonl(run_dir / "room_features.jsonl", [])
    write_jsonl(
        run_dir / "property_features.jsonl",
        [
            {
                "property_name": "Apartment One",
                "property_url": "https://example.test/apartment-one",
                "captured_at": captured_at,
                "property_type": "Apartment",
                "latitude": 35.515,
                "longitude": 24.018,
            }
        ],
    )
    write_jsonl(run_dir / "failures.jsonl", [])


def create_failure_run(
    run_dir: Path,
    *,
    captured_at: str,
    category: str,
    reason: str = "Synthetic failure.",
) -> None:
    run_dir.mkdir(parents=True)
    write_jsonl(run_dir / "price_rows.jsonl", [])
    write_jsonl(run_dir / "room_features.jsonl", [])
    write_jsonl(run_dir / "room_inventory.jsonl", [])
    write_jsonl(
        run_dir / "property_features.jsonl",
        [
            {
                "property_name": "Apartment One",
                "property_url": "https://example.test/apartment-one",
                "captured_at": captured_at,
                "property_type": "Apartment",
                "latitude": 35.515,
                "longitude": 24.018,
            }
        ],
    )
    write_jsonl(
        run_dir / "failures.jsonl",
        [
            {
                "property_name": "Apartment One",
                "property_url": "https://example.test/apartment-one",
                "scrape_stage": "price_rows",
                "category": category,
                "reason": reason,
                "requested_url": "https://example.test/apartment-one?checkin=2026-07-15",
                "final_url": "https://example.test/apartment-one",
                "checkin": "2026-07-15",
                "checkout": "2026-07-19",
                "lead_time_days": 15,
                "stay_length_days": 4,
                "status_code": 200,
                "snapshot_filename": None,
                "exception_type": None,
                "exception_message": None,
                "captured_at": captured_at,
            }
        ],
    )


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


class AppendPriceObservationsTests(unittest.TestCase):
    def test_build_observations_from_synthetic_run_uses_feature_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "20260630_091500_000000"
            create_synthetic_run(run_dir, captured_at="2026-06-30T09:15:00", price=500.0)

            frame = build_price_observations_from_run(run_dir)

        self.assertEqual(list(frame.columns), list(PRICE_OBSERVATION_COLUMNS))
        self.assertEqual(frame.shape, (1, len(PRICE_OBSERVATION_COLUMNS)))
        self.assertEqual(frame.loc[0, "snapshot_date"], pd.Timestamp("2026-06-30"))
        self.assertEqual(frame.loc[0, "run_id"], "20260630_091500_000000")
        self.assertEqual(frame.loc[0, "adults"], 2)
        self.assertEqual(frame.loc[0, "children"], 0)
        self.assertEqual(frame.loc[0, "rooms"], 1)
        self.assertEqual(frame.loc[0, "currency"], "EUR")
        self.assertEqual(frame.loc[0, "market"], "Chania")
        self.assertEqual(frame.loc[0, "property_type"], "Apartment")
        self.assertEqual(frame.loc[0, "price_per_night"], 125.0)

    def test_append_writes_parquet_and_dedupes_repeated_observations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "price_observations.parquet"
            frame = pd.DataFrame([sample_price_observation()])

            first = append_price_observations(frame, out_path)
            second = append_price_observations(frame, out_path)
            round_tripped = pd.read_parquet(out_path)

        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertEqual(round_tripped.shape, (1, len(PRICE_OBSERVATION_COLUMNS)))

    def test_append_keeps_distinct_query_context_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "price_observations.parquet"
            frame = pd.DataFrame(
                [
                    sample_price_observation(),
                    sample_price_observation(adults=3, current_price_value=600.0),
                    sample_price_observation(currency="USD", current_price_value=650.0),
                    sample_price_observation(market="Rethymno", current_price_value=700.0),
                ]
            )

            appended = append_price_observations(frame, out_path)

        self.assertEqual(len(appended), 4)
        self.assertEqual(set(appended["adults"]), {2, 3})
        self.assertEqual(set(appended["currency"]), {"EUR", "USD"})
        self.assertEqual(set(appended["market"]), {"Chania", "Rethymno"})

    def test_append_from_run_appends_second_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            first_run = tmp_path / "20260630_091500_000000"
            second_run = tmp_path / "20260701_091500_000000"
            out_path = tmp_path / "price_observations.parquet"
            create_synthetic_run(first_run, captured_at="2026-06-30T09:15:00", price=500.0)
            create_synthetic_run(second_run, captured_at="2026-07-01T09:15:00", price=540.0)

            append_price_observations_from_run(first_run, out_path)
            appended = append_price_observations_from_run(second_run, out_path)

        self.assertEqual(len(appended), 2)
        self.assertEqual(
            list(appended["snapshot_date"]),
            [pd.Timestamp("2026-06-30"), pd.Timestamp("2026-07-01")],
        )
        self.assertEqual(list(appended["price_per_night"]), [125.0, 135.0])


class AppendOfferPresenceTests(unittest.TestCase):
    def test_build_presence_from_available_run_collapses_price_rows_to_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "20260630_091500_000000"
            create_synthetic_run(run_dir, captured_at="2026-06-30T09:15:00", price=500.0)

            frame = build_offer_presence_from_run(run_dir)

        self.assertEqual(list(frame.columns), list(OFFER_PRESENCE_COLUMNS))
        self.assertEqual(frame.shape, (1, len(OFFER_PRESENCE_COLUMNS)))
        self.assertEqual(frame.loc[0, "availability_status"], AVAILABILITY_STATUS_AVAILABLE)
        self.assertIsNone(frame.loc[0, "failure_reason"])
        self.assertEqual(frame.loc[0, "property_type"], "Apartment")
        self.assertEqual(frame.loc[0, "snapshot_date"], pd.Timestamp("2026-06-30"))

    def test_build_presence_maps_empty_availability_failure_to_no_offer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "20260630_091500_000000"
            create_failure_run(
                run_dir,
                captured_at="2026-06-30T09:15:00",
                category="empty_availability",
                reason="No rooms available for this search.",
            )

            frame = build_offer_presence_from_run(run_dir)

        self.assertEqual(frame.shape, (1, len(OFFER_PRESENCE_COLUMNS)))
        self.assertEqual(frame.loc[0, "availability_status"], AVAILABILITY_STATUS_NO_OFFER)
        self.assertEqual(frame.loc[0, "failure_reason"], "No rooms available for this search.")

    def test_build_presence_maps_other_price_failures_to_scrape_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "20260630_091500_000000"
            create_failure_run(
                run_dir,
                captured_at="2026-06-30T09:15:00",
                category="selector_drift",
                reason="Price table selector changed.",
            )

            frame = build_offer_presence_from_run(run_dir)

        self.assertEqual(frame.loc[0, "availability_status"], AVAILABILITY_STATUS_FAILED)
        self.assertEqual(frame.loc[0, "failure_reason"], "Price table selector changed.")

    def test_build_presence_does_not_infer_missing_windows_from_absent_prices(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "20260630_091500_000000"
            create_synthetic_run(run_dir, captured_at="2026-06-30T09:15:00", price=500.0)

            frame = build_offer_presence_from_run(run_dir)

        self.assertEqual(len(frame), 1)
        self.assertEqual(set(frame["lead_time_days"]), {15})
        self.assertEqual(set(frame["stay_length_days"]), {4})

    def test_build_presence_prefers_available_over_duplicate_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "20260630_091500_000000"
            create_synthetic_run(run_dir, captured_at="2026-06-30T09:15:00", price=500.0)
            write_jsonl(
                run_dir / "failures.jsonl",
                [
                    {
                        "property_name": "Apartment One",
                        "property_url": "https://example.test/apartment-one",
                        "scrape_stage": "price_rows",
                        "category": "selector_drift",
                        "reason": "Should not override the available price rows.",
                        "requested_url": "https://example.test/apartment-one?checkin=2026-07-15",
                        "final_url": "https://example.test/apartment-one",
                        "checkin": "2026-07-15",
                        "checkout": "2026-07-19",
                        "lead_time_days": 15,
                        "stay_length_days": 4,
                        "status_code": 200,
                        "snapshot_filename": None,
                        "exception_type": None,
                        "exception_message": None,
                        "captured_at": "2026-06-30T09:16:00",
                    }
                ],
            )

            frame = build_offer_presence_from_run(run_dir)

        self.assertEqual(len(frame), 1)
        self.assertEqual(frame.loc[0, "availability_status"], AVAILABILITY_STATUS_AVAILABLE)

    def test_append_offer_presence_writes_parquet_and_dedupes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "offer_presence.parquet"
            frame = pd.DataFrame([sample_offer_presence()])

            first = append_offer_presence(frame, out_path)
            second = append_offer_presence(frame, out_path)
            round_tripped = pd.read_parquet(out_path)

        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertEqual(round_tripped.shape, (1, len(OFFER_PRESENCE_COLUMNS)))

    def test_append_history_from_run_writes_observations_and_presence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run_dir = tmp_path / "20260630_091500_000000"
            observations_out = tmp_path / "price_observations.parquet"
            presence_out = tmp_path / "offer_presence.parquet"
            create_synthetic_run(run_dir, captured_at="2026-06-30T09:15:00", price=500.0)

            observations, presence = append_history_from_run(
                run_dir,
                observations_out,
                presence_out,
            )
            observation_rows = pd.read_parquet(observations_out).shape[0]
            presence_rows = pd.read_parquet(presence_out).shape[0]

        self.assertEqual(len(observations), 1)
        self.assertEqual(len(presence), 1)
        self.assertEqual(observation_rows, 1)
        self.assertEqual(presence_rows, 1)

    def test_append_history_from_failure_only_run_records_presence_without_prices(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run_dir = tmp_path / "20260630_091500_000000"
            observations_out = tmp_path / "price_observations.parquet"
            presence_out = tmp_path / "offer_presence.parquet"
            create_failure_run(
                run_dir,
                captured_at="2026-06-30T09:15:00",
                category="empty_availability",
            )

            observations, presence = append_history_from_run(
                run_dir,
                observations_out,
                presence_out,
            )
            observation_rows = pd.read_parquet(observations_out).shape[0]
            status = pd.read_parquet(presence_out).loc[0, "availability_status"]

        self.assertEqual(len(observations), 0)
        self.assertEqual(len(presence), 1)
        self.assertEqual(observation_rows, 0)
        self.assertEqual(status, AVAILABILITY_STATUS_NO_OFFER)


if __name__ == "__main__":
    unittest.main()
