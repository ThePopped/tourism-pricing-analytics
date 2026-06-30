"""Load and validate the durable downstream modelling table."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Iterable

import pandas as pd

from config import DATA_DIR

DEFAULT_MODELLING_TABLE = DATA_DIR / "modelling" / "modelling_table.parquet"
DEFAULT_HEDONIC_TRAINING_TABLE = DATA_DIR / "modelling" / "hedonic_training_table.parquet"

JSON_ENCODED_COLUMNS = (
    "quantity_options",
    "bed_types",
    "amenities",
    "review_subscores",
    "property_facilities",
    "nearby_poi",
    "house_rules",
    "languages_spoken",
)

REQUIRED_COLUMNS = (
    "property_name",
    "property_url",
    "checkin",
    "checkout",
    "lead_time_days",
    "stay_length_days",
    "block_id",
    "current_price_value",
    "price_per_night",
    "property_type",
    "latitude",
    "longitude",
)

NON_NULL_COLUMNS = (
    "property_name",
    "property_url",
    "checkin",
    "checkout",
    "lead_time_days",
    "stay_length_days",
    "block_id",
    "current_price_value",
    "price_per_night",
)


class ModellingTableError(ValueError):
    """Raised when the modelling table cannot be safely used for analysis."""


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return value is pd.NA


def decode_json_cell(value: object) -> object:
    """Decode one JSON-encoded Parquet cell, preserving nulls and objects."""

    if _is_missing(value):
        return None
    if isinstance(value, (list, dict)):
        return value
    if not isinstance(value, str):
        return value
    return json.loads(value)


def decode_nested_columns(
    frame: pd.DataFrame,
    columns: Iterable[str] = JSON_ENCODED_COLUMNS,
) -> pd.DataFrame:
    """Return a copy with known JSON-encoded nested columns decoded."""

    out = frame.copy()
    for column in columns:
        if column in out.columns:
            try:
                out[column] = out[column].map(decode_json_cell)
            except json.JSONDecodeError as exc:
                raise ModellingTableError(
                    f"Column {column!r} contains invalid JSON: {exc}"
                ) from exc
    return out


def parse_temporal_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with date-like columns converted to pandas timestamps."""

    out = frame.copy()
    for column in ("checkin", "checkout", "captured_at"):
        if column in out.columns:
            out[column] = pd.to_datetime(out[column], errors="coerce")
    return out


def validate_modelling_table(frame: pd.DataFrame) -> None:
    """Validate the minimum contract expected by downstream analysis code."""

    missing_columns = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing_columns:
        raise ModellingTableError(f"Missing required columns: {', '.join(missing_columns)}")
    if frame.empty:
        raise ModellingTableError("Modelling table is empty")

    null_columns = [
        column for column in NON_NULL_COLUMNS if frame[column].isna().any()
    ]
    if null_columns:
        raise ModellingTableError(f"Unexpected nulls in columns: {', '.join(null_columns)}")

    checkin = pd.to_datetime(frame["checkin"], errors="coerce")
    checkout = pd.to_datetime(frame["checkout"], errors="coerce")
    if checkin.isna().any() or checkout.isna().any():
        raise ModellingTableError("checkin/checkout contain unparsable dates")
    if (checkout <= checkin).any():
        raise ModellingTableError("checkout must be after checkin for every row")

    stay_lengths = pd.to_numeric(frame["stay_length_days"], errors="coerce")
    prices = pd.to_numeric(frame["current_price_value"], errors="coerce")
    nightly = pd.to_numeric(frame["price_per_night"], errors="coerce")
    if stay_lengths.isna().any() or prices.isna().any() or nightly.isna().any():
        raise ModellingTableError("Price and stay-length columns must be numeric")
    if (stay_lengths <= 0).any():
        raise ModellingTableError("stay_length_days must be positive")
    if (prices <= 0).any() or (nightly <= 0).any():
        raise ModellingTableError("Prices must be positive")

    expected_nightly = prices / stay_lengths
    mismatched = (expected_nightly - nightly).abs() > 0.01
    if mismatched.any():
        raise ModellingTableError("price_per_night does not match total price / stay length")


def load_modelling_table(
    path: str | Path = DEFAULT_MODELLING_TABLE,
    *,
    decode_json: bool = True,
    parse_dates: bool = True,
    validate: bool = True,
) -> pd.DataFrame:
    """Load the committed modelling table with optional decoding and validation."""

    table_path = Path(path)
    frame = pd.read_parquet(table_path)
    if validate:
        validate_modelling_table(frame)
    if decode_json:
        frame = decode_nested_columns(frame)
    if parse_dates:
        frame = parse_temporal_columns(frame)
    return frame
