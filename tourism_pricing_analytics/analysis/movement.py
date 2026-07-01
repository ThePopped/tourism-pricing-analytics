"""Schema contracts for repeated-scrape price movement history."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd

from config import DATA_DIR

DEFAULT_PRICE_OBSERVATIONS_PATH = DATA_DIR / "modelling" / "price_observations.parquet"
DEFAULT_OFFER_PRESENCE_PATH = DATA_DIR / "modelling" / "offer_presence.parquet"
DEFAULT_DEMAND_COVARIATES_PATH = DATA_DIR / "modelling" / "demand_covariates.csv"

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

DEMAND_COVARIATE_COLUMNS = (
    "date",
    "checkin",
    "market",
    "google_trends_index",
    "holiday_flag",
    "event_flag",
    "weather_temp_c",
    "weather_rain_mm",
    "notes",
)
DEMAND_COVARIATE_REQUIRED_COLUMNS = ("date", "checkin", "market")
DEMAND_COVARIATE_DATE_COLUMNS = ("date", "checkin")
DEMAND_COVARIATE_NUMERIC_COLUMNS = (
    "google_trends_index",
    "weather_temp_c",
    "weather_rain_mm",
)
DEMAND_COVARIATE_FLAG_COLUMNS = ("holiday_flag", "event_flag")

HISTORY_STATUS_READY = "ready"
HISTORY_STATUS_LOW_HISTORY = "low_history"
HISTORY_STATUS_MISSING = "missing"
COVARIATE_STATUS_LOADED = "External covariates loaded."
COVARIATE_STATUS_MISSING = "No external covariates loaded."

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


def _empty_frame(columns: Iterable[str], **attrs: object) -> pd.DataFrame:
    frame = pd.DataFrame(columns=list(columns))
    frame.attrs.update(attrs)
    return frame


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


def _load_parquet_or_empty(
    path: str | Path,
    *,
    columns: Iterable[str],
    label: str,
    missing_message: str,
) -> pd.DataFrame:
    table_path = Path(path)
    if not table_path.exists():
        return _empty_frame(
            columns,
            history_status=HISTORY_STATUS_MISSING,
            history_message=missing_message,
            source_path=str(table_path),
        )
    try:
        frame = pd.read_parquet(table_path)
    except Exception as exc:  # pragma: no cover - pandas exception type depends on engine
        raise MovementHistoryError(f"Unable to load {label} from {table_path}: {exc}") from exc
    frame.attrs.update(
        history_status=HISTORY_STATUS_READY,
        history_message=f"Loaded {label}.",
        source_path=str(table_path),
    )
    return frame


def movement_history_status(
    observations: pd.DataFrame,
    presence: pd.DataFrame | None = None,
    *,
    min_snapshots: int = 2,
) -> dict[str, Any]:
    """Return a compact dashboard-ready status for loaded movement history."""

    frames = [frame for frame in (observations, presence) if frame is not None]
    snapshot_values: set[pd.Timestamp] = set()
    for frame in frames:
        if "snapshot_date" not in frame.columns or frame.empty:
            continue
        dates = pd.to_datetime(frame["snapshot_date"], errors="coerce").dropna()
        snapshot_values.update(date.normalize() for date in dates)

    snapshot_count = len(snapshot_values)
    has_missing_file = any(
        frame.attrs.get("history_status") == HISTORY_STATUS_MISSING for frame in frames
    )
    if snapshot_count >= min_snapshots:
        status = HISTORY_STATUS_READY
        message = f"Loaded {snapshot_count} comparable movement-history snapshots."
    elif has_missing_file:
        status = HISTORY_STATUS_MISSING
        message = "Movement history file is missing."
    else:
        status = HISTORY_STATUS_LOW_HISTORY
        message = (
            "Price movement history needs at least two comparable snapshots; "
            f"{snapshot_count} loaded."
        )
    return {
        "status": status,
        "is_low_history": status != HISTORY_STATUS_READY,
        "snapshot_count": snapshot_count,
        "min_snapshots": min_snapshots,
        "message": message,
    }


def load_price_observations(
    path: str | Path = DEFAULT_PRICE_OBSERVATIONS_PATH,
) -> pd.DataFrame:
    """Load generated price-observation history, returning empty low-history frames safely."""

    raw = _load_parquet_or_empty(
        path,
        columns=PRICE_OBSERVATION_COLUMNS,
        label="price observations",
        missing_message="Price observation history is missing.",
    )
    source_attrs = dict(raw.attrs)
    normalized = normalize_price_observations(raw).loc[:, list(PRICE_OBSERVATION_COLUMNS)]
    normalized.attrs.update(source_attrs)
    status = movement_history_status(normalized)
    normalized.attrs.update(
        history_status=status["status"],
        history_message=status["message"],
        low_history=status,
    )
    return normalized


def load_offer_presence(path: str | Path = DEFAULT_OFFER_PRESENCE_PATH) -> pd.DataFrame:
    """Load generated offer-presence history, returning empty low-history frames safely."""

    raw = _load_parquet_or_empty(
        path,
        columns=OFFER_PRESENCE_COLUMNS,
        label="offer presence",
        missing_message="Offer-presence history is missing.",
    )
    source_attrs = dict(raw.attrs)
    normalized = normalize_offer_presence(raw).loc[:, list(OFFER_PRESENCE_COLUMNS)]
    normalized.attrs.update(source_attrs)
    status = movement_history_status(normalized)
    normalized.attrs.update(
        history_status=status["status"],
        history_message=status["message"],
        low_history=status,
    )
    return normalized


def _normalize_bool_series(values: pd.Series, column: str) -> pd.Series:
    if values.isna().all():
        return values.fillna(False).astype(bool)

    def _coerce(value: object) -> bool:
        if pd.isna(value):
            return False
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and value in {0, 1}:
            return bool(value)
        text = str(value).strip().lower()
        if text in {"true", "t", "yes", "y", "1"}:
            return True
        if text in {"false", "f", "no", "n", "0", ""}:
            return False
        raise MovementHistoryError(f"demand covariates has invalid boolean values in: {column}")

    return values.map(_coerce).astype(bool)


def normalize_demand_covariates(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of manual demand covariates parsed to the v1 CSV schema."""

    label = "demand covariates"
    _require_columns(frame, DEMAND_COVARIATE_COLUMNS, label)
    out = frame.copy()

    for column in DEMAND_COVARIATE_DATE_COLUMNS:
        out[column] = pd.to_datetime(out[column], errors="coerce").dt.normalize()
    bad_dates = [column for column in DEMAND_COVARIATE_DATE_COLUMNS if out[column].isna().any()]
    if bad_dates:
        raise MovementHistoryError(
            f"{label} has unparsable date values in: {', '.join(bad_dates)}"
        )

    for column in DEMAND_COVARIATE_NUMERIC_COLUMNS:
        out[column] = pd.to_numeric(out[column], errors="coerce")

    for column in DEMAND_COVARIATE_FLAG_COLUMNS:
        out[column] = _normalize_bool_series(out[column], column)

    _validate_non_null(out, DEMAND_COVARIATE_REQUIRED_COLUMNS, label)
    _validate_non_empty_strings(out, ("market",), label)
    if "notes" in out.columns:
        out["notes"] = out["notes"].fillna("").astype("string")
    return out.loc[:, list(DEMAND_COVARIATE_COLUMNS)]


def validate_demand_covariates(frame: pd.DataFrame) -> None:
    """Validate manual demand covariates, raising ``MovementHistoryError`` on failure."""

    normalize_demand_covariates(frame)


def load_demand_covariates(
    path: str | Path = DEFAULT_DEMAND_COVARIATES_PATH,
) -> pd.DataFrame:
    """Load optional manual demand covariates; a missing file returns a safe empty frame."""

    csv_path = Path(path)
    if not csv_path.exists():
        return _empty_frame(
            DEMAND_COVARIATE_COLUMNS,
            covariate_status=COVARIATE_STATUS_MISSING,
            source_path=str(csv_path),
        )
    try:
        frame = pd.read_csv(csv_path)
    except Exception as exc:  # pragma: no cover - pandas exception type depends on parser
        raise MovementHistoryError(f"Unable to load demand covariates from {csv_path}: {exc}") from exc
    normalized = normalize_demand_covariates(frame)
    normalized.attrs.update(
        covariate_status=COVARIATE_STATUS_LOADED,
        source_path=str(csv_path),
    )
    return normalized
