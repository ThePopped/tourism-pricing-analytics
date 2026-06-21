import logging
import re
from datetime import date

from playwright.sync_api import Locator, Page

from tourism_pricing_analytics.scraping.booking.models import (
    PriceRowRecord,
    PropertyTarget,
    RoomInventoryRecord,
)


def normalize_whitespace(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = re.sub(r"\s+", " ", value).strip()
    return normalized or None


def normalize_price_text(value: str | None) -> float | None:
    normalized_text = normalize_whitespace(value)
    if normalized_text is None:
        return None

    price_text = re.sub(r"[^0-9,.\-]", "", normalized_text)
    if not price_text:
        return None

    comma_index = price_text.rfind(",")
    dot_index = price_text.rfind(".")

    decimal_separator: str | None = None
    if comma_index >= 0 and dot_index >= 0:
        decimal_separator = "," if comma_index > dot_index else "."
    elif comma_index >= 0:
        parts = price_text.split(",")
        if not (len(parts[-1]) == 3 and all(len(part) == 3 for part in parts[1:])):
            decimal_separator = ","
    elif dot_index >= 0:
        parts = price_text.split(".")
        if not (len(parts[-1]) == 3 and all(len(part) == 3 for part in parts[1:])):
            decimal_separator = "."

    if decimal_separator is None:
        normalized_price = re.sub(r"[,\.]", "", price_text)
    elif decimal_separator == ",":
        normalized_price = price_text.replace(".", "").replace(",", ".")
    else:
        normalized_price = price_text.replace(",", "")

    try:
        return float(normalized_price)
    except ValueError:
        logging.debug("Unable to parse price text %r", value)
        return None


def compute_price_per_night(total_price: float | None, stay_length_days: int) -> float | None:
    if total_price is None or stay_length_days <= 0:
        return None
    return round(total_price / stay_length_days, 2)


def room_id_from_block_id(block_id: str | None) -> str | None:
    """Recover the room id from a Booking ``data-block-id``.

    Block ids are composite keys of the form ``{room_id}_{rate_plan}_...`` (for
    example ``217097709_383286522_2_1_0``), so the leading numeric segment is the
    room id. This lets a price row that precedes its room-type header row, or
    whose header link is missing ``data-room-id``, still be attributed to its room
    instead of carrying a null ``room_id`` downstream.
    """

    if not block_id:
        return None

    match = re.match(r"(\d+)_", block_id)
    if match is None:
        return None
    return match.group(1)


def get_locator_text(locator: Locator) -> str | None:
    try:
        if locator.count() == 0:
            return None
        return normalize_whitespace(locator.first.inner_text(timeout=0))
    except Exception:
        logging.debug("Unable to read text from locator", exc_info=True)
        return None


def get_locator_attribute(locator: Locator, attribute_name: str) -> str | None:
    try:
        if locator.count() == 0:
            return None
        return locator.first.get_attribute(attribute_name, timeout=0)
    except Exception:
        logging.debug("Unable to read %s from locator", attribute_name, exc_info=True)
        return None


def extract_room_inventory(
    page: Page,
    target: PropertyTarget,
    property_url: str,
    captured_at: str,
) -> list[RoomInventoryRecord]:
    rd_buttons = page.locator('[href^="#RD"]')
    count = rd_buttons.count()
    logging.info("Found %d room inventory links for %s", count, target.name)

    seen_room_ids: set[str] = set()
    records: list[RoomInventoryRecord] = []

    for index in range(count):
        locator = rd_buttons.nth(index)
        room_name = get_locator_text(locator)
        href = get_locator_attribute(locator, "href")
        if room_name is None or href is None:
            continue

        match = re.search(r"#RD(\d+)", href)
        if match is None:
            continue

        room_id = match.group(1)
        if room_id in seen_room_ids:
            continue

        seen_room_ids.add(room_id)
        records.append(
            RoomInventoryRecord(
                property_name=target.name,
                property_url=property_url,
                room_id=room_id,
                room_name=room_name,
                captured_at=captured_at,
            )
        )

    return records


def extract_select_options(row: Locator) -> list[str]:
    try:
        select_options = row.locator("select option")
        return [
            option
            for option in (
                get_locator_text(select_options.nth(index))
                for index in range(select_options.count())
            )
            if option is not None
        ]
    except Exception:
        logging.exception("Unable to extract quantity options from price row")
        return []


def extract_price_rows(
    page: Page,
    target: PropertyTarget,
    checkin: date,
    checkout: date,
    lead_time_days: int,
    stay_length_days: int,
    captured_at: str,
) -> list[PriceRowRecord]:
    rows = page.locator("tr.js-rt-block-row")
    count = rows.count()
    logging.info(
        "Found %d price rows for %s between %s and %s",
        count,
        target.name,
        checkin.isoformat(),
        checkout.isoformat(),
    )

    records: list[PriceRowRecord] = []
    current_room_id: str | None = None
    current_room_name: str | None = None
    current_scarcity_text: str | None = None

    for index in range(count):
        try:
            row = rows.nth(index)
            room_cell = row.locator("th.hprt-table-cell-roomtype")

            if room_cell.count() > 0:
                room_link = room_cell.locator(".hprt-roomtype-link").first
                current_room_name = get_locator_text(room_link)
                current_room_id = get_locator_attribute(room_link, "data-room-id")
                current_scarcity_text = get_locator_text(room_cell.locator(".only_x_left").first)

            current_price_text = get_locator_text(row.locator(".bui-price-display__value").first)
            original_price_text = get_locator_text(row.locator(".bui-price-display__original").first)
            current_price_value = normalize_price_text(current_price_text)
            original_price_value = normalize_price_text(original_price_text)

            block_id = get_locator_attribute(row, "data-block-id")
            # Prefer the carried-forward room id from the room-type header cell;
            # fall back to the block id prefix when no header has been seen yet or
            # its link lacked a room id, so the row is never left with a null room.
            row_room_id = current_room_id or room_id_from_block_id(block_id)

            records.append(
                PriceRowRecord(
                    property_name=target.name,
                    property_url=target.url,
                    checkin=checkin.isoformat(),
                    checkout=checkout.isoformat(),
                    lead_time_days=lead_time_days,
                    stay_length_days=stay_length_days,
                    room_id=row_room_id,
                    room_name=current_room_name,
                    block_id=block_id,
                    occupancy_text=get_locator_text(row.locator(".hprt-table-cell-occupancy").first),
                    conditions_text=get_locator_text(row.locator(".hprt-table-cell-conditions").first),
                    scarcity_text=current_scarcity_text,
                    current_price_text=current_price_text,
                    original_price_text=original_price_text,
                    current_price_value=current_price_value,
                    original_price_value=original_price_value,
                    price_per_night=compute_price_per_night(current_price_value, stay_length_days),
                    quantity_options=extract_select_options(row),
                    captured_at=captured_at,
                )
            )
        except Exception:
            logging.exception(
                "Failed parsing price row %d for %s between %s and %s",
                index,
                target.name,
                checkin.isoformat(),
                checkout.isoformat(),
            )
            raise

    return records
