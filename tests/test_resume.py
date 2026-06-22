import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tourism_pricing_analytics.scraping.booking.models import PropertyTarget
from tourism_pricing_analytics.scraping.booking.resume import (
    expected_price_windows,
    expected_property_dir,
    is_property_complete,
    pending_targets,
)


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(f"{json.dumps(record)}\n" for record in records)
    path.write_text(content, encoding="utf-8")


def _inventory_record(target: PropertyTarget) -> dict:
    return {
        "property_name": target.name,
        "property_url": target.url,
        "room_id": "12345601",
        "room_name": "Double Room",
        "captured_at": "2026-06-22T12:00:00",
    }


def _price_record(target: PropertyTarget, lead_time_days: int, stay_length_days: int) -> dict:
    return {
        "property_name": target.name,
        "property_url": target.url,
        "checkin": "2026-07-01",
        "checkout": "2026-07-05",
        "lead_time_days": lead_time_days,
        "stay_length_days": stay_length_days,
        "room_id": "12345601",
        "room_name": "Double Room",
        "block_id": "12345601_1_0_0",
        "occupancy_text": None,
        "conditions_text": None,
        "scarcity_text": None,
        "current_price_text": "EUR 400",
        "original_price_text": None,
        "current_price_value": 400.0,
        "original_price_value": None,
        "price_per_night": 100.0,
        "quantity_options": ["0", "1"],
        "captured_at": "2026-06-22T12:00:00",
    }


def _failure_record(
    target: PropertyTarget,
    *,
    category: str,
    scrape_stage: str = "price_rows",
    lead_time_days: int | None = 7,
    stay_length_days: int | None = 4,
) -> dict:
    return {
        "property_name": target.name,
        "property_url": target.url,
        "scrape_stage": scrape_stage,
        "category": category,
        "reason": "Synthetic failure.",
        "requested_url": target.url,
        "final_url": target.url,
        "checkin": "2026-07-01" if scrape_stage == "price_rows" else None,
        "checkout": "2026-07-05" if scrape_stage == "price_rows" else None,
        "lead_time_days": lead_time_days,
        "stay_length_days": stay_length_days,
        "status_code": 200,
        "snapshot_filename": None,
        "exception_type": None,
        "exception_message": None,
        "captured_at": "2026-06-22T12:00:00",
    }


class ResumeHelpersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.target = PropertyTarget(
            name="Example Hotel",
            url="https://www.booking.com/hotel/gr/example.en-gb.html",
        )
        self.other_target = PropertyTarget(
            name="Other Hotel",
            url="https://www.booking.com/hotel/gr/other.en-gb.html",
        )

    def test_expected_property_dir_matches_runner_naming(self) -> None:
        run_dir = Path("saved_dom/runs/example")

        path = expected_property_dir(run_dir, 12, self.target)

        self.assertEqual(path, run_dir / "012_example_hotel")

    def test_expected_price_windows_returns_full_matrix(self) -> None:
        self.assertEqual(
            expected_price_windows([7, 30], [4, 7]),
            {(7, 4), (7, 7), (30, 4), (30, 7)},
        )

    def test_missing_property_directory_is_not_complete(self) -> None:
        with TemporaryDirectory() as tmp:
            self.assertFalse(
                is_property_complete(Path(tmp), 1, self.target, [7], [4])
            )

    def test_directory_only_is_not_complete(self) -> None:
        with TemporaryDirectory() as tmp:
            property_dir = expected_property_dir(Path(tmp), 1, self.target)
            property_dir.mkdir(parents=True)

            self.assertFalse(
                is_property_complete(Path(tmp), 1, self.target, [7], [4])
            )

    def test_inventory_only_is_not_complete(self) -> None:
        with TemporaryDirectory() as tmp:
            property_dir = expected_property_dir(Path(tmp), 1, self.target)
            _write_jsonl(property_dir / "room_inventory.jsonl", [_inventory_record(self.target)])

            self.assertFalse(
                is_property_complete(Path(tmp), 1, self.target, [7], [4])
            )

    def test_successful_price_rows_complete_property(self) -> None:
        with TemporaryDirectory() as tmp:
            property_dir = expected_property_dir(Path(tmp), 1, self.target)
            _write_jsonl(property_dir / "room_inventory.jsonl", [_inventory_record(self.target)])
            _write_jsonl(
                property_dir / "price_rows.jsonl",
                [
                    _price_record(self.target, 7, 4),
                    _price_record(self.target, 7, 7),
                ],
            )

            self.assertTrue(
                is_property_complete(Path(tmp), 1, self.target, [7], [4, 7])
            )

    def test_all_empty_availability_windows_complete_sold_out_property(self) -> None:
        with TemporaryDirectory() as tmp:
            property_dir = expected_property_dir(Path(tmp), 1, self.target)
            _write_jsonl(property_dir / "room_inventory.jsonl", [_inventory_record(self.target)])
            _write_jsonl(
                property_dir / "failures.jsonl",
                [
                    _failure_record(
                        self.target,
                        category="empty_availability",
                        lead_time_days=7,
                        stay_length_days=4,
                    ),
                    _failure_record(
                        self.target,
                        category="empty_availability",
                        lead_time_days=7,
                        stay_length_days=7,
                    ),
                ],
            )

            self.assertTrue(
                is_property_complete(Path(tmp), 1, self.target, [7], [4, 7])
            )

    def test_partial_price_windows_are_pending(self) -> None:
        with TemporaryDirectory() as tmp:
            property_dir = expected_property_dir(Path(tmp), 1, self.target)
            _write_jsonl(property_dir / "room_inventory.jsonl", [_inventory_record(self.target)])
            _write_jsonl(
                property_dir / "price_rows.jsonl",
                [_price_record(self.target, 7, 4)],
            )

            self.assertFalse(
                is_property_complete(Path(tmp), 1, self.target, [7], [4, 7])
            )

    def test_transient_failure_window_is_pending(self) -> None:
        with TemporaryDirectory() as tmp:
            property_dir = expected_property_dir(Path(tmp), 1, self.target)
            _write_jsonl(property_dir / "room_inventory.jsonl", [_inventory_record(self.target)])
            _write_jsonl(
                property_dir / "failures.jsonl",
                [_failure_record(self.target, category="navigation_error")],
            )

            self.assertFalse(
                is_property_complete(Path(tmp), 1, self.target, [7], [4])
            )

    def test_pending_targets_returns_only_incomplete_targets(self) -> None:
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            complete_dir = expected_property_dir(run_dir, 1, self.target)
            _write_jsonl(complete_dir / "room_inventory.jsonl", [_inventory_record(self.target)])
            _write_jsonl(
                complete_dir / "price_rows.jsonl",
                [_price_record(self.target, 7, 4)],
            )
            incomplete_dir = expected_property_dir(run_dir, 2, self.other_target)
            incomplete_dir.mkdir(parents=True)

            self.assertEqual(
                pending_targets(run_dir, [self.target, self.other_target], [7], [4]),
                [self.other_target],
            )


if __name__ == "__main__":
    unittest.main()
