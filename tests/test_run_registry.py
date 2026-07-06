import json
import unittest
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from tourism_pricing_analytics.scraping.booking.registry import (
    append_run_registry,
    build_run_summary,
    count_artifact_records,
    count_priced_properties,
    inventory_freshness_payload,
    latest_inventory_feature_run,
    min_available_gib,
    read_validation_summary,
    summarize_failures,
)


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(f"{json.dumps(record)}\n" for record in records),
        encoding="utf-8",
    )


class SummarizeFailuresTests(unittest.TestCase):
    def test_tallies_categories_and_challenge_signals(self) -> None:
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_jsonl(
                run_dir / "failures.jsonl",
                [
                    {
                        "category": "selector_drift",
                        "final_url": "https://www.booking.com/hotel/gr/a.html",
                        "exception_message": None,
                    },
                    {
                        "category": "selector_drift",
                        "final_url": None,
                        "exception_message": "Page.goto: net::ERR_ABORTED",
                    },
                    {
                        "category": "blocked_challenge",
                        "final_url": "https://www.booking.com/chal_t/xyz",
                        "exception_message": None,
                    },
                ],
            )

            summary = summarize_failures(run_dir)

            self.assertEqual(
                summary,
                {
                    "by_category": {"blocked_challenge": 1, "selector_drift": 2},
                    "chal_t": 1,
                    "err_aborted": 1,
                    "total": 3,
                },
            )

    def test_missing_file_yields_empty_summary(self) -> None:
        with TemporaryDirectory() as tmp:
            summary = summarize_failures(Path(tmp))

            self.assertEqual(
                summary,
                {"by_category": {}, "chal_t": 0, "err_aborted": 0, "total": 0},
            )


class CountPricedPropertiesTests(unittest.TestCase):
    def test_counts_distinct_property_urls(self) -> None:
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_jsonl(
                run_dir / "price_rows.jsonl",
                [
                    {"property_url": "https://example.com/a"},
                    {"property_url": "https://example.com/a"},
                    {"property_url": "https://example.com/b"},
                    {"property_url": None},
                    {},
                ],
            )

            self.assertEqual(count_priced_properties(run_dir), 2)

    def test_missing_file_counts_zero(self) -> None:
        with TemporaryDirectory() as tmp:
            self.assertEqual(count_priced_properties(Path(tmp)), 0)


class MinAvailableGibTests(unittest.TestCase):
    def test_returns_minimum_in_gib(self) -> None:
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_jsonl(
                run_dir / "memory_stats.jsonl",
                [
                    {"available_bytes": 4 * 2**30},
                    {"available_bytes": 2 * 2**30},
                    {"available_bytes": 3 * 2**30},
                    {"available_bytes": None},
                ],
            )

            self.assertEqual(min_available_gib(run_dir), 2.0)

    def test_missing_or_empty_file_returns_none(self) -> None:
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            self.assertIsNone(min_available_gib(run_dir))

            _write_jsonl(run_dir / "memory_stats.jsonl", [])
            self.assertIsNone(min_available_gib(run_dir))


class ReadValidationSummaryTests(unittest.TestCase):
    def test_reads_core_fields(self) -> None:
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "validation_report.json").write_text(
                json.dumps(
                    {
                        "run_dir": str(run_dir),
                        "is_valid": False,
                        "issue_count": 4,
                        "issues": [],
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                read_validation_summary(run_dir),
                {"is_valid": False, "issue_count": 4},
            )

    def test_tolerates_missing_and_malformed_files(self) -> None:
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            self.assertIsNone(read_validation_summary(run_dir))

            (run_dir / "validation_report.json").write_text(
                "{not json", encoding="utf-8"
            )
            self.assertIsNone(read_validation_summary(run_dir))


class BuildRunSummaryTests(unittest.TestCase):
    def _populate_run_dir(self, run_dir: Path) -> None:
        (run_dir / "run_metadata.json").write_text(
            json.dumps(
                {
                    "created_at": "2026-07-05T08:00:00",
                    "search_base_date": "2026-07-05",
                }
            ),
            encoding="utf-8",
        )
        _write_jsonl(
            run_dir / "price_rows.jsonl",
            [
                {"property_url": "https://example.com/a"},
                {"property_url": "https://example.com/b"},
            ],
        )
        _write_jsonl(
            run_dir / "failures.jsonl",
            [{"category": "redirect", "final_url": None, "exception_message": None}],
        )
        _write_jsonl(run_dir / "memory_stats.jsonl", [{"available_bytes": 2**30}])
        (run_dir / "validation_report.json").write_text(
            json.dumps({"is_valid": True, "issue_count": 0}),
            encoding="utf-8",
        )

    def test_merges_metadata_settings_timing_and_results(self) -> None:
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            self._populate_run_dir(run_dir)
            settings = {"workers": 8, "batch_per_worker": 1, "headless": True}

            summary = build_run_summary(
                run_dir,
                settings=settings,
                started_at=datetime(2026, 7, 5, 8, 0, 0),
                finished_at=datetime(2026, 7, 5, 9, 30, 0),
                status="completed",
                artifact_counts={"price_rows.jsonl": 2, "failures.jsonl": 1},
            )

            self.assertEqual(summary["run_id"], run_dir.name)
            self.assertEqual(summary["created_at"], "2026-07-05T08:00:00")
            self.assertEqual(summary["search_base_date"], "2026-07-05")
            self.assertEqual(summary["settings"], settings)
            self.assertEqual(summary["status"], "completed")
            self.assertEqual(summary["started_at"], "2026-07-05T08:00:00")
            self.assertEqual(summary["finished_at"], "2026-07-05T09:30:00")
            self.assertEqual(summary["duration_seconds"], 5400.0)
            self.assertEqual(
                summary["artifact_counts"],
                {"price_rows.jsonl": 2, "failures.jsonl": 1},
            )
            self.assertEqual(summary["priced_properties"], 2)
            self.assertEqual(summary["failure_summary"]["by_category"], {"redirect": 1})
            self.assertEqual(summary["min_available_gib"], 1.0)
            self.assertEqual(
                summary["validation"], {"is_valid": True, "issue_count": 0}
            )

    def test_backfill_mode_tolerates_unknown_settings_and_counts_artifacts(self) -> None:
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            self._populate_run_dir(run_dir)

            summary = build_run_summary(
                run_dir,
                settings=None,
                started_at=None,
                finished_at=None,
                status="backfilled",
            )

            self.assertIsNone(summary["settings"])
            self.assertIsNone(summary["started_at"])
            self.assertIsNone(summary["finished_at"])
            self.assertIsNone(summary["duration_seconds"])
            self.assertEqual(summary["status"], "backfilled")
            self.assertEqual(
                summary["artifact_counts"],
                {"price_rows.jsonl": 2, "failures.jsonl": 1},
            )

    def test_tolerates_bare_run_dir(self) -> None:
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)

            summary = build_run_summary(
                run_dir,
                settings=None,
                started_at=None,
                finished_at=None,
                status="backfilled",
            )

            self.assertEqual(summary["run_id"], run_dir.name)
            self.assertEqual(summary["artifact_counts"], {})
            self.assertEqual(summary["priced_properties"], 0)
            self.assertIsNone(summary["min_available_gib"])
            self.assertIsNone(summary["validation"])


class CountArtifactRecordsTests(unittest.TestCase):
    def test_counts_only_existing_streams(self) -> None:
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_jsonl(run_dir / "price_rows.jsonl", [{"a": 1}, {"a": 2}])
            _write_jsonl(run_dir / "failures.jsonl", [{"b": 1}])

            self.assertEqual(
                count_artifact_records(run_dir),
                {"price_rows.jsonl": 2, "failures.jsonl": 1},
            )


class InventoryFreshnessTests(unittest.TestCase):
    def test_selects_latest_completed_stable_feature_run(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry_path = root / "run_registry.jsonl"
            _write_jsonl(
                registry_path,
                [
                    {
                        "run_id": "old",
                        "status": "completed",
                        "finished_at": "2026-06-30T10:00:00",
                        "artifact_counts": {
                            "room_inventory.jsonl": 10,
                            "property_features.jsonl": 10,
                        },
                    },
                    {
                        "run_id": "missing_features",
                        "status": "completed",
                        "finished_at": "2026-07-03T10:00:00",
                        "artifact_counts": {
                            "room_inventory.jsonl": 10,
                            "property_features.jsonl": 0,
                        },
                    },
                    {
                        "run_id": "fresh",
                        "status": "completed",
                        "finished_at": "2026-07-04T10:00:00",
                        "artifact_counts": {
                            "room_inventory.jsonl": 12,
                            "property_features.jsonl": 12,
                        },
                    },
                ],
            )

            result = latest_inventory_feature_run(registry_path, root / "saved_dom")

        self.assertIsNotNone(result)
        row, run_dir = result
        self.assertEqual(row["run_id"], "fresh")
        self.assertEqual(run_dir, root / "saved_dom" / "runs" / "fresh")

    def test_marks_inventory_stale_when_age_exceeds_threshold(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry_path = root / "run_registry.jsonl"
            _write_jsonl(
                registry_path,
                [
                    {
                        "run_id": "stable",
                        "status": "completed",
                        "finished_at": "2026-06-28T10:00:00",
                        "artifact_counts": {
                            "room_inventory.jsonl": 1,
                            "property_features.jsonl": 1,
                        },
                    }
                ],
            )

            payload = inventory_freshness_payload(
                registry_path,
                root / "saved_dom",
                max_age_days=7,
                today=date(2026, 7, 6),
            )

        self.assertEqual(payload["latest_inventory_run_id"], "stable")
        self.assertEqual(payload["age_days"], 8)
        self.assertTrue(payload["is_stale"])
        self.assertIn("8 days old", payload["reason"])


class AppendRunRegistryTests(unittest.TestCase):
    def test_creates_registry_and_appends_distinct_runs(self) -> None:
        with TemporaryDirectory() as tmp:
            registry_path = Path(tmp) / "data" / "run_registry.jsonl"

            append_run_registry(registry_path, {"run_id": "run_a", "status": "completed"})
            append_run_registry(registry_path, {"run_id": "run_b", "status": "completed"})

            lines = registry_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual(json.loads(lines[0])["run_id"], "run_a")
            self.assertEqual(json.loads(lines[1])["run_id"], "run_b")

    def test_same_run_id_replaces_existing_row(self) -> None:
        with TemporaryDirectory() as tmp:
            registry_path = Path(tmp) / "run_registry.jsonl"

            append_run_registry(
                registry_path, {"run_id": "run_a", "status": "memory_halt"}
            )
            append_run_registry(registry_path, {"run_id": "run_b", "status": "completed"})
            append_run_registry(registry_path, {"run_id": "run_a", "status": "completed"})

            rows = [
                json.loads(line)
                for line in registry_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["run_id"], "run_b")
            self.assertEqual(rows[1], {"run_id": "run_a", "status": "completed"})

    def test_malformed_lines_are_dropped_on_rewrite(self) -> None:
        with TemporaryDirectory() as tmp:
            registry_path = Path(tmp) / "run_registry.jsonl"
            registry_path.write_text(
                '{"run_id": "run_a"}\n{not json\n', encoding="utf-8"
            )

            append_run_registry(registry_path, {"run_id": "run_b"})

            rows = [
                json.loads(line)
                for line in registry_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(
                [row["run_id"] for row in rows], ["run_a", "run_b"]
            )


if __name__ == "__main__":
    unittest.main()
