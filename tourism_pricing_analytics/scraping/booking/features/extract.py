"""Per-page room feature collection.

Locates each room's header row in the price table, resolves its ``room_id``
(preferring the room link, falling back to the block-id prefix), runs the
registered room extractors in isolation, and assembles deduped
``RoomFeatureRecord`` rows. Room features are stable across dates, so callers
typically run this once per property and dedupe by ``room_id``.
"""

import logging
from dataclasses import fields

from playwright.sync_api import Page

from tourism_pricing_analytics.scraping.booking.features.base import (
    RoomFeatureContext,
    run_extractors,
)
from tourism_pricing_analytics.scraping.booking.features.registry import ROOM_EXTRACTORS
from tourism_pricing_analytics.scraping.booking.models import RoomFeatureRecord
from tourism_pricing_analytics.scraping.booking.parsing import (
    get_locator_attribute,
    room_id_from_block_id,
)


_ROOM_FEATURE_FIELDS = {field.name for field in fields(RoomFeatureRecord)}


def extract_room_features(
    page: Page,
    *,
    property_name: str,
    property_url: str,
    captured_at: str,
    extractors=None,
) -> list[RoomFeatureRecord]:
    extractors = ROOM_EXTRACTORS if extractors is None else extractors

    rows = page.locator("tr.js-rt-block-row")
    records: list[RoomFeatureRecord] = []
    seen_room_ids: set[str] = set()

    for index in range(rows.count()):
        row = rows.nth(index)
        room_cell = row.locator("th.hprt-table-cell-roomtype")
        if room_cell.count() == 0:
            continue
        room_cell = room_cell.first

        room_link = room_cell.locator(".hprt-roomtype-link").first
        room_id = get_locator_attribute(room_link, "data-room-id") or room_id_from_block_id(
            get_locator_attribute(row, "data-block-id")
        )
        if room_id is None or room_id in seen_room_ids:
            continue
        seen_room_ids.add(room_id)

        ctx = RoomFeatureContext(
            row=row,
            room_cell=room_cell,
            property_url=property_url,
            room_id=room_id,
        )
        merged = run_extractors(extractors, ctx)
        # Drop any unexpected keys so a stray field never aborts record
        # construction; the per-extractor isolation in run_extractors is only
        # useful if the assembly step is equally defensive.
        feature_fields = {
            key: value for key, value in merged.items() if key in _ROOM_FEATURE_FIELDS
        }
        unexpected = set(merged) - _ROOM_FEATURE_FIELDS
        if unexpected:
            logging.warning("Ignoring unexpected room feature keys: %s", sorted(unexpected))

        records.append(
            RoomFeatureRecord(
                property_name=property_name,
                property_url=property_url,
                room_id=room_id,
                captured_at=captured_at,
                **feature_fields,
            )
        )

    return records
