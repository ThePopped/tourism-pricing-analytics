import json
import logging
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path

from playwright.sync_api import Page

from tourism_pricing_analytics.scraping.booking.models import (
    PriceRowRecord,
    PropertyFeatureRecord,
    PropertyTarget,
    RoomFeatureRecord,
    RoomInventoryRecord,
    ScrapeFailureRecord,
)
from tourism_pricing_analytics.scraping.booking.urls import slugify
from tourism_pricing_analytics.scraping.booking.validation import (
    RunValidationReport,
    report_to_dict,
)


RUN_METADATA_FILENAME = "run_metadata.json"


def create_run_dir(output_root: Path) -> Path:
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    run_dir = output_root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def load_run_metadata(run_dir: Path) -> dict:
    path = run_dir / RUN_METADATA_FILENAME
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logging.warning("Ignoring malformed run metadata: %s", path)
        return {}
    if not isinstance(data, dict):
        logging.warning("Ignoring non-object run metadata: %s", path)
        return {}
    return data


def save_run_metadata(run_dir: Path, metadata: dict) -> Path:
    path = run_dir / RUN_METADATA_FILENAME
    content = json.dumps(metadata, ensure_ascii=True, indent=2, sort_keys=True)
    return save_text_file(content + "\n", path)


def _search_base_date_from_record(record: dict) -> date | None:
    checkin = record.get("checkin")
    lead_time_days = record.get("lead_time_days")
    if not isinstance(checkin, str) or not isinstance(lead_time_days, int):
        return None
    try:
        return date.fromisoformat(checkin) - timedelta(days=lead_time_days)
    except ValueError:
        return None


def infer_run_search_base_date(run_dir: Path) -> date | None:
    """Infer the run's date anchor from existing dated artifacts, if any."""

    for filename in ("price_rows.jsonl", "failures.jsonl"):
        aggregate_path = run_dir / filename
        if not aggregate_path.exists():
            continue
        for line in aggregate_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            search_base_date = _search_base_date_from_record(record)
            if search_base_date is not None:
                return search_base_date

    for artifact_path in sorted(run_dir.glob("*/price_rows.jsonl")) + sorted(
        run_dir.glob("*/failures.jsonl")
    ):
        for line in artifact_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            search_base_date = _search_base_date_from_record(record)
            if search_base_date is not None:
                return search_base_date

    return None


def resolve_run_search_base_date(run_dir: Path, today: date | None = None) -> date:
    """Return and persist the date anchor used to expand lead-time windows.

    A resumed run must keep the same date windows even if it resumes after
    midnight. For older runs without metadata, infer the anchor from existing
    dated artifacts before falling back to the current date.
    """

    metadata = load_run_metadata(run_dir)
    value = metadata.get("search_base_date")
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            logging.warning("Ignoring invalid search_base_date in run metadata: %s", value)

    search_base_date = infer_run_search_base_date(run_dir) or (today or date.today())
    metadata["search_base_date"] = search_base_date.isoformat()
    metadata.setdefault("created_at", datetime.now().isoformat(timespec="seconds"))
    save_run_metadata(run_dir, metadata)
    return search_base_date


def create_property_output_dir(run_dir: Path, property_index: int, target: PropertyTarget) -> Path:
    property_dir = run_dir / f"{property_index:03d}_{slugify(target.name)}"
    property_dir.mkdir(parents=True, exist_ok=True)
    return property_dir


def setup_logging(log_path: Path) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_path, encoding="utf-8"),
        ],
        force=True,
    )


def save_text_file(content: str, filepath: Path) -> Path:
    filepath.write_text(content, encoding="utf-8")
    logging.info("saved file: %s", filepath)
    return filepath


def save_jsonl_file(records: list[dict], filepath: Path) -> Path:
    lines = [json.dumps(record, ensure_ascii=True) for record in records]
    content = "\n".join(lines)
    if lines:
        content += "\n"
    return save_text_file(content, filepath)


def append_jsonl_file(records: list[dict], filepath: Path) -> Path:
    lines = [json.dumps(record, ensure_ascii=True) for record in records]
    if not lines:
        return filepath

    filepath.parent.mkdir(parents=True, exist_ok=True)
    with filepath.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
        handle.write("\n")
    logging.info("appended file: %s", filepath)
    return filepath


def room_inventory_records_to_dicts(records: list[RoomInventoryRecord]) -> list[dict]:
    return [asdict(record) for record in records]


def price_row_records_to_dicts(records: list[PriceRowRecord]) -> list[dict]:
    return [asdict(record) for record in records]


def failure_records_to_dicts(records: list[ScrapeFailureRecord]) -> list[dict]:
    return [asdict(record) for record in records]


def room_feature_records_to_dicts(records: list[RoomFeatureRecord]) -> list[dict]:
    return [asdict(record) for record in records]


def property_feature_records_to_dicts(records: list[PropertyFeatureRecord]) -> list[dict]:
    return [asdict(record) for record in records]


def save_property_room_inventory(
    records: list[RoomInventoryRecord],
    output_dir: Path,
) -> Path:
    return save_jsonl_file(
        room_inventory_records_to_dicts(records),
        output_dir / "room_inventory.jsonl",
    )


def save_property_price_rows(
    records: list[PriceRowRecord],
    output_dir: Path,
) -> Path:
    return save_jsonl_file(
        price_row_records_to_dicts(records),
        output_dir / "price_rows.jsonl",
    )


def save_property_failures(
    records: list[ScrapeFailureRecord],
    output_dir: Path,
) -> Path:
    return save_jsonl_file(
        failure_records_to_dicts(records),
        output_dir / "failures.jsonl",
    )


def append_property_failures(
    records: list[ScrapeFailureRecord],
    output_dir: Path,
) -> Path:
    return append_jsonl_file(
        failure_records_to_dicts(records),
        output_dir / "failures.jsonl",
    )


def save_property_room_features(
    records: list[RoomFeatureRecord],
    output_dir: Path,
) -> Path:
    return save_jsonl_file(
        room_feature_records_to_dicts(records),
        output_dir / "room_features.jsonl",
    )


def save_property_features(
    records: list[PropertyFeatureRecord],
    output_dir: Path,
) -> Path:
    return save_jsonl_file(
        property_feature_records_to_dicts(records),
        output_dir / "property_features.jsonl",
    )


def save_validation_report(report: RunValidationReport, filepath: Path) -> Path:
    content = json.dumps(report_to_dict(report), ensure_ascii=True, indent=2)
    return save_text_file(content + "\n", filepath)


def save_full_page_dom(
    page: Page,
    output_dir: Path,
    filename: str,
) -> Path:
    filepath = output_dir / filename
    return save_text_file(page.content(), filepath)
