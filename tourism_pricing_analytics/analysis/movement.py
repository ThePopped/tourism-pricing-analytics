"""Schema contracts for repeated-scrape price movement history."""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

SNAPSHOT_CONTEXT_COLUMNS = ("snapshot_date", "captured_at", "run_id")
PROPERTY_IDENTITY_COLUMNS = ("property_url", "property_name")
OFFER_IDENTITY_COLUMNS = ("room_id", "room_name", "block_id")
QUERY_CONTEXT_COLUMNS = (
    "checkin",
    "checkout",
    "lead_time_days",
    "stay_length_days",
    "adults",
    "children",
    "rooms",
    "currency",
    "market",
)
PROPERTY_CONTEXT_COLUMNS = ("property_type", "latitude", "longitude")
PRICE_COLUMNS = ("price_per_night", "current_price_value")

PRICE_OBSERVATION_COLUMNS = (
    *SNAPSHOT_CONTEXT_COLUMNS,
    *PROPERTY_IDENTITY_COLUMNS,
    *OFFER_IDENTITY_COLUMNS,
    *QUERY_CONTEXT_COLUMNS,
    *PRICE_COLUMNS,
    *PROPERTY_CONTEXT_COLUMNS,
)
OFFER_PRESENCE_COLUMNS = (
    *SNAPSHOT_CONTEXT_COLUMNS,
    *PROPERTY_IDENTITY_COLUMNS,
    *QUERY_CONTEXT_COLUMNS,
    *PROPERTY_CONTEXT_COLUMNS,
    "availability_status",
    "failure_reason",
)

DEDUPE_QUERY_CONTEXT_COLUMNS = (
    "checkin",
    "checkout",
    "adults",
    "children",
    "rooms",
    "currency",
    "market",
)
PRESENCE_DEDUPE_KEY = (
    "snapshot_date",
    "property_url",
    *DEDUPE_QUERY_CONTEXT_COLUMNS,
)
OBSERVATION_DEDUPE_KEY = (
    *PRESENCE_DEDUPE_KEY,
    "room_id",
    "block_id",
)

AVAILABILITY_STATUS_AVAILABLE = "available"
AVAILABILITY_STATUS_NO_OFFER = "no_available_offer"
AVAILABILITY_STATUS_FAILED = "scrape_failed"
AVAILABILITY_STATUSES = frozenset(
    {
        AVAILABILITY_STATUS_AVAILABLE,
        AVAILABILITY_STATUS_NO_OFFER,
        AVAILABILITY_STATUS_FAILED,
    }
)

TEMPORAL_DATE_COLUMNS = ("snapshot_date", "checkin", "checkout")
TEMPORAL_DATETIME_COLUMNS = ("captured_at",)
INTEGER_CONTEXT_COLUMNS = (
    "lead_time_days",
    "stay_length_days",
    "adults",
    "children",
    "rooms",
)
NUMERIC_CONTEXT_COLUMNS = ("latitude", "longitude")
OBSERVATION_NUMERIC_COLUMNS = (*INTEGER_CONTEXT_COLUMNS, *PRICE_COLUMNS, *NUMERIC_CONTEXT_COLUMNS)
PRESENCE_NUMERIC_COLUMNS = (*INTEGER_CONTEXT_COLUMNS, *NUMERIC_CONTEXT_COLUMNS)
NON_NULL_OBSERVATION_COLUMNS = tuple(
    column for column in PRICE_OBSERVATION_COLUMNS if column not in {"latitude", "longitude"}
)
NON_NULL_PRESENCE_COLUMNS = tuple(
    column for column in OFFER_PRESENCE_COLUMNS if column not in {"latitude", "longitude", "failure_reason"}
)


class MovementHistoryError(ValueError):
    """Raised when movement-history input violates the v1 schema contract."""


def _missing_columns(frame: pd.DataFrame, required: Iterable[str]) -> list[str]:
    return [column for column in required if column not in frame.columns]


def _require_columns(frame: pd.DataFrame, required: Iterable[str], label: str) -> None:
    missing = _missing_columns(frame, required)
    if missing:
        raise MovementHistoryError(
            f"{label} is missing required columns: {', '.join(missing)}"
        )


def _normalize_temporal_columns(frame: pd.DataFrame, label: str) -> pd.DataFrame:
    out = frame.copy()
    for column in TEMPORAL_DATE_COLUMNS:
        if column in out.columns:
            out[column] = pd.to_datetime(out[column], errors="coerce").dt.normalize()
    for column in TEMPORAL_DATETIME_COLUMNS:
        if column in out.columns:
            out[column] = pd.to_datetime(out[column], errors="coerce")

    temporal_columns = [
        column for column in (*TEMPORAL_DATE_COLUMNS, *TEMPORAL_DATETIME_COLUMNS)
        if column in out.columns
    ]
    bad = [column for column in temporal_columns if out[column].isna().any()]
    if bad:
        raise MovementHistoryError(
            f"{label} has unparsable date values in: {', '.join(bad)}"
        )
    return out


def _normalize_numeric_columns(
    frame: pd.DataFrame,
    columns: Iterable[str],
    label: str,
) -> pd.DataFrame:
    out = frame.copy()
    for column in columns:
        out[column] = pd.to_numeric(out[column], errors="coerce")
    bad = [column for column in columns if out[column].isna().any()]
    if bad:
        raise MovementHistoryError(
            f"{label} has non-numeric values in: {', '.join(bad)}"
        )
    return out


def _validate_non_null(frame: pd.DataFrame, columns: Iterable[str], label: str) -> None:
    bad = [column for column in columns if frame[column].isna().any()]
    if bad:
        raise MovementHistoryError(f"{label} has null values in: {', '.join(bad)}")


def _validate_non_empty_strings(
    frame: pd.DataFrame,
    columns: Iterable[str],
    label: str,
) -> None:
    bad: list[str] = []
    for column in columns:
        values = frame[column].astype("string")
        if values.str.strip().eq("").any():
            bad.append(column)
    if bad:
        raise MovementHistoryError(f"{label} has blank values in: {', '.join(bad)}")


def _validate_query_context(frame: pd.DataFrame, label: str) -> None:
    if (frame["checkout"] <= frame["checkin"]).any():
        raise MovementHistoryError(f"{label} checkout must be after checkin")
    if (frame["lead_time_days"] < 0).any():
        raise MovementHistoryError(f"{label} lead_time_days must be zero or positive")
    if (frame["stay_length_days"] <= 0).any():
        raise MovementHistoryError(f"{label} stay_length_days must be positive")
    if (frame["adults"] <= 0).any():
        raise MovementHistoryError(f"{label} adults must be positive")
    if (frame["children"] < 0).any():
        raise MovementHistoryError(f"{label} children must be zero or positive")
    if (frame["rooms"] <= 0).any():
        raise MovementHistoryError(f"{label} rooms must be positive")


def normalize_price_observations(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of price observations parsed and validated to the v1 schema."""

    label = "price observations"
    _require_columns(frame, PRICE_OBSERVATION_COLUMNS, label)
    out = _normalize_temporal_columns(frame, label)
    out = _normalize_numeric_columns(out, OBSERVATION_NUMERIC_COLUMNS, label)
    _validate_non_null(out, NON_NULL_OBSERVATION_COLUMNS, label)
    _validate_non_empty_strings(
        out,
        (
            "run_id",
            "property_url",
            "property_name",
            "room_id",
            "room_name",
            "block_id",
            "currency",
            "market",
            "property_type",
        ),
        label,
    )
    _validate_query_context(out, label)
    if (out["price_per_night"] <= 0).any() or (out["current_price_value"] <= 0).any():
        raise MovementHistoryError("price observations prices must be positive")
    return out


def validate_price_observations(frame: pd.DataFrame) -> None:
    """Validate price observations, raising ``MovementHistoryError`` on failure."""

    normalize_price_observations(frame)


def normalize_offer_presence(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of offer-presence rows parsed and validated to the v1 schema."""

    label = "offer presence"
    _require_columns(frame, OFFER_PRESENCE_COLUMNS, label)
    out = _normalize_temporal_columns(frame, label)
    out = _normalize_numeric_columns(out, PRESENCE_NUMERIC_COLUMNS, label)
    _validate_non_null(out, NON_NULL_PRESENCE_COLUMNS, label)
    _validate_non_empty_strings(
        out,
        (
            "run_id",
            "property_url",
            "property_name",
            "currency",
            "market",
            "property_type",
            "availability_status",
        ),
        label,
    )
    _validate_query_context(out, label)

    invalid_statuses = sorted(set(out["availability_status"]) - AVAILABILITY_STATUSES)
    if invalid_statuses:
        raise MovementHistoryError(
            "offer presence has invalid availability_status values: "
            + ", ".join(invalid_statuses)
        )
    return out


def validate_offer_presence(frame: pd.DataFrame) -> None:
    """Validate offer-presence rows, raising ``MovementHistoryError`` on failure."""

    normalize_offer_presence(frame)
