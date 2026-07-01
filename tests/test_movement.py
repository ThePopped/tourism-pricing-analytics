import tempfile
import unittest
from pathlib import Path

import pandas as pd

from tests.test_price_observations import sample_offer_presence, sample_price_observation
from tourism_pricing_analytics.analysis.movement import (
    COVARIATE_STATUS_LOADED,
    COVARIATE_STATUS_MISSING,
    DEMAND_COVARIATE_COLUMNS,
    HISTORY_STATUS_LOW_HISTORY,
    HISTORY_STATUS_MISSING,
    HISTORY_STATUS_READY,
    MOVEMENT_STATUS_AVAILABLE,
    MOVEMENT_STATUS_DISAPPEARED,
    MOVEMENT_STATUS_NEWLY_AVAILABLE,
    MOVEMENT_STATUS_STILL_UNAVAILABLE,
    MOVEMENT_STATUS_UNKNOWN,
    OFFER_PRESENCE_COLUMNS,
    PRICE_OBSERVATION_COLUMNS,
    MovementHistoryError,
    build_peer_market_movement_table,
    build_price_movement_table,
    load_demand_covariates,
    load_offer_presence,
    load_price_observations,
    movement_history_status,
    normalize_demand_covariates,
    validate_demand_covariates,
)


class MovementHistoryLoaderTests(unittest.TestCase):
    def test_missing_price_observations_returns_empty_low_history_frame(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "price_observations.parquet"

            frame = load_price_observations(missing)

        self.assertTrue(frame.empty)
        self.assertEqual(frame.attrs["history_status"], HISTORY_STATUS_MISSING)
        self.assertEqual(frame.attrs["low_history"]["status"], HISTORY_STATUS_MISSING)
        self.assertTrue(frame.attrs["low_history"]["is_low_history"])
        self.assertIn("snapshot_date", frame.columns)

    def test_missing_offer_presence_returns_empty_low_history_frame(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "offer_presence.parquet"

            frame = load_offer_presence(missing)

        self.assertTrue(frame.empty)
        self.assertEqual(frame.attrs["history_status"], HISTORY_STATUS_MISSING)
        self.assertEqual(frame.attrs["low_history"]["status"], HISTORY_STATUS_MISSING)
        self.assertIn("availability_status", frame.columns)

    def test_load_price_observations_validates_existing_parquet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "price_observations.parquet"
            pd.DataFrame([sample_price_observation(price_per_night=-1)]).to_parquet(
                path,
                index=False,
            )

            with self.assertRaisesRegex(MovementHistoryError, "prices must be positive"):
                load_price_observations(path)

    def test_load_price_observations_normalizes_dates_and_reports_one_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "price_observations.parquet"
            pd.DataFrame([sample_price_observation()]).to_parquet(path, index=False)

            frame = load_price_observations(path)

        self.assertEqual(frame.loc[0, "snapshot_date"], pd.Timestamp("2026-06-30"))
        self.assertEqual(frame.attrs["low_history"]["status"], HISTORY_STATUS_LOW_HISTORY)
        self.assertEqual(frame.attrs["low_history"]["snapshot_count"], 1)

    def test_movement_history_status_is_ready_with_two_snapshots(self) -> None:
        observations = pd.DataFrame(
            [
                sample_price_observation(snapshot_date="2026-06-30"),
                sample_price_observation(
                    snapshot_date="2026-07-01",
                    run_id="20260701_091500_000000",
                    price_per_night=135.0,
                    current_price_value=540.0,
                ),
            ]
        )
        observations = load_price_observations_from_frame_for_test(observations)

        status = movement_history_status(observations)

        self.assertEqual(status["status"], HISTORY_STATUS_READY)
        self.assertFalse(status["is_low_history"])
        self.assertEqual(status["snapshot_count"], 2)

    def test_movement_history_status_counts_presence_snapshots_too(self) -> None:
        observations = load_price_observations_from_frame_for_test(
            pd.DataFrame([sample_price_observation(snapshot_date="2026-06-30")])
        )
        presence = load_offer_presence_from_frame_for_test(
            pd.DataFrame(
                [
                    sample_offer_presence(snapshot_date="2026-06-30"),
                    sample_offer_presence(
                        snapshot_date="2026-07-01",
                        run_id="20260701_091500_000000",
                    ),
                ]
            )
        )

        status = movement_history_status(observations, presence)

        self.assertEqual(status["status"], HISTORY_STATUS_READY)
        self.assertEqual(status["snapshot_count"], 2)


def load_price_observations_from_frame_for_test(frame: pd.DataFrame) -> pd.DataFrame:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "price_observations.parquet"
        frame.to_parquet(path, index=False)
        return load_price_observations(path)


def load_offer_presence_from_frame_for_test(frame: pd.DataFrame) -> pd.DataFrame:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "offer_presence.parquet"
        frame.to_parquet(path, index=False)
        return load_offer_presence(path)


class DemandCovariateLoaderTests(unittest.TestCase):
    def test_missing_covariates_csv_is_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "demand_covariates.csv"

            frame = load_demand_covariates(missing)

        self.assertTrue(frame.empty)
        self.assertEqual(list(frame.columns), list(DEMAND_COVARIATE_COLUMNS))
        self.assertEqual(frame.attrs["covariate_status"], COVARIATE_STATUS_MISSING)

    def test_valid_covariates_parse_dates_numbers_flags_and_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "demand_covariates.csv"
            pd.DataFrame(
                [
                    {
                        "date": "2026-06-30",
                        "checkin": "2026-07-15",
                        "market": "Chania",
                        "google_trends_index": "72",
                        "holiday_flag": "yes",
                        "event_flag": "0",
                        "weather_temp_c": "29.5",
                        "weather_rain_mm": "",
                        "notes": None,
                    }
                ],
                columns=DEMAND_COVARIATE_COLUMNS,
            ).to_csv(path, index=False)

            frame = load_demand_covariates(path)

        self.assertEqual(frame.attrs["covariate_status"], COVARIATE_STATUS_LOADED)
        self.assertEqual(frame.loc[0, "date"], pd.Timestamp("2026-06-30"))
        self.assertEqual(frame.loc[0, "checkin"], pd.Timestamp("2026-07-15"))
        self.assertEqual(frame.loc[0, "google_trends_index"], 72)
        self.assertTrue(frame.loc[0, "holiday_flag"])
        self.assertFalse(frame.loc[0, "event_flag"])
        self.assertTrue(pd.isna(frame.loc[0, "weather_rain_mm"]))
        self.assertEqual(frame.loc[0, "notes"], "")

    def test_covariates_require_full_schema_and_valid_dates(self) -> None:
        missing_column = pd.DataFrame(
            [
                {
                    "date": "2026-06-30",
                    "checkin": "2026-07-15",
                    "market": "Chania",
                }
            ]
        )
        with self.assertRaisesRegex(MovementHistoryError, "missing required columns"):
            validate_demand_covariates(missing_column)

        bad_date = pd.DataFrame(
            [
                {
                    "date": "not-a-date",
                    "checkin": "2026-07-15",
                    "market": "Chania",
                    "google_trends_index": 72,
                    "holiday_flag": False,
                    "event_flag": False,
                    "weather_temp_c": 29.5,
                    "weather_rain_mm": 0.0,
                    "notes": "",
                }
            ],
            columns=DEMAND_COVARIATE_COLUMNS,
        )
        with self.assertRaisesRegex(MovementHistoryError, "unparsable date"):
            normalize_demand_covariates(bad_date)


class SnapshotComparisonCoreTests(unittest.TestCase):
    def test_available_snapshots_compute_median_price_delta(self) -> None:
        observations = pd.DataFrame(
            [
                sample_price_observation(
                    snapshot_date="2026-06-30",
                    price_per_night=100.0,
                    current_price_value=400.0,
                ),
                sample_price_observation(
                    snapshot_date="2026-06-30",
                    room_id="102",
                    room_name="Garden Studio",
                    block_id="102_2026-07-15_2026-07-19",
                    price_per_night=140.0,
                    current_price_value=560.0,
                ),
                sample_price_observation(
                    snapshot_date="2026-07-01",
                    captured_at="2026-07-01T09:15:00",
                    run_id="20260701_091500_000000",
                    lead_time_days=14,
                    price_per_night=110.0,
                    current_price_value=440.0,
                ),
                sample_price_observation(
                    snapshot_date="2026-07-01",
                    captured_at="2026-07-01T09:15:00",
                    run_id="20260701_091500_000000",
                    room_id="102",
                    room_name="Garden Studio",
                    block_id="102_2026-07-15_2026-07-19",
                    lead_time_days=14,
                    price_per_night=150.0,
                    current_price_value=600.0,
                ),
            ]
        )
        presence = pd.DataFrame(
            [
                sample_offer_presence(snapshot_date="2026-06-30"),
                sample_offer_presence(
                    snapshot_date="2026-07-01",
                    captured_at="2026-07-01T09:15:00",
                    run_id="20260701_091500_000000",
                    lead_time_days=14,
                ),
            ]
        )

        movement = build_price_movement_table(
            observations,
            presence,
            subject_url="https://example.test/apartment-one",
            windows=None,
            peer_property_urls=[],
        )

        current = movement.loc[movement["snapshot_date"].eq(pd.Timestamp("2026-07-01"))].iloc[0]
        self.assertEqual(current["previous_snapshot_date"], pd.Timestamp("2026-06-30"))
        self.assertEqual(current["availability_state"], MOVEMENT_STATUS_AVAILABLE)
        self.assertEqual(current["previous_lead_time_days"], 15)
        self.assertEqual(current["lead_time_days"], 14)
        self.assertEqual(current["current_price_per_night"], 130.0)
        self.assertEqual(current["previous_price_per_night"], 120.0)
        self.assertEqual(current["price_change_eur"], 10.0)
        self.assertAlmostEqual(current["price_change_pct"], 10.0 / 120.0)
        self.assertEqual(current["current_offer_count"], 2)
        self.assertEqual(current["previous_offer_count"], 2)
        self.assertTrue(current["is_subject"])

    def test_observations_can_supply_available_presence_when_presence_is_absent(self) -> None:
        observations = pd.DataFrame(
            [
                sample_price_observation(snapshot_date="2026-06-30"),
                sample_price_observation(
                    snapshot_date="2026-07-01",
                    captured_at="2026-07-01T09:15:00",
                    run_id="20260701_091500_000000",
                    lead_time_days=14,
                    price_per_night=135.0,
                    current_price_value=540.0,
                ),
            ]
        )
        presence = pd.DataFrame(columns=OFFER_PRESENCE_COLUMNS)

        movement = build_price_movement_table(
            observations,
            presence,
            subject_url="https://example.test/apartment-one",
            windows=None,
            peer_property_urls=[],
        )

        current = movement.loc[movement["snapshot_date"].eq(pd.Timestamp("2026-07-01"))].iloc[0]
        self.assertEqual(current["availability_state"], MOVEMENT_STATUS_AVAILABLE)
        self.assertEqual(current["price_change_eur"], 10.0)

    def test_availability_transitions_are_classified(self) -> None:
        observations = pd.DataFrame(
            [
                sample_price_observation(
                    property_url="available",
                    property_name="Available Stay",
                    price_per_night=100.0,
                    current_price_value=400.0,
                ),
                sample_price_observation(
                    property_url="available",
                    property_name="Available Stay",
                    snapshot_date="2026-07-01",
                    captured_at="2026-07-01T09:15:00",
                    run_id="20260701_091500_000000",
                    lead_time_days=14,
                    price_per_night=120.0,
                    current_price_value=480.0,
                ),
                sample_price_observation(
                    property_url="new",
                    property_name="New Stay",
                    snapshot_date="2026-07-01",
                    captured_at="2026-07-01T09:15:00",
                    run_id="20260701_091500_000000",
                    lead_time_days=14,
                    price_per_night=130.0,
                    current_price_value=520.0,
                ),
                sample_price_observation(
                    property_url="gone",
                    property_name="Gone Stay",
                    price_per_night=140.0,
                    current_price_value=560.0,
                ),
            ]
        )
        presence = pd.DataFrame(
            [
                sample_offer_presence(property_url="available", property_name="Available Stay"),
                sample_offer_presence(
                    property_url="available",
                    property_name="Available Stay",
                    snapshot_date="2026-07-01",
                    captured_at="2026-07-01T09:15:00",
                    run_id="20260701_091500_000000",
                    lead_time_days=14,
                ),
                sample_offer_presence(
                    property_url="new",
                    property_name="New Stay",
                    availability_status="no_available_offer",
                ),
                sample_offer_presence(
                    property_url="new",
                    property_name="New Stay",
                    snapshot_date="2026-07-01",
                    captured_at="2026-07-01T09:15:00",
                    run_id="20260701_091500_000000",
                    lead_time_days=14,
                ),
                sample_offer_presence(property_url="gone", property_name="Gone Stay"),
                sample_offer_presence(
                    property_url="gone",
                    property_name="Gone Stay",
                    snapshot_date="2026-07-01",
                    captured_at="2026-07-01T09:15:00",
                    run_id="20260701_091500_000000",
                    lead_time_days=14,
                    availability_status="no_available_offer",
                ),
                sample_offer_presence(
                    property_url="still",
                    property_name="Still Unavailable Stay",
                    availability_status="no_available_offer",
                ),
                sample_offer_presence(
                    property_url="still",
                    property_name="Still Unavailable Stay",
                    snapshot_date="2026-07-01",
                    captured_at="2026-07-01T09:15:00",
                    run_id="20260701_091500_000000",
                    lead_time_days=14,
                    availability_status="no_available_offer",
                ),
                sample_offer_presence(
                    property_url="failed",
                    property_name="Failed Stay",
                    availability_status="scrape_failed",
                    failure_reason="timeout",
                ),
                sample_offer_presence(
                    property_url="failed",
                    property_name="Failed Stay",
                    snapshot_date="2026-07-01",
                    captured_at="2026-07-01T09:15:00",
                    run_id="20260701_091500_000000",
                    lead_time_days=14,
                ),
            ]
        )

        movement = build_price_movement_table(
            observations,
            presence,
            subject_url="available",
            windows=[{"stay_length_days": 4}],
            peer_property_urls=["new", "gone", "still", "failed"],
        )
        latest = movement.loc[movement["snapshot_date"].eq(pd.Timestamp("2026-07-01"))]
        states = dict(zip(latest["property_url"], latest["availability_state"], strict=True))

        self.assertEqual(states["available"], MOVEMENT_STATUS_AVAILABLE)
        self.assertEqual(states["new"], MOVEMENT_STATUS_NEWLY_AVAILABLE)
        self.assertEqual(states["gone"], MOVEMENT_STATUS_DISAPPEARED)
        self.assertEqual(states["still"], MOVEMENT_STATUS_STILL_UNAVAILABLE)
        self.assertEqual(states["failed"], MOVEMENT_STATUS_UNKNOWN)
        gone = latest.loc[latest["property_url"].eq("gone")].iloc[0]
        self.assertTrue(pd.isna(gone["current_price_per_night"]))
        self.assertTrue(pd.isna(gone["price_change_eur"]))

    def test_previous_snapshot_respects_query_context_identity(self) -> None:
        observations = pd.DataFrame(
            [
                sample_price_observation(snapshot_date="2026-06-30", adults=3),
                sample_price_observation(
                    snapshot_date="2026-07-01",
                    captured_at="2026-07-01T09:15:00",
                    run_id="20260701_091500_000000",
                    lead_time_days=14,
                    price_per_night=135.0,
                    current_price_value=540.0,
                ),
            ]
        )
        presence = pd.DataFrame(
            [
                sample_offer_presence(snapshot_date="2026-06-30", adults=3),
                sample_offer_presence(
                    snapshot_date="2026-07-01",
                    captured_at="2026-07-01T09:15:00",
                    run_id="20260701_091500_000000",
                    lead_time_days=14,
                ),
            ]
        )

        movement = build_price_movement_table(
            observations,
            presence,
            subject_url="https://example.test/apartment-one",
            windows=None,
            peer_property_urls=[],
        )

        two_adult_row = movement.loc[movement["adults"].eq(2)].iloc[0]
        self.assertEqual(two_adult_row["availability_state"], MOVEMENT_STATUS_UNKNOWN)
        self.assertTrue(pd.isna(two_adult_row["previous_snapshot_date"]))

    def test_empty_history_returns_empty_low_history_movement_table(self) -> None:
        movement = build_price_movement_table(
            pd.DataFrame(columns=PRICE_OBSERVATION_COLUMNS),
            pd.DataFrame(columns=OFFER_PRESENCE_COLUMNS),
            subject_url="https://example.test/apartment-one",
            windows=None,
            peer_property_urls=[],
        )

        self.assertTrue(movement.empty)
        self.assertEqual(movement.attrs["low_history"]["status"], HISTORY_STATUS_LOW_HISTORY)


class PeerMarketMovementTests(unittest.TestCase):
    def test_peer_market_medians_are_property_weighted_and_ranks_move(self) -> None:
        observations = pd.DataFrame(
            [
                _movement_observation("subject", "Subject Stay", "2026-06-30", 450.0, 35.500),
                _movement_observation("subject", "Subject Stay", "2026-07-01", 1050.0, 35.500),
                _movement_observation("peer_multi", "Many Room Peer", "2026-06-30", 80.0, 35.501, room_id="m1"),
                _movement_observation("peer_multi", "Many Room Peer", "2026-06-30", 80.0, 35.501, room_id="m2"),
                _movement_observation("peer_multi", "Many Room Peer", "2026-06-30", 80.0, 35.501, room_id="m3"),
                _movement_observation("peer_multi", "Many Room Peer", "2026-06-30", 80.0, 35.501, room_id="m4"),
                _movement_observation("peer_multi", "Many Room Peer", "2026-06-30", 80.0, 35.501, room_id="m5"),
                _movement_observation("peer_multi", "Many Room Peer", "2026-07-01", 100.0, 35.501, room_id="m1"),
                _movement_observation("peer_multi", "Many Room Peer", "2026-07-01", 100.0, 35.501, room_id="m2"),
                _movement_observation("peer_multi", "Many Room Peer", "2026-07-01", 100.0, 35.501, room_id="m3"),
                _movement_observation("peer_multi", "Many Room Peer", "2026-07-01", 100.0, 35.501, room_id="m4"),
                _movement_observation("peer_multi", "Many Room Peer", "2026-07-01", 100.0, 35.501, room_id="m5"),
                _movement_observation("peer_high", "High Peer", "2026-06-30", 900.0, 35.502),
                _movement_observation("peer_high", "High Peer", "2026-07-01", 1000.0, 35.502),
            ]
        )
        presence = pd.DataFrame(
            [
                _movement_presence("subject", "Subject Stay", "2026-06-30", 35.500),
                _movement_presence("subject", "Subject Stay", "2026-07-01", 35.500),
                _movement_presence("peer_multi", "Many Room Peer", "2026-06-30", 35.501),
                _movement_presence("peer_multi", "Many Room Peer", "2026-07-01", 35.501),
                _movement_presence("peer_high", "High Peer", "2026-06-30", 35.502),
                _movement_presence("peer_high", "High Peer", "2026-07-01", 35.502),
            ]
        )

        movement = build_peer_market_movement_table(
            observations,
            presence,
            observations,
            subject_url="subject",
            windows=[{"checkin": "2026-07-15", "stay_length_days": 4}],
            max_peers=2,
            w_geo=1.0,
            w_sim=0.0,
            max_distance_km=5.0,
        )

        latest_subject = movement.loc[
            movement["snapshot_date"].eq(pd.Timestamp("2026-07-01"))
            & movement["property_url"].eq("subject")
        ].iloc[0]
        self.assertEqual(movement.attrs["peer_property_urls"], ["peer_multi", "peer_high"])
        self.assertEqual(latest_subject["peer_property_count"], 2)
        self.assertEqual(latest_subject["current_peer_median_price_per_night"], 550.0)
        self.assertEqual(latest_subject["previous_peer_median_price_per_night"], 490.0)
        self.assertEqual(latest_subject["peer_median_change_eur"], 60.0)
        self.assertAlmostEqual(latest_subject["peer_median_change_pct"], 60.0 / 490.0)
        self.assertEqual(latest_subject["current_price_rank"], 1.0)
        self.assertEqual(latest_subject["previous_price_rank"], 2.0)
        self.assertEqual(latest_subject["price_rank_change"], 1.0)
        self.assertEqual(latest_subject["price_gap_to_peer_median"], 500.0)


def _movement_observation(
    property_url: str,
    property_name: str,
    snapshot_date: str,
    price_per_night: float,
    latitude: float,
    *,
    room_id: str = "101",
) -> dict[str, object]:
    date = pd.Timestamp(snapshot_date)
    lead_time_days = (pd.Timestamp("2026-07-15") - date).days
    return sample_price_observation(
        snapshot_date=snapshot_date,
        captured_at=f"{snapshot_date}T09:15:00",
        run_id=f"{date.strftime('%Y%m%d')}_091500_000000",
        property_url=property_url,
        property_name=property_name,
        room_id=room_id,
        room_name=f"Room {room_id}",
        block_id=f"{room_id}_2026-07-15_2026-07-19",
        lead_time_days=lead_time_days,
        price_per_night=price_per_night,
        current_price_value=price_per_night * 4,
        latitude=latitude,
    )


def _movement_presence(
    property_url: str,
    property_name: str,
    snapshot_date: str,
    latitude: float,
) -> dict[str, object]:
    date = pd.Timestamp(snapshot_date)
    return sample_offer_presence(
        snapshot_date=snapshot_date,
        captured_at=f"{snapshot_date}T09:15:00",
        run_id=f"{date.strftime('%Y%m%d')}_091500_000000",
        property_url=property_url,
        property_name=property_name,
        lead_time_days=(pd.Timestamp("2026-07-15") - date).days,
        latitude=latitude,
    )


if __name__ == "__main__":
    unittest.main()
