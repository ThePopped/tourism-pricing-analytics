"""Layer 2 join: assemble the modelling table from persisted JSONL streams.

Pure functions over already-persisted run output (no browser, no Playwright).
A price row is the grain of the modelling table, so this performs a *left* join
of price rows onto room features (on ``room_id``) and property features (on
``property_url``) — one output row per price row — and attaches the Tier A
calendar / meal-plan / cancellation derivations.

It also reconciles price rows whose ``room_id`` is null but whose ``room_name``
is set (Booking "bbasic" generic blocks) to a numeric id by
``(property_url, room_name)`` against room inventory. This name -> id step is
deliberately a Layer 2 join, not a scrape-time guess: inventory is the
authoritative source that always carries both the name and the numeric id.
"""

from pathlib import Path

from tourism_pricing_analytics.features.cancellation import cancellation_features
from tourism_pricing_analytics.features.meal_plan import meal_plan_features
from tourism_pricing_analytics.features.seasonality import seasonality_features
from tourism_pricing_analytics.scraping.booking.validation import load_jsonl_records


# Identity fields carried by feature records that a price row already owns;
# excluded when merging so the price row's values win and columns stay unique.
_ROOM_FEATURE_IDENTITY = frozenset({"property_name", "property_url", "captured_at", "room_id"})
_PROPERTY_FEATURE_IDENTITY = frozenset({"property_name", "property_url", "captured_at"})


def build_room_name_index(inventory_records: list[dict]) -> dict[tuple[str, str], str]:
    """Map ``(property_url, room_name) -> room_id`` from room inventory.

    Inventory is the authoritative name -> id source: every record carries both a
    numeric ``room_id`` and a ``room_name``. The first id seen for a name wins.
    """

    index: dict[tuple[str, str], str] = {}
    for record in inventory_records:
        property_url = record.get("property_url")
        room_name = record.get("room_name")
        room_id = record.get("room_id")
        if property_url and room_name and room_id:
            index.setdefault((property_url, room_name), room_id)
    return index


def resolve_room_id(
    price_row: dict,
    name_index: dict[tuple[str, str], str],
) -> str | None:
    """Return the row's ``room_id``, reconciling a null id by ``room_name``.

    A row that already has a numeric ``room_id`` keeps it. A row with no id but a
    ``room_name`` is matched against the inventory name index. An unmatched name
    yields None: the row still appears in the table, just without room features.
    """

    room_id = price_row.get("room_id")
    if room_id:
        return room_id
    room_name = price_row.get("room_name")
    property_url = price_row.get("property_url")
    if room_name and property_url:
        return name_index.get((property_url, room_name))
    return None


def build_features(
    price_rows: list[dict],
    room_features: list[dict],
    property_features: list[dict],
    room_inventory: list[dict],
) -> list[dict]:
    """Left-join the streams into one modelling row per price row."""

    rooms_by_key = {
        (record.get("property_url"), record.get("room_id")): record
        for record in room_features
    }
    props_by_url = {record.get("property_url"): record for record in property_features}
    name_index = build_room_name_index(room_inventory)

    rows: list[dict] = []
    for price_row in price_rows:
        row = dict(price_row)

        original_room_id = price_row.get("room_id")
        resolved_id = resolve_room_id(price_row, name_index)
        row["room_id"] = resolved_id
        row["room_id_reconciled"] = bool(resolved_id and not original_room_id)

        # Tier A derivations from fields already on the price row.
        row.update(seasonality_features(price_row.get("checkin")))
        row.update(meal_plan_features(price_row.get("conditions_text")))
        row.update(cancellation_features(price_row.get("conditions_text")))

        room = rooms_by_key.get((price_row.get("property_url"), resolved_id))
        if room is not None:
            for key, value in room.items():
                if key not in _ROOM_FEATURE_IDENTITY:
                    row[key] = value

        prop = props_by_url.get(price_row.get("property_url"))
        if prop is not None:
            for key, value in prop.items():
                if key not in _PROPERTY_FEATURE_IDENTITY:
                    row[key] = value

        rows.append(row)

    return rows


def build_features_from_run(run_dir: Path) -> list[dict]:
    """Build the modelling table from a completed run directory's JSONL streams.

    ``property_features.jsonl`` is optional (absent until the Tier C property
    extractors land), so a missing stream simply contributes nothing rather than
    failing the build.
    """

    price_rows, _ = load_jsonl_records(run_dir / "price_rows.jsonl")
    room_features, _ = load_jsonl_records(run_dir / "room_features.jsonl")
    property_features, _ = load_jsonl_records(run_dir / "property_features.jsonl")
    room_inventory, _ = load_jsonl_records(run_dir / "room_inventory.jsonl")
    return build_features(price_rows, room_features, property_features, room_inventory)
