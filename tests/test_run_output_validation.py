import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tourism_pricing_analytics.scraping.booking.validation import (
    REQUIRED_RUN_FILES,
    RunValidationReport,
    ValidationIssue,
    load_jsonl_records,
    report_to_dict,
    validate_failures,
    validate_price_rows,
    validate_room_inventory,
    validate_run_directory,
)


def _room_record(**overrides) -> dict:
    record = {
        "property_name": "Example Hotel",
        "property_url": "https://www.booking.com/hotel/gr/example.en-gb.html",
        "room_id": "12345601",
        "room_name": "Double Room",
        "captured_at": "2026-06-20T18:00:00",
    }
    record.update(overrides)
    return record


def _price_record(**overrides) -> dict:
    record = {
        "property_name": "Example Hotel",
        "property_url": "https://www.booking.com/hotel/gr/example.en-gb.html",
        "checkin": "2026-06-21",
        "checkout": "2026-06-25",
        "lead_time_days": 1,
        "stay_length_days": 4,
        "room_id": "12345601",
        "room_name": "Double Room",
        "block_id": "12345601_000",
        "occupancy_text": "2 adults",
        "conditions_text": None,
        "scarcity_text": None,
        "current_price_text": "€ 400",
        "original_price_text": None,
        "current_price_value": 400.0,
        "original_price_value": None,
        "price_per_night": 100.0,
        "quantity_options": ["1"],
        "captured_at": "2026-06-20T18:00:00",
    }
    record.update(overrides)
    return record


def _failure_record(**overrides) -> dict:
    record = {
        "property_name": "Example Hotel",
        "property_url": "https://www.booking.com/hotel/gr/example.en-gb.html",
        "scrape_stage": "price_rows",
        "category": "empty_availability",
        "reason": "No availability for the requested window.",
        "requested_url": "https://www.booking.com/hotel/gr/example.en-gb.html",
        "final_url": "https://www.booking.com/hotel/gr/example.en-gb.html",
        "checkin": "2026-06-21",
        "checkout": "2026-06-25",
        "lead_time_days": 1,
        "stay_length_days": 4,
        "status_code": 200,
        "snapshot_filename": None,
        "exception_type": None,
        "exception_message": None,
        "captured_at": "2026-06-20T18:00:00",
    }
    record.update(overrides)
    return record


def _write_jsonl(filepath: Path, records: list[dict]) -> None:
    lines = [json.dumps(record, ensure_ascii=True) for record in records]
    content = "\n".join(lines)
    if lines:
        content += "\n"
    filepath.write_text(content, encoding="utf-8")


def _write_valid_run(run_dir: Path) -> None:
    _write_jsonl(run_dir / "room_inventory.jsonl", [_room_record()])
    _write_jsonl(run_dir / "price_rows.jsonl", [_price_record()])
    _write_jsonl(run_dir / "failures.jsonl", [_failure_record()])
    (run_dir / "scrape_debug.log").write_text("ok\n", encoding="utf-8")


class LoadJsonlRecordsTests(unittest.TestCase):
    def test_parses_one_record_per_line_and_ignores_trailing_newline(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "price_rows.jsonl"
            _write_jsonl(path, [_price_record(), _price_record(room_id="12345602")])
            records, issues = load_jsonl_records(path)
        self.assertEqual(len(records), 2)
        self.assertEqual(issues, [])

    def test_reports_missing_file(self) -> None:
        with TemporaryDirectory() as tmp:
            records, issues = load_jsonl_records(Path(tmp) / "missing.jsonl")
        self.assertEqual(records, [])
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].check, "jsonl_parse")

    def test_reports_malformed_line(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "price_rows.jsonl"
            path.write_text('{"ok": 1}\nnot json\n', encoding="utf-8")
            records, issues = load_jsonl_records(path)
        self.assertEqual(len(records), 1)
        self.assertEqual(len(issues), 1)
        self.assertIn("price_rows.jsonl:2", issues[0].location)

    def test_reports_non_object_line(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "price_rows.jsonl"
            path.write_text("[1, 2, 3]\n", encoding="utf-8")
            records, issues = load_jsonl_records(path)
        self.assertEqual(records, [])
        self.assertEqual(len(issues), 1)


class RoomInventoryValidationTests(unittest.TestCase):
    def test_clean_records_have_no_issues(self) -> None:
        issues = validate_room_inventory(
            [_room_record(), _room_record(room_id="12345602")],
            source="room_inventory.jsonl",
        )
        self.assertEqual(issues, [])

    def test_detects_duplicate_pairs(self) -> None:
        issues = validate_room_inventory(
            [_room_record(), _room_record()],
            source="room_inventory.jsonl",
        )
        checks = [issue.check for issue in issues]
        self.assertIn("room_inventory_duplicates", checks)

    def test_detects_missing_room_id_and_name(self) -> None:
        issues = validate_room_inventory(
            [_room_record(room_id=None, room_name="")],
            source="room_inventory.jsonl",
        )
        messages = [issue.message for issue in issues]
        self.assertTrue(any("missing room_id" in m for m in messages))
        self.assertTrue(any("missing room_name" in m for m in messages))


class PriceRowValidationTests(unittest.TestCase):
    def test_clean_records_have_no_issues(self) -> None:
        issues = validate_price_rows([_price_record()], source="price_rows.jsonl")
        self.assertEqual(issues, [])

    def test_detects_missing_required_fields(self) -> None:
        issues = validate_price_rows(
            [_price_record(checkin=None, stay_length_days=None)],
            source="price_rows.jsonl",
        )
        checks = [issue.check for issue in issues]
        self.assertEqual(checks.count("price_row_fields"), 2)

    def test_detects_nonpositive_price_with_raw_text(self) -> None:
        issues = validate_price_rows(
            [_price_record(current_price_value=0.0)],
            source="price_rows.jsonl",
        )
        checks = [issue.check for issue in issues]
        self.assertIn("price_row_positive_price", checks)

    def test_ignores_nonpositive_when_no_raw_text(self) -> None:
        issues = validate_price_rows(
            [
                _price_record(
                    current_price_text=None,
                    current_price_value=None,
                    price_per_night=None,
                )
            ],
            source="price_rows.jsonl",
        )
        self.assertEqual(issues, [])

    def test_detects_inconsistent_price_per_night(self) -> None:
        issues = validate_price_rows(
            [_price_record(price_per_night=999.0)],
            source="price_rows.jsonl",
        )
        checks = [issue.check for issue in issues]
        self.assertIn("price_per_night_consistency", checks)

    def test_allows_small_rounding_tolerance(self) -> None:
        # 130 / 3 = 43.333..., stored rounded to 43.33
        issues = validate_price_rows(
            [
                _price_record(
                    stay_length_days=3,
                    current_price_value=130.0,
                    price_per_night=43.33,
                )
            ],
            source="price_rows.jsonl",
        )
        self.assertEqual(issues, [])


class FailureValidationTests(unittest.TestCase):
    def test_clean_records_have_no_issues(self) -> None:
        with TemporaryDirectory() as tmp:
            issues = validate_failures(
                [_failure_record()],
                Path(tmp),
                source="failures.jsonl",
            )
        self.assertEqual(issues, [])

    def test_detects_missing_category(self) -> None:
        with TemporaryDirectory() as tmp:
            issues = validate_failures(
                [_failure_record(category=None)],
                Path(tmp),
                source="failures.jsonl",
            )
        checks = [issue.check for issue in issues]
        self.assertIn("failure_category", checks)

    def test_detects_missing_snapshot_file(self) -> None:
        with TemporaryDirectory() as tmp:
            issues = validate_failures(
                [_failure_record(snapshot_filename="price_rows_selector_drift.html")],
                Path(tmp),
                source="failures.jsonl",
            )
        checks = [issue.check for issue in issues]
        self.assertIn("failure_snapshot_exists", checks)

    def test_accepts_snapshot_in_property_subdirectory(self) -> None:
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            property_dir = run_dir / "001_example"
            property_dir.mkdir()
            snapshot = "price_rows_selector_drift_lead_001_stay_004.html"
            (property_dir / snapshot).write_text("<html></html>", encoding="utf-8")
            issues = validate_failures(
                [_failure_record(snapshot_filename=snapshot)],
                run_dir,
                source="failures.jsonl",
            )
        self.assertEqual(issues, [])


class ValidateRunDirectoryTests(unittest.TestCase):
    def test_valid_run_reports_no_issues(self) -> None:
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_valid_run(run_dir)
            report = validate_run_directory(run_dir)
        self.assertTrue(report.is_valid, msg=report.issues)
        self.assertEqual(report.run_dir, run_dir)

    def test_missing_required_files_are_reported(self) -> None:
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_jsonl(run_dir / "room_inventory.jsonl", [_room_record()])
            report = validate_run_directory(run_dir)
        required_issues = report.issues_for("required_files")
        missing = {Path(issue.location).name for issue in required_issues}
        self.assertIn("price_rows.jsonl", missing)
        self.assertIn("failures.jsonl", missing)
        self.assertIn("scrape_debug.log", missing)

    def test_aggregates_issues_across_artifacts(self) -> None:
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_jsonl(run_dir / "room_inventory.jsonl", [_room_record(), _room_record()])
            _write_jsonl(run_dir / "price_rows.jsonl", [_price_record(price_per_night=1.0)])
            _write_jsonl(
                run_dir / "failures.jsonl",
                [_failure_record(snapshot_filename="absent.html")],
            )
            (run_dir / "scrape_debug.log").write_text("ok\n", encoding="utf-8")
            report = validate_run_directory(run_dir)
        checks = {issue.check for issue in report.issues}
        self.assertFalse(report.is_valid)
        self.assertIn("room_inventory_duplicates", checks)
        self.assertIn("price_per_night_consistency", checks)
        self.assertIn("failure_snapshot_exists", checks)

    def test_required_files_constant_matches_expected_set(self) -> None:
        self.assertEqual(
            set(REQUIRED_RUN_FILES),
            {
                "room_inventory.jsonl",
                "price_rows.jsonl",
                "failures.jsonl",
                "scrape_debug.log",
            },
        )


class ReportSerializationTests(unittest.TestCase):
    def test_report_to_dict_round_trips_through_json(self) -> None:
        report = RunValidationReport(
            run_dir=Path("saved_dom/runs/example"),
            issues=[
                ValidationIssue(
                    check="price_row_fields",
                    message="Price row is missing checkin",
                    location="price_rows.jsonl:2",
                ),
                ValidationIssue(
                    check="price_row_fields",
                    message="Price row is missing checkout",
                    location="price_rows.jsonl:3",
                ),
            ],
        )
        payload = json.loads(json.dumps(report_to_dict(report)))
        self.assertFalse(payload["is_valid"])
        self.assertEqual(payload["issue_count"], 2)
        self.assertEqual(payload["issue_counts_by_check"], {"price_row_fields": 2})
        self.assertEqual(len(payload["issues"]), 2)

    def test_valid_report_serializes_clean(self) -> None:
        report = RunValidationReport(run_dir=Path("saved_dom/runs/example"))
        payload = report_to_dict(report)
        self.assertTrue(payload["is_valid"])
        self.assertEqual(payload["issue_count"], 0)
        self.assertEqual(payload["issues"], [])


class ValidateAndReportRunTests(unittest.TestCase):
    def test_writes_report_and_logs_pass(self) -> None:
        from tourism_pricing_analytics.scraping.booking.runner import validate_and_report_run

        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_valid_run(run_dir)
            with self.assertLogs(level="INFO") as captured:
                validate_and_report_run(run_dir)
            report_path = run_dir / "validation_report.json"
            self.assertTrue(report_path.is_file())
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertTrue(payload["is_valid"])
        self.assertTrue(any("validation passed" in line for line in captured.output))

    def test_writes_report_and_logs_warning_on_issues(self) -> None:
        from tourism_pricing_analytics.scraping.booking.runner import validate_and_report_run

        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_jsonl(run_dir / "room_inventory.jsonl", [_room_record(), _room_record()])
            _write_jsonl(run_dir / "price_rows.jsonl", [_price_record()])
            _write_jsonl(run_dir / "failures.jsonl", [_failure_record()])
            (run_dir / "scrape_debug.log").write_text("ok\n", encoding="utf-8")
            with self.assertLogs(level="WARNING") as captured:
                validate_and_report_run(run_dir)
            payload = json.loads(
                (run_dir / "validation_report.json").read_text(encoding="utf-8")
            )
        self.assertFalse(payload["is_valid"])
        self.assertIn("room_inventory_duplicates", payload["issue_counts_by_check"])
        self.assertTrue(any("validation found" in line for line in captured.output))


if __name__ == "__main__":
    unittest.main()
