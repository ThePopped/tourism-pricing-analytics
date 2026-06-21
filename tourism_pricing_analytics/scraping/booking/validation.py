"""Structured validation for completed scrape run directories.

These helpers read the JSONL artifacts written under ``saved_dom/runs/<timestamp>/``
and report data-quality problems without touching the live browser. They are pure
functions over already-persisted run output so they can be unit tested against
small fixtures and reused for post-run gating before data moves downstream.
"""

import json
import math
from dataclasses import asdict, dataclass, field
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

    def issue_counts_by_check(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for issue in self.issues:
            counts[issue.check] = counts.get(issue.check, 0) + 1
        return counts


def report_to_dict(report: RunValidationReport) -> dict:
    """Convert a validation report into a JSON-serializable dict."""

    return {
        "run_dir": str(report.run_dir),
        "is_valid": report.is_valid,
        "issue_count": len(report.issues),
        "issue_counts_by_check": report.issue_counts_by_check(),
        "issues": [asdict(issue) for issue in report.issues],
    }


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

        # A price row must be attributable to a room. The preferred key is the
        # numeric room_id (recovered from the block-id prefix when no header is
        # present), but Booking's generic "bbasic" blocks expose a room_name with
        # no numeric id; those rows are still attributable by name and reconciled
        # to an id downstream. Only a row with neither is truly orphaned.
        if _is_missing(record.get("room_id")) and _is_missing(record.get("room_name")):
            issues.append(
                ValidationIssue(
                    check="price_row_room_identity",
                    message="Price row has neither room_id nor room_name; cannot attribute to a room",
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


def validate_room_features(records: list[dict], *, source: str) -> list[ValidationIssue]:
    """Validate the room-features stream: a clean join key and sane magnitudes.

    room_id is the join key to price rows, so it must be present and unique per
    property. Size and occupancy, when present, must fall within sane bounds; a
    value outside them signals a parsing error rather than a real listing.
    """

    issues: list[ValidationIssue] = []
    seen_pairs: set[tuple[str, str]] = set()

    for index, record in enumerate(records, start=1):
        location = f"{source}:{index}"

        room_id = record.get("room_id")
        if _is_missing(room_id):
            issues.append(
                ValidationIssue(
                    check="room_feature_room_id",
                    message="Room feature record is missing room_id",
                    location=location,
                )
            )

        property_url = record.get("property_url")
        if not _is_missing(room_id) and not _is_missing(property_url):
            pair = (str(property_url), str(room_id))
            if pair in seen_pairs:
                issues.append(
                    ValidationIssue(
                        check="room_feature_duplicates",
                        message=(
                            "Duplicate room feature record for "
                            f"(property_url={property_url!r}, room_id={room_id!r})"
                        ),
                        location=location,
                    )
                )
            seen_pairs.add(pair)

        room_size_sqm = record.get("room_size_sqm")
        if isinstance(room_size_sqm, (int, float)) and not (0 < room_size_sqm <= 1000):
            issues.append(
                ValidationIssue(
                    check="room_feature_bounds",
                    message=f"room_size_sqm {room_size_sqm} is outside (0, 1000]",
                    location=location,
                )
            )

        max_persons = record.get("max_persons")
        if isinstance(max_persons, int) and not (1 <= max_persons <= 30):
            issues.append(
                ValidationIssue(
                    check="room_feature_bounds",
                    message=f"max_persons {max_persons} is outside [1, 30]",
                    location=location,
                )
            )

        bed_count = record.get("bed_count")
        if isinstance(bed_count, int) and bed_count < 0:
            issues.append(
                ValidationIssue(
                    check="room_feature_bounds",
                    message=f"bed_count {bed_count} is negative",
                    location=location,
                )
            )

    return issues


def validate_property_features(records: list[dict], *, source: str) -> list[ValidationIssue]:
    """Validate the property-features stream: a clean join key and sane magnitudes.

    property_url is the join key to price rows, so it must be present and unique.
    Scores/subscores, when present, must fall within Booking's 0-10 scale; the
    star rating within 0-5; and counts/distances must be non-negative. A value
    outside these bounds signals a parsing error rather than a real listing.
    """

    issues: list[ValidationIssue] = []
    seen_urls: set[str] = set()

    for index, record in enumerate(records, start=1):
        location = f"{source}:{index}"

        property_url = record.get("property_url")
        if _is_missing(property_url):
            issues.append(
                ValidationIssue(
                    check="property_feature_property_url",
                    message="Property feature record is missing property_url",
                    location=location,
                )
            )
        else:
            url = str(property_url)
            if url in seen_urls:
                issues.append(
                    ValidationIssue(
                        check="property_feature_duplicates",
                        message=f"Duplicate property feature record for property_url={property_url!r}",
                        location=location,
                    )
                )
            seen_urls.add(url)

        star_rating = record.get("star_rating")
        if isinstance(star_rating, (int, float)) and not (0 < star_rating <= 5):
            issues.append(
                ValidationIssue(
                    check="property_feature_bounds",
                    message=f"star_rating {star_rating} is outside (0, 5]",
                    location=location,
                )
            )

        review_score = record.get("review_score")
        if isinstance(review_score, (int, float)) and not (0 <= review_score <= 10):
            issues.append(
                ValidationIssue(
                    check="property_feature_bounds",
                    message=f"review_score {review_score} is outside [0, 10]",
                    location=location,
                )
            )

        subscores = record.get("review_subscores")
        if isinstance(subscores, dict):
            for category, value in subscores.items():
                if isinstance(value, (int, float)) and not (0 <= value <= 10):
                    issues.append(
                        ValidationIssue(
                            check="property_feature_bounds",
                            message=f"review subscore {category!r}={value} is outside [0, 10]",
                            location=location,
                        )
                    )

        for count_field in ("review_count", "photo_count"):
            value = record.get(count_field)
            if isinstance(value, int) and value < 0:
                issues.append(
                    ValidationIssue(
                        check="property_feature_bounds",
                        message=f"{count_field} {value} is negative",
                        location=location,
                    )
                )

        nearby_poi = record.get("nearby_poi")
        if isinstance(nearby_poi, list):
            for poi in nearby_poi:
                distance = poi.get("distance") if isinstance(poi, dict) else None
                if isinstance(distance, (int, float)) and distance < 0:
                    issues.append(
                        ValidationIssue(
                            check="property_feature_bounds",
                            message=f"nearby_poi distance {distance} is negative",
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

    # room_features.jsonl is an optional stream (absent in pre-feature runs), so
    # it is only validated when present rather than required.
    room_features_path = run_dir / "room_features.jsonl"
    if room_features_path.exists():
        feature_records, feature_parse_issues = load_jsonl_records(room_features_path)
        issues.extend(feature_parse_issues)
        issues.extend(validate_room_features(feature_records, source="room_features.jsonl"))

    # property_features.jsonl is likewise optional (absent in pre-Tier-C runs).
    property_features_path = run_dir / "property_features.jsonl"
    if property_features_path.exists():
        property_records, property_parse_issues = load_jsonl_records(property_features_path)
        issues.extend(property_parse_issues)
        issues.extend(
            validate_property_features(property_records, source="property_features.jsonl")
        )

    return RunValidationReport(run_dir=run_dir, issues=issues)
