import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from scripts.export_modelling_table import (
    export_combined_modelling_table,
    export_modelling_table,
)


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


class ExportModellingTableTests(unittest.TestCase):
    def _write_minimal_run(
        self,
        run_dir: Path,
        rows: list[dict],
    ) -> None:
        run_dir.mkdir()
        write_jsonl(run_dir / "price_rows.jsonl", rows)
        write_jsonl(run_dir / "room_features.jsonl", [])
        write_jsonl(run_dir / "property_features.jsonl", [])
        write_jsonl(run_dir / "room_inventory.jsonl", [])

    def test_export_round_trips_nested_columns_through_parquet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run_dir = tmp_path / "run"
            run_dir.mkdir()

            write_jsonl(
                run_dir / "price_rows.jsonl",
                [
                    {
                        "property_name": "Apartment One",
                        "property_url": "https://example.test/apartment-one",
                        "checkin": "2026-07-15",
                        "checkout": "2026-07-19",
                        "lead_time_days": 7,
                        "stay_length_days": 4,
                        "room_id": "101",
                        "room_name": "Sea View Suite",
                        "conditions_text": "Breakfast included",
                        "current_price_value": 400.0,
                        "price_per_night": 100.0,
                        "quantity_options": [{"rooms": 1, "price": 400.0}],
                        "captured_at": "2026-06-25T10:00:00",
                    }
                ],
            )
            write_jsonl(
                run_dir / "room_features.jsonl",
                [
                    {
                        "property_name": "Apartment One",
                        "property_url": "https://example.test/apartment-one",
                        "captured_at": "2026-06-25T10:00:00",
                        "room_id": "101",
                        "room_size_sqm": 45.0,
                        "bed_types": [{"bed_type": "double", "count": 1}],
                        "amenities": ["Air conditioning", "Balcony"],
                    }
                ],
            )
            write_jsonl(
                run_dir / "property_features.jsonl",
                [
                    {
                        "property_name": "Apartment One",
                        "property_url": "https://example.test/apartment-one",
                        "captured_at": "2026-06-25T10:00:00",
                        "review_subscores": {"cleanliness": 9.2},
                        "property_facilities": ["Parking"],
                        "nearby_poi": [{"name": "Old Harbour", "distance_km": 0.4}],
                        "house_rules": ["No smoking"],
                        "languages_spoken": ["English", "Greek"],
                    }
                ],
            )
            write_jsonl(
                run_dir / "room_inventory.jsonl",
                [
                    {
                        "property_url": "https://example.test/apartment-one",
                        "room_name": "Sea View Suite",
                        "room_id": "101",
                    }
                ],
            )

            out_path = tmp_path / "modelling_table.parquet"
            frame, encoded_columns = export_modelling_table(run_dir, out_path)
            round_tripped = pd.read_parquet(out_path)

            self.assertEqual(frame.shape[0], 1)
            self.assertEqual(round_tripped.shape[0], 1)
            self.assertEqual(round_tripped.loc[0, "price_per_night"], 100.0)
            self.assertEqual(round_tripped.loc[0, "meal_plan"], "breakfast")
            self.assertFalse(round_tripped.loc[0, "room_id_reconciled"])

            expected_encoded = {
                "quantity_options",
                "bed_types",
                "amenities",
                "review_subscores",
                "property_facilities",
                "nearby_poi",
                "house_rules",
                "languages_spoken",
            }
            self.assertEqual(set(encoded_columns), expected_encoded)
            self.assertEqual(
                json.loads(round_tripped.loc[0, "quantity_options"]),
                [{"price": 400.0, "rooms": 1}],
            )
            self.assertEqual(
                json.loads(round_tripped.loc[0, "bed_types"]),
                [{"bed_type": "double", "count": 1}],
            )
            self.assertEqual(
                json.loads(round_tripped.loc[0, "review_subscores"]),
                {"cleanliness": 9.2},
            )
            self.assertEqual(
                json.loads(round_tripped.loc[0, "nearby_poi"]),
                [{"distance_km": 0.4, "name": "Old Harbour"}],
            )

    def test_combined_export_prefers_later_run_for_same_property(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            base = tmp_path / "base"
            retry = tmp_path / "retry"
            self._write_minimal_run(
                base,
                [
                    {
                        "property_name": "Subject",
                        "property_url": "https://example.test/subject",
                        "checkin": "2026-07-15",
                        "checkout": "2026-07-19",
                        "lead_time_days": 7,
                        "stay_length_days": 4,
                        "room_id": "101",
                        "room_name": "Base Room",
                        "conditions_text": "",
                        "current_price_value": 400.0,
                        "price_per_night": 100.0,
                    },
                    {
                        "property_name": "Other",
                        "property_url": "https://example.test/other",
                        "checkin": "2026-07-15",
                        "checkout": "2026-07-19",
                        "lead_time_days": 7,
                        "stay_length_days": 4,
                        "room_id": "201",
                        "room_name": "Other Room",
                        "conditions_text": "",
                        "current_price_value": 800.0,
                        "price_per_night": 200.0,
                    },
                ],
            )
            self._write_minimal_run(
                retry,
                [
                    {
                        "property_name": "Subject",
                        "property_url": "https://example.test/subject",
                        "checkin": "2026-07-15",
                        "checkout": "2026-07-19",
                        "lead_time_days": 7,
                        "stay_length_days": 4,
                        "room_id": "101",
                        "room_name": "Retry Room",
                        "conditions_text": "",
                        "current_price_value": 360.0,
                        "price_per_night": 90.0,
                    }
                ],
            )

            out_path = tmp_path / "combined.parquet"
            frame, _ = export_combined_modelling_table([base, retry], out_path)
            round_tripped = pd.read_parquet(out_path)

            self.assertEqual(frame.shape[0], 2)
            self.assertEqual(round_tripped.shape[0], 2)
            by_url = round_tripped.set_index("property_url")
            self.assertEqual(
                by_url.loc["https://example.test/subject", "price_per_night"],
                90.0,
            )
            self.assertEqual(
                by_url.loc["https://example.test/other", "price_per_night"],
                200.0,
            )


if __name__ == "__main__":
    unittest.main()
