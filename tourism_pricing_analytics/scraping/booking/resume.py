"""Browser-free resumability helpers for Booking.com scrape runs."""

from datetime import date
from pathlib import Path

from tourism_pricing_analytics.scraping.booking.models import (
    FailureCategory,
    PropertyTarget,
)
from tourism_pricing_analytics.scraping.booking.urls import build_date_window, slugify
from tourism_pricing_analytics.scraping.booking.validation import load_jsonl_records


PriceWindow = tuple[int, int]
DatedPriceWindow = tuple[int, int, str, str]

TERMINAL_FAILURE_CATEGORIES: frozenset[FailureCategory] = frozenset(
    {
        "empty_availability",
        "selector_drift",
        "redirect",
        "extraction_error",
    }
)


def expected_property_dir(run_dir: Path, index: int, target: PropertyTarget) -> Path:
    """Return the per-property directory path used by the scraper."""

    return run_dir / f"{index:03d}_{slugify(target.name)}"


def expected_price_windows(
    lead_times: list[int],
    stay_lengths: list[int],
) -> set[PriceWindow]:
    """Return the configured price-window matrix as ``(lead, stay)`` pairs."""

    return {
        (lead_time_days, stay_length_days)
        for lead_time_days in lead_times
        for stay_length_days in stay_lengths
    }


def expected_dated_price_windows(
    lead_times: list[int],
    stay_lengths: list[int],
    search_base_date: date,
) -> set[DatedPriceWindow]:
    """Return the configured matrix with concrete checkin/checkout dates."""

    windows: set[DatedPriceWindow] = set()
    for lead_time_days in lead_times:
        for stay_length_days in stay_lengths:
            checkin, checkout = build_date_window(
                lead_time_days,
                stay_length_days,
                base_date=search_base_date,
            )
            windows.add(
                (
                    lead_time_days,
                    stay_length_days,
                    checkin.isoformat(),
                    checkout.isoformat(),
                )
            )
    return windows


def is_terminal_failure_category(category: object) -> bool:
    return category in TERMINAL_FAILURE_CATEGORIES


def _load_jsonl_dicts(path: Path) -> list[dict]:
    records, issues = load_jsonl_records(path)
    if issues:
        return []
    return records


def _matching_records(records: list[dict], target: PropertyTarget) -> list[dict]:
    return [record for record in records if record.get("property_url") == target.url]


def _has_inventory_terminal_artifact(property_dir: Path, target: PropertyTarget) -> bool:
    inventory_records = _matching_records(
        _load_jsonl_dicts(property_dir / "room_inventory.jsonl"),
        target,
    )
    if inventory_records:
        return True

    failure_records = _matching_records(
        _load_jsonl_dicts(property_dir / "failures.jsonl"),
        target,
    )
    return any(
        record.get("scrape_stage") == "room_inventory"
        and is_terminal_failure_category(record.get("category"))
        for record in failure_records
    )


def _price_row_window_keys(property_dir: Path, target: PropertyTarget) -> set[PriceWindow]:
    keys: set[PriceWindow] = set()
    for record in _matching_records(
        _load_jsonl_dicts(property_dir / "price_rows.jsonl"),
        target,
    ):
        lead_time_days = record.get("lead_time_days")
        stay_length_days = record.get("stay_length_days")
        if isinstance(lead_time_days, int) and isinstance(stay_length_days, int):
            keys.add((lead_time_days, stay_length_days))
    return keys


def _price_row_dated_window_keys(
    property_dir: Path,
    target: PropertyTarget,
) -> set[DatedPriceWindow]:
    keys: set[DatedPriceWindow] = set()
    for record in _matching_records(
        _load_jsonl_dicts(property_dir / "price_rows.jsonl"),
        target,
    ):
        lead_time_days = record.get("lead_time_days")
        stay_length_days = record.get("stay_length_days")
        checkin = record.get("checkin")
        checkout = record.get("checkout")
        if (
            isinstance(lead_time_days, int)
            and isinstance(stay_length_days, int)
            and isinstance(checkin, str)
            and isinstance(checkout, str)
        ):
            keys.add((lead_time_days, stay_length_days, checkin, checkout))
    return keys


def _terminal_price_failure_window_keys(
    property_dir: Path,
    target: PropertyTarget,
) -> set[PriceWindow]:
    keys: set[PriceWindow] = set()
    for record in _matching_records(
        _load_jsonl_dicts(property_dir / "failures.jsonl"),
        target,
    ):
        lead_time_days = record.get("lead_time_days")
        stay_length_days = record.get("stay_length_days")
        if (
            record.get("scrape_stage") == "price_rows"
            and is_terminal_failure_category(record.get("category"))
            and isinstance(lead_time_days, int)
            and isinstance(stay_length_days, int)
        ):
            keys.add((lead_time_days, stay_length_days))
    return keys


def _terminal_price_failure_dated_window_keys(
    property_dir: Path,
    target: PropertyTarget,
) -> set[DatedPriceWindow]:
    keys: set[DatedPriceWindow] = set()
    for record in _matching_records(
        _load_jsonl_dicts(property_dir / "failures.jsonl"),
        target,
    ):
        lead_time_days = record.get("lead_time_days")
        stay_length_days = record.get("stay_length_days")
        checkin = record.get("checkin")
        checkout = record.get("checkout")
        if (
            record.get("scrape_stage") == "price_rows"
            and is_terminal_failure_category(record.get("category"))
            and isinstance(lead_time_days, int)
            and isinstance(stay_length_days, int)
            and isinstance(checkin, str)
            and isinstance(checkout, str)
        ):
            keys.add((lead_time_days, stay_length_days, checkin, checkout))
    return keys


def is_property_complete(
    run_dir: Path,
    index: int,
    target: PropertyTarget,
    lead_times: list[int],
    stay_lengths: list[int],
    search_base_date: date | None = None,
) -> bool:
    """Return whether a property's persisted artifacts prove terminal progress."""

    property_dir = expected_property_dir(run_dir, index, target)
    if not property_dir.is_dir():
        return False

    if not _has_inventory_terminal_artifact(property_dir, target):
        return False

    if search_base_date is not None:
        required_windows = expected_dated_price_windows(
            lead_times,
            stay_lengths,
            search_base_date,
        )
        completed_windows = _price_row_dated_window_keys(property_dir, target)
        completed_windows.update(
            _terminal_price_failure_dated_window_keys(property_dir, target)
        )
        return required_windows.issubset(completed_windows)

    required_windows = expected_price_windows(lead_times, stay_lengths)
    completed_windows = _price_row_window_keys(property_dir, target)
    completed_windows.update(_terminal_price_failure_window_keys(property_dir, target))
    return required_windows.issubset(completed_windows)


def pending_targets(
    run_dir: Path,
    targets: list[PropertyTarget],
    lead_times: list[int],
    stay_lengths: list[int],
    search_base_date: date | None = None,
) -> list[PropertyTarget]:
    """Return configured targets whose per-property artifacts are incomplete."""

    return [
        target
        for index, target in enumerate(targets, start=1)
        if not is_property_complete(
            run_dir,
            index,
            target,
            lead_times,
            stay_lengths,
            search_base_date,
        )
    ]
