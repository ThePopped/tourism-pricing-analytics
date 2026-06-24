import json
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from tourism_pricing_analytics.scraping.booking.models import PropertyTarget
from tourism_pricing_analytics.scraping.booking.sharding import (
    aggregate_run_artifacts,
    indexed_targets,
    pending_indexed_targets,
    split_indexed_targets,
)


def _target(index: int) -> PropertyTarget:
    return PropertyTarget(
        name=f"Hotel {index}",
        url=f"https://www.booking.com/hotel/gr/example-{index}.en-gb.html",
    )


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(f"{json.dumps(record)}\n" for record in records),
        encoding="utf-8",
    )


def _inventory_record(target: PropertyTarget) -> dict:
    return {
        "property_name": target.name,
        "property_url": target.url,
        "room_id": "12345601",
        "room_name": "Double Room",
        "captured_at": "2026-06-22T12:00:00",
    }


def _price_record(target: PropertyTarget, marker: str) -> dict:
    return {
        "property_name": target.name,
        "property_url": target.url,
        "checkin": "2026-07-01",
        "checkout": "2026-07-05",
        "lead_time_days": 7,
        "stay_length_days": 4,
        "room_id": "12345601",
        "room_name": "Double Room",
        "block_id": marker,
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


class ShardedScrapeDriverTests(unittest.TestCase):
    def test_split_indexed_targets_is_contiguous_and_balanced(self) -> None:
        targets = indexed_targets([_target(index) for index in range(1, 6)])

        shards = split_indexed_targets(targets, 2)

        self.assertEqual([[item.index for item in shard] for shard in shards], [[1, 2, 3], [4, 5]])

    def test_split_indexed_targets_keeps_empty_shards_for_idle_workers(self) -> None:
        targets = indexed_targets([_target(1), _target(2)])

        shards = split_indexed_targets(targets, 3)

        self.assertEqual([[item.index for item in shard] for shard in shards], [[1], [2], []])

    def test_split_indexed_targets_rejects_invalid_worker_count(self) -> None:
        with self.assertRaises(ValueError):
            split_indexed_targets([], 0)

    def test_pending_indexed_targets_uses_full_config_indexes_for_resume(self) -> None:
        targets = indexed_targets([_target(1), _target(2), _target(3)])
        second = targets[1]

        with TemporaryDirectory() as tmp:
            property_dir = Path(tmp) / "002_hotel_2"
            _write_jsonl(property_dir / "room_inventory.jsonl", [_inventory_record(second.target)])
            _write_jsonl(
                property_dir / "price_rows.jsonl",
                [_price_record(second.target, "completed-window")],
            )

            pending = pending_indexed_targets(
                Path(tmp),
                [second],
                lead_times=[7],
                stay_lengths=[4],
            )

        self.assertEqual(pending, [])

    def test_pending_indexed_targets_respects_search_base_date(self) -> None:
        targets = indexed_targets([_target(1)])

        with TemporaryDirectory() as tmp:
            property_dir = Path(tmp) / "001_hotel_1"
            _write_jsonl(property_dir / "room_inventory.jsonl", [_inventory_record(targets[0].target)])
            _write_jsonl(
                property_dir / "price_rows.jsonl",
                [_price_record(targets[0].target, "shifted-window")],
            )

            pending = pending_indexed_targets(
                Path(tmp),
                targets,
                lead_times=[7],
                stay_lengths=[4],
                search_base_date=date(2026, 6, 23),
            )

        self.assertEqual(pending, targets)

    def test_aggregate_run_artifacts_rebuilds_top_level_streams_in_config_order(self) -> None:
        targets = indexed_targets([_target(1), _target(2)])

        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_jsonl(
                run_dir / "002_hotel_2" / "price_rows.jsonl",
                [_price_record(targets[1].target, "second")],
            )
            _write_jsonl(
                run_dir / "001_hotel_1" / "price_rows.jsonl",
                [_price_record(targets[0].target, "first")],
            )

            counts = aggregate_run_artifacts(
                run_dir,
                targets,
                filenames=("price_rows.jsonl",),
            )
            records = [
                json.loads(line)
                for line in (run_dir / "price_rows.jsonl").read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(counts, {"price_rows.jsonl": 2})
        self.assertEqual([record["block_id"] for record in records], ["first", "second"])


if __name__ == "__main__":
    unittest.main()
