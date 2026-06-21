"""Structured validation for completed scrape run directories.

These helpers read the JSONL artifacts written under ``saved_dom/runs/<timestamp>/``
and report data-quality problems without touching the live browser. They are pure
functions over already-persisted run output so they can be unit tested against
small fixtures and reused for post-run gating before data moves downstream.
"""

import json
import math
from dataclasses import dataclass, field
from pathlib import Path


REQUIRED_RUN_FILES = (
    "room_inventory.jsonl",
    "price_rows.jsonl",
    "failures.jsonl",
    "scrape_debug.log",
)

# price_per_night is stored as round(value / stay_length_days, 2); allow a small
# tolerance so floating point representation does not produce spurious failures.
PRICE_PER_NIGHT_ABS_TOL = 0.01


@dataclass(frozen=True)
class ValidationIssue:
    check: str
    message: str
    location: str | None = None


@dataclass(frozen=True)
class RunValidationReport:
    run_dir: Path
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.issues

    def issues_for(self, check: str) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.check == check]


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def load_jsonl_records(filepath: Path) -> tuple[list[dict], list[ValidationIssue]]:
    """Parse a JSONL file into records, reporting one issue per malformed line.

    Blank trailing lines are ignored to match :func:`save_jsonl_file`, which
    appends a trailing newline after the final record.
    """

    issues: list[ValidationIssue] = []
    records: list[dict] = []

    if not filepath.exists():
        issues.append(
            ValidationIssue(
                check="jsonl_parse",
                message=f"Expected JSONL file is missing: {filepath.name}",
                location=str(filepath),
            )
        )
        return records, issues

    text = filepath.read_text(encoding="utf-8")
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if raw_line.strip() == "":
            continue
        try:
            parsed = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            issues.append(
                ValidationIssue(
                    check="jsonl_parse",
                    message=f"Line does not parse as JSON: {exc}",
                    location=f"{filepath.name}:{line_number}",
                )
            )
            continue

        if not isinstance(parsed, dict):
            issues.append(
                ValidationIssue(
                    check="jsonl_parse",
                    message=f"Line is not a JSON object (got {type(parsed).__name__})",
                    location=f"{filepath.name}:{line_number}",
                )
            )
            continue

        records.append(parsed)

    return records, issues


def validate_required_files(run_dir: Path) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for filename in REQUIRED_RUN_FILES:
        if not (run_dir / filename).is_file():
            issues.append(
                ValidationIssue(
                    check="required_files",
                    message=f"Required run file is missing: {filename}",
                    location=str(run_dir / filename),
                )
            )
    return issues


def validate_room_inventory(records: list[dict], *, source: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    seen_pairs: set[tuple[str, str]] = set()

    for index, record in enumerate(records, start=1):
        location = f"{source}:{index}"
        room_id = record.get("room_id")
        room_name = record.get("room_name")

        if _is_missing(room_id):
            issues.append(
                ValidationIssue(
                    check="room_inventory_fields",
                    message="Room inventory record is missing room_id",
                    location=location,
                )
            )
        if _is_missing(room_name):
            issues.append(
                ValidationIssue(
                    check="room_inventory_fields",
                    message="Room inventory record is missing room_name",
                    location=location,
                )
            )

        property_url = record.get("property_url")
        if not _is_missing(room_id) and not _is_missing(property_url):
            pair = (str(property_url), str(room_id))
            if pair in seen_pairs:
                issues.append(
                    ValidationIssue(
                        check="room_inventory_duplicates",
                        message=(
                            "Duplicate room inventory record for "
                            f"(property_url={property_url!r}, room_id={room_id!r})"
                        ),
                        location=location,
                    )
                )
            seen_pairs.add(pair)

    return issues


def validate_price_rows(records: list[dict], *, source: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    required_fields = ("checkin", "checkout", "stay_length_days", "captured_at")

    for index, record in enumerate(records, start=1):
        location = f"{source}:{index}"

        for field_name in required_fields:
            if _is_missing(record.get(field_name)):
                issues.append(
                    ValidationIssue(
                        check="price_row_fields",
                        message=f"Price row is missing {field_name}",
                        location=location,
                    )
                )

        current_price_text = record.get("current_price_text")
        current_price_value = record.get("current_price_value")

        if not _is_missing(current_price_text) and isinstance(current_price_value, (int, float)):
            if current_price_value <= 0:
                issues.append(
                    ValidationIssue(
                        check="price_row_positive_price",
                        message=(
                            "Price row has nonpositive current_price_value "
                            f"({current_price_value}) despite raw price text "
                            f"{current_price_text!r}"
                        ),
                        location=location,
                    )
                )

        price_per_night = record.get("price_per_night")
        stay_length_days = record.get("stay_length_days")
        if (
            isinstance(current_price_value, (int, float))
            and isinstance(price_per_night, (int, float))
            and isinstance(stay_length_days, int)
            and stay_length_days > 0
        ):
            expected = round(current_price_value / stay_length_days, 2)
            if not math.isclose(price_per_night, expected, abs_tol=PRICE_PER_NIGHT_ABS_TOL):
                issues.append(
                    ValidationIssue(
                        check="price_per_night_consistency",
                        message=(
                            f"price_per_night {price_per_night} does not match "
                            f"current_price_value / stay_length_days "
                            f"({current_price_value} / {stay_length_days} = {expected})"
                        ),
                        location=location,
                    )
                )

    return issues


def validate_failures(
    records: list[dict],
    run_dir: Path,
    *,
    source: str,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    for index, record in enumerate(records, start=1):
        location = f"{source}:{index}"

        if _is_missing(record.get("category")):
            issues.append(
                ValidationIssue(
                    check="failure_category",
                    message="Failure record is missing category",
                    location=location,
                )
            )

        snapshot_filename = record.get("snapshot_filename")
        if not _is_missing(snapshot_filename):
            # Snapshots are written into per-property subdirectories, so search the
            # whole run tree for the referenced filename rather than only run_dir.
            matches = list(run_dir.rglob(str(snapshot_filename)))
            if not matches:
                issues.append(
                    ValidationIssue(
                        check="failure_snapshot_exists",
                        message=(
                            "Failure record references snapshot "
                            f"{snapshot_filename!r} but no such file exists under the run"
                        ),
                        location=location,
                    )
                )

    return issues


def validate_run_directory(run_dir: Path) -> RunValidationReport:
    """Validate a completed scrape run directory and return all issues found."""

    issues: list[ValidationIssue] = []
    issues.extend(validate_required_files(run_dir))

    room_records, room_parse_issues = load_jsonl_records(run_dir / "room_inventory.jsonl")
    price_records, price_parse_issues = load_jsonl_records(run_dir / "price_rows.jsonl")
    failure_records, failure_parse_issues = load_jsonl_records(run_dir / "failures.jsonl")
    issues.extend(room_parse_issues)
    issues.extend(price_parse_issues)
    issues.extend(failure_parse_issues)

    issues.extend(validate_room_inventory(room_records, source="room_inventory.jsonl"))
    issues.extend(validate_price_rows(price_records, source="price_rows.jsonl"))
    issues.extend(validate_failures(failure_records, run_dir, source="failures.jsonl"))

    return RunValidationReport(run_dir=run_dir, issues=issues)
