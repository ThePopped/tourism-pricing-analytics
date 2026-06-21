import json
import logging
from dataclasses import asdict
from datetime import datetime
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


def create_run_dir(output_root: Path) -> Path:
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    run_dir = output_root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def create_property_output_dir(run_dir: Path, property_index: int, target: PropertyTarget) -> Path:
    property_dir = run_dir / f"{property_index:03d}_{slugify(target.name)}"
    property_dir.mkdir(parents=True, exist_ok=False)
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
