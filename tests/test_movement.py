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
    MovementHistoryError,
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


if __name__ == "__main__":
    unittest.main()
