"""Analysis population and segment helpers."""

from __future__ import annotations

import pandas as pd

SELF_CATERING_PROPERTY_TYPES = frozenset(
    {
        "Apartment",
        "Aparthotel",
        "Holiday home",
        "Villa",
    }
)
OPTIONAL_SELF_CATERING_PROPERTY_TYPES = frozenset({"Guest house"})


def normalize_property_type(value: object) -> str | None:
    """Normalize Booking property-type labels for stable filtering."""

    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def self_catering_property_types(*, include_guest_house: bool = False) -> tuple[str, ...]:
    """Return the property types included in the self-catering segment."""

    values = set(SELF_CATERING_PROPERTY_TYPES)
    if include_guest_house:
        values.update(OPTIONAL_SELF_CATERING_PROPERTY_TYPES)
    return tuple(sorted(values))


def segment_self_catering(
    frame: pd.DataFrame,
    *,
    include_guest_house: bool = False,
) -> pd.DataFrame:
    """Return apartment/villa-style rows for the agreed training population."""

    allowed = set(self_catering_property_types(include_guest_house=include_guest_house))
    normalized = frame["property_type"].map(normalize_property_type)
    return frame.loc[normalized.isin(allowed)].copy()


def property_type_counts(frame: pd.DataFrame) -> dict[str, int]:
    """Return deterministic property-type counts for rows in ``frame``."""

    normalized = frame["property_type"].map(normalize_property_type).fillna("(missing)")
    counts = normalized.value_counts()
    return {str(label): int(counts[label]) for label in sorted(counts.index)}
