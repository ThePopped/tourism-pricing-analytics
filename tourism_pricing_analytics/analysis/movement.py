"""Schema contracts for repeated-scrape price movement history."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd

from config import DATA_DIR
from tourism_pricing_analytics.analysis.competitors import rank_competitors

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

MOVEMENT_STATUS_AVAILABLE = "available"
MOVEMENT_STATUS_NEWLY_AVAILABLE = "newly_available"
MOVEMENT_STATUS_DISAPPEARED = "disappeared"
MOVEMENT_STATUS_STILL_UNAVAILABLE = "still_unavailable"
MOVEMENT_STATUS_UNKNOWN = "unknown"
MOVEMENT_AVAILABILITY_STATES = frozenset(
    {
        MOVEMENT_STATUS_AVAILABLE,
        MOVEMENT_STATUS_NEWLY_AVAILABLE,
        MOVEMENT_STATUS_DISAPPEARED,
        MOVEMENT_STATUS_STILL_UNAVAILABLE,
        MOVEMENT_STATUS_UNKNOWN,
    }
)

MOVEMENT_CONTEXT_KEY = (
    "property_url",
    *DEDUPE_QUERY_CONTEXT_COLUMNS,
)
PRICE_MOVEMENT_COLUMNS = (
    "snapshot_date",
    "previous_snapshot_date",
    "property_url",
    "property_name",
    "property_type",
    "checkin",
    "checkout",
    "lead_time_days",
    "previous_lead_time_days",
    "stay_length_days",
    "adults",
    "children",
    "rooms",
    "currency",
    "market",
    "latitude",
    "longitude",
    "current_availability_status",
    "previous_availability_status",
    "availability_state",
    "current_price_per_night",
    "previous_price_per_night",
    "price_change_eur",
    "price_change_pct",
    "current_offer_count",
    "previous_offer_count",
    "is_subject",
)
PEER_MARKET_CONTEXT_COLUMNS = (
    "snapshot_date",
    *DEDUPE_QUERY_CONTEXT_COLUMNS,
)
PEER_MARKET_SUMMARY_COLUMNS = (
    "peer_property_count",
    "peer_available_property_count",
    "previous_peer_available_property_count",
    "current_peer_median_price_per_night",
    "previous_peer_median_price_per_night",
    "peer_median_change_eur",
    "peer_median_change_pct",
)
PEER_MARKET_MOVEMENT_COLUMNS = (
    *PRICE_MOVEMENT_COLUMNS,
    *PEER_MARKET_SUMMARY_COLUMNS,
    "price_gap_to_peer_median",
    "price_gap_to_peer_median_pct",
    "current_price_rank",
    "previous_price_rank",
    "price_rank_change",
)
MOVEMENT_SIGNAL_COLUMNS = (
    "market_pressure_label",
    "market_pressure_score",
    "reason_codes",
    "recommended_action",
    "rationale",
    "confidence",
    "confidence_flags",
)
SIGNALLED_PEER_MARKET_MOVEMENT_COLUMNS = (
    *PEER_MARKET_MOVEMENT_COLUMNS,
    *MOVEMENT_SIGNAL_COLUMNS,
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

REASON_MARKET_FIRMING = "market_firming"
REASON_MARKET_SOFTENING = "market_softening"
REASON_PROPERTY_SPECIFIC_INCREASE = "property_specific_increase"
REASON_PROPERTY_SPECIFIC_DISCOUNT = "property_specific_discount"
REASON_LEAD_TIME_COMPRESSION = "lead_time_compression"
REASON_AVAILABILITY_COMPRESSION = "availability_compression"
REASON_NEARBY_UNDERCUTTERS_DISCOUNTING = "nearby_undercutters_discounting"
REASON_PREMIUM_NOT_FEATURE_SUPPORTED = "premium_not_feature_supported"
REASON_POSSIBLE_PRICE_HEADROOM = "possible_price_headroom"
REASON_LOW_CONFIDENCE_LOW_HISTORY = "low_confidence_low_history"
REASON_EXTERNAL_COVARIATES_MISSING = "external_covariates_missing"
REASON_SEARCH_DEMAND_RISING = "search_demand_rising"
REASON_SEARCH_DEMAND_SOFTENING = "search_demand_softening"
REASON_HOLIDAY_OR_EVENT_PRESSURE = "holiday_or_event_pressure"
REASON_WEATHER_POSSIBLE_FACTOR = "weather_possible_factor"
MOVEMENT_REASON_CODES = frozenset(
    {
        REASON_MARKET_FIRMING,
        REASON_MARKET_SOFTENING,
        REASON_PROPERTY_SPECIFIC_INCREASE,
        REASON_PROPERTY_SPECIFIC_DISCOUNT,
        REASON_LEAD_TIME_COMPRESSION,
        REASON_AVAILABILITY_COMPRESSION,
        REASON_NEARBY_UNDERCUTTERS_DISCOUNTING,
        REASON_PREMIUM_NOT_FEATURE_SUPPORTED,
        REASON_POSSIBLE_PRICE_HEADROOM,
        REASON_LOW_CONFIDENCE_LOW_HISTORY,
        REASON_EXTERNAL_COVARIATES_MISSING,
        REASON_SEARCH_DEMAND_RISING,
        REASON_SEARCH_DEMAND_SOFTENING,
        REASON_HOLIDAY_OR_EVENT_PRESSURE,
        REASON_WEATHER_POSSIBLE_FACTOR,
    }
)

ACTION_HOLD = "Hold"
ACTION_INCREASE_TEST = "Increase test"
ACTION_DISCOUNT_TEST = "Discount test"
ACTION_WATCH = "Watch"
ACTION_NO_SIGNAL = "No signal"
MOVEMENT_ACTIONS = frozenset(
    {
        ACTION_HOLD,
        ACTION_INCREASE_TEST,
        ACTION_DISCOUNT_TEST,
        ACTION_WATCH,
        ACTION_NO_SIGNAL,
    }
)
CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"

MARKET_MOVE_PCT_THRESHOLD = 0.05
PROPERTY_SPECIFIC_MOVE_PCT_THRESHOLD = 0.05
PRICE_GAP_PCT_THRESHOLD = 0.10
HIGH_PREMIUM_PCT_THRESHOLD = 0.20
SEARCH_DEMAND_RISING_THRESHOLD = 65.0
SEARCH_DEMAND_SOFTENING_THRESHOLD = 35.0
HOT_WEATHER_TEMP_C_THRESHOLD = 32.0
RAIN_WEATHER_MM_THRESHOLD = 5.0
LOW_PEER_COVERAGE_THRESHOLD = 3

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
    *,
    nullable_columns: Iterable[str] = (),
) -> pd.DataFrame:
    out = frame.copy()
    nullable = set(nullable_columns)
    for column in columns:
        out[column] = pd.to_numeric(out[column], errors="coerce")
    bad = [column for column in columns if column not in nullable and out[column].isna().any()]
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
    out = _normalize_numeric_columns(
        out,
        OBSERVATION_NUMERIC_COLUMNS,
        label,
        nullable_columns=NUMERIC_CONTEXT_COLUMNS,
    )
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
    out = _normalize_numeric_columns(
        out,
        PRESENCE_NUMERIC_COLUMNS,
        label,
        nullable_columns=NUMERIC_CONTEXT_COLUMNS,
    )
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


def _filter_windows(frame: pd.DataFrame, windows: Iterable[dict[str, Any]] | None) -> pd.DataFrame:
    if not windows:
        return frame
    if frame.empty:
        return frame

    mask = pd.Series(False, index=frame.index)
    for window in windows:
        window_mask = pd.Series(True, index=frame.index)
        for raw_key, value in window.items():
            key = "crete_season" if raw_key == "season" else raw_key
            if value is None or key not in frame.columns:
                continue
            series = frame[key]
            if key in {"checkin", "checkout", "snapshot_date"}:
                comparable = pd.to_datetime(value).normalize()
                window_mask &= pd.to_datetime(series, errors="coerce").dt.normalize().eq(comparable)
            else:
                window_mask &= series.eq(value)
        mask |= window_mask
    return frame.loc[mask].copy()


def _filter_properties(
    frame: pd.DataFrame,
    *,
    subject_url: str | None,
    peer_property_urls: Iterable[str] | None,
) -> pd.DataFrame:
    property_urls = {url for url in ([subject_url] if subject_url else []) if url}
    property_urls.update(url for url in (peer_property_urls or []) if url)
    if not property_urls or frame.empty:
        return frame
    return frame.loc[frame["property_url"].isin(property_urls)].copy()


def _aggregate_observation_prices(observations: pd.DataFrame) -> pd.DataFrame:
    if observations.empty:
        return pd.DataFrame(
            columns=[
                "snapshot_date",
                *MOVEMENT_CONTEXT_KEY,
                "current_price_per_night",
                "current_offer_count",
            ]
        )

    grouped = observations.groupby(["snapshot_date", *MOVEMENT_CONTEXT_KEY], dropna=False)
    return (
        grouped.agg(
            current_price_per_night=("price_per_night", "median"),
            current_offer_count=("price_per_night", "size"),
        )
        .reset_index()
    )


def _presence_from_available_observations(observations: pd.DataFrame) -> pd.DataFrame:
    if observations.empty:
        return pd.DataFrame(columns=OFFER_PRESENCE_COLUMNS)

    grouped = observations.groupby(["snapshot_date", *MOVEMENT_CONTEXT_KEY], dropna=False)
    presence = (
        grouped.agg(
            captured_at=("captured_at", "max"),
            run_id=("run_id", "last"),
            property_name=("property_name", "last"),
            lead_time_days=("lead_time_days", "last"),
            stay_length_days=("stay_length_days", "last"),
            property_type=("property_type", "last"),
            latitude=("latitude", "last"),
            longitude=("longitude", "last"),
        )
        .reset_index()
    )
    presence["availability_status"] = AVAILABILITY_STATUS_AVAILABLE
    presence["failure_reason"] = None
    return presence.loc[:, list(OFFER_PRESENCE_COLUMNS)]


def _dedupe_presence_for_movement(presence: pd.DataFrame) -> pd.DataFrame:
    if presence.empty:
        return presence.loc[:, list(OFFER_PRESENCE_COLUMNS)]

    status_priority = {
        AVAILABILITY_STATUS_AVAILABLE: 0,
        AVAILABILITY_STATUS_NO_OFFER: 1,
        AVAILABILITY_STATUS_FAILED: 2,
    }
    out = presence.copy()
    out["_status_priority"] = out["availability_status"].map(status_priority)
    out = (
        out.sort_values(["snapshot_date", *MOVEMENT_CONTEXT_KEY, "_status_priority"])
        .drop_duplicates(subset=["snapshot_date", *MOVEMENT_CONTEXT_KEY], keep="first")
        .drop(columns=["_status_priority"])
        .reset_index(drop=True)
    )
    return out.loc[:, list(OFFER_PRESENCE_COLUMNS)]


def _availability_state(current: object, previous: object) -> str:
    if pd.isna(previous) or current == AVAILABILITY_STATUS_FAILED or previous == AVAILABILITY_STATUS_FAILED:
        return MOVEMENT_STATUS_UNKNOWN
    if current == AVAILABILITY_STATUS_AVAILABLE and previous == AVAILABILITY_STATUS_AVAILABLE:
        return MOVEMENT_STATUS_AVAILABLE
    if current == AVAILABILITY_STATUS_AVAILABLE and previous == AVAILABILITY_STATUS_NO_OFFER:
        return MOVEMENT_STATUS_NEWLY_AVAILABLE
    if current == AVAILABILITY_STATUS_NO_OFFER and previous == AVAILABILITY_STATUS_AVAILABLE:
        return MOVEMENT_STATUS_DISAPPEARED
    if current == AVAILABILITY_STATUS_NO_OFFER and previous == AVAILABILITY_STATUS_NO_OFFER:
        return MOVEMENT_STATUS_STILL_UNAVAILABLE
    return MOVEMENT_STATUS_UNKNOWN


def build_price_movement_table(
    observations: pd.DataFrame,
    presence: pd.DataFrame,
    subject_url: str | None,
    windows: Iterable[dict[str, Any]] | None,
    peer_property_urls: Iterable[str] | None,
) -> pd.DataFrame:
    """Compare each snapshot with the previous matching property/window context.

    Offer rows are collapsed to the property's median available EUR/night within
    each snapshot and searched stay window. Availability transitions come from
    explicit presence rows; observations only contribute explicit ``available``
    presence when the presence store is absent.
    """

    normalized_observations = normalize_price_observations(observations)
    if presence.empty and not normalized_observations.empty:
        normalized_presence = normalize_offer_presence(
            _presence_from_available_observations(normalized_observations)
        )
    else:
        normalized_presence = normalize_offer_presence(presence)

    normalized_observations = _filter_windows(normalized_observations, windows)
    normalized_presence = _filter_windows(normalized_presence, windows)
    normalized_observations = _filter_properties(
        normalized_observations,
        subject_url=subject_url,
        peer_property_urls=peer_property_urls,
    )
    normalized_presence = _filter_properties(
        normalized_presence,
        subject_url=subject_url,
        peer_property_urls=peer_property_urls,
    )

    if normalized_presence.empty:
        empty = pd.DataFrame(columns=PRICE_MOVEMENT_COLUMNS)
        empty.attrs["low_history"] = movement_history_status(
            normalized_observations,
            normalized_presence,
        )
        return empty

    prices = _aggregate_observation_prices(normalized_observations)
    current = _dedupe_presence_for_movement(normalized_presence).merge(
        prices,
        on=["snapshot_date", *MOVEMENT_CONTEXT_KEY],
        how="left",
    )
    current = current.sort_values(["property_url", *DEDUPE_QUERY_CONTEXT_COLUMNS, "snapshot_date"])

    previous_columns = [
        "snapshot_date",
        "lead_time_days",
        "availability_status",
        "current_price_per_night",
        "current_offer_count",
    ]
    grouped = current.groupby(list(MOVEMENT_CONTEXT_KEY), dropna=False, sort=False)
    for column in previous_columns:
        current[f"previous_{column}"] = grouped[column].shift(1)

    current["availability_state"] = [
        _availability_state(current_status, previous_status)
        for current_status, previous_status in zip(
            current["availability_status"],
            current["previous_availability_status"],
            strict=True,
        )
    ]
    current["price_change_eur"] = (
        current["current_price_per_night"] - current["previous_current_price_per_night"]
    )
    current["price_change_pct"] = (
        current["price_change_eur"] / current["previous_current_price_per_night"]
    )
    unavailable = current["availability_state"] != MOVEMENT_STATUS_AVAILABLE
    current.loc[unavailable, ["price_change_eur", "price_change_pct"]] = pd.NA
    current["is_subject"] = current["property_url"].eq(subject_url) if subject_url else False

    movement = pd.DataFrame(
        {
            "snapshot_date": current["snapshot_date"],
            "previous_snapshot_date": current["previous_snapshot_date"],
            "property_url": current["property_url"],
            "property_name": current["property_name"],
            "property_type": current["property_type"],
            "checkin": current["checkin"],
            "checkout": current["checkout"],
            "lead_time_days": current["lead_time_days"],
            "previous_lead_time_days": current["previous_lead_time_days"],
            "stay_length_days": current["stay_length_days"],
            "adults": current["adults"],
            "children": current["children"],
            "rooms": current["rooms"],
            "currency": current["currency"],
            "market": current["market"],
            "latitude": current["latitude"],
            "longitude": current["longitude"],
            "current_availability_status": current["availability_status"],
            "previous_availability_status": current["previous_availability_status"],
            "availability_state": current["availability_state"],
            "current_price_per_night": current["current_price_per_night"],
            "previous_price_per_night": current["previous_current_price_per_night"],
            "price_change_eur": current["price_change_eur"],
            "price_change_pct": current["price_change_pct"],
            "current_offer_count": current["current_offer_count"],
            "previous_offer_count": current["previous_current_offer_count"],
            "is_subject": current["is_subject"],
        },
        columns=PRICE_MOVEMENT_COLUMNS,
    ).reset_index(drop=True)
    movement.attrs["low_history"] = movement_history_status(
        normalized_observations,
        normalized_presence,
    )
    return movement


def select_movement_peers(
    subject_url: str,
    modelling_frame: pd.DataFrame,
    *,
    max_peers: int = 25,
    w_geo: float = 0.5,
    w_sim: float = 0.5,
    max_distance_km: float = 8.0,
    include_guest_house: bool = False,
) -> pd.DataFrame:
    """Return Phase 2 comparable peers to use for movement monitoring."""

    return rank_competitors(
        subject_url,
        modelling_frame,
        w_geo=w_geo,
        w_sim=w_sim,
        k=max_peers,
        max_distance_km=max_distance_km,
        include_guest_house=include_guest_house,
    )


def add_peer_market_context(movement: pd.DataFrame) -> pd.DataFrame:
    """Add property-weighted peer medians and price-rank movement to rows."""

    _require_columns(movement, PRICE_MOVEMENT_COLUMNS, "price movement")
    if movement.empty:
        empty = pd.DataFrame(columns=PEER_MARKET_MOVEMENT_COLUMNS)
        empty.attrs.update(movement.attrs)
        return empty

    out = movement.copy()
    context_columns = [column for column in PEER_MARKET_CONTEXT_COLUMNS if column in out.columns]
    peer_rows = out.loc[~out["is_subject"].astype(bool)].copy()

    if peer_rows.empty:
        market = pd.DataFrame(columns=[*context_columns, *PEER_MARKET_SUMMARY_COLUMNS])
    else:
        grouped = peer_rows.groupby(context_columns, dropna=False)
        market = (
            grouped.agg(
                peer_property_count=("property_url", "nunique"),
                peer_available_property_count=(
                    "current_price_per_night",
                    lambda values: int(pd.to_numeric(values, errors="coerce").notna().sum()),
                ),
                previous_peer_available_property_count=(
                    "previous_price_per_night",
                    lambda values: int(pd.to_numeric(values, errors="coerce").notna().sum()),
                ),
                current_peer_median_price_per_night=("current_price_per_night", "median"),
                previous_peer_median_price_per_night=("previous_price_per_night", "median"),
            )
            .reset_index()
        )
        market["peer_median_change_eur"] = (
            market["current_peer_median_price_per_night"]
            - market["previous_peer_median_price_per_night"]
        )
        market["peer_median_change_pct"] = (
            market["peer_median_change_eur"] / market["previous_peer_median_price_per_night"]
        )

    out = out.merge(market, on=context_columns, how="left")
    out["price_gap_to_peer_median"] = (
        out["current_price_per_night"] - out["current_peer_median_price_per_night"]
    )
    out["price_gap_to_peer_median_pct"] = (
        out["price_gap_to_peer_median"] / out["current_peer_median_price_per_night"]
    )
    out["current_price_rank"] = out.groupby(context_columns, dropna=False)[
        "current_price_per_night"
    ].rank(method="min", ascending=False)
    out["previous_price_rank"] = out.groupby(context_columns, dropna=False)[
        "previous_price_per_night"
    ].rank(method="min", ascending=False)
    out["price_rank_change"] = out["previous_price_rank"] - out["current_price_rank"]
    return out.loc[:, list(PEER_MARKET_MOVEMENT_COLUMNS)].reset_index(drop=True)


def _is_missing(value: object) -> bool:
    if value is None or value is pd.NA:
        return True
    try:
        missing = pd.isna(value)
    except TypeError:
        return False
    return bool(missing) if isinstance(missing, bool) else False


def _as_float(value: object) -> float | None:
    if _is_missing(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: object) -> int | None:
    number = _as_float(value)
    return None if number is None else int(number)


def _row_get(row: pd.Series | dict[str, Any], key: str, default: object = None) -> object:
    if isinstance(row, pd.Series):
        return row.get(key, default)
    return row.get(key, default)


def _append_reason(codes: list[str], code: str) -> None:
    if code not in codes:
        codes.append(code)


def _market_context_from_row(row: pd.Series | dict[str, Any]) -> dict[str, Any]:
    change_pct = _as_float(_row_get(row, "peer_median_change_pct"))
    current_median = _as_float(_row_get(row, "current_peer_median_price_per_night"))
    previous_median = _as_float(_row_get(row, "previous_peer_median_price_per_night"))
    if change_pct is None and current_median is not None and previous_median not in {None, 0.0}:
        change_pct = (current_median - previous_median) / previous_median

    peer_available = _as_int(_row_get(row, "peer_available_property_count"))
    previous_peer_available = _as_int(_row_get(row, "previous_peer_available_property_count"))
    availability_delta = None
    if peer_available is not None and previous_peer_available is not None:
        availability_delta = peer_available - previous_peer_available

    if change_pct is None:
        label = "insufficient_history"
        score = 0.0
    elif change_pct >= MARKET_MOVE_PCT_THRESHOLD:
        label = "firming"
        score = change_pct * 100.0
    elif change_pct <= -MARKET_MOVE_PCT_THRESHOLD:
        label = "softening"
        score = change_pct * 100.0
    else:
        label = "stable"
        score = change_pct * 100.0

    if availability_delta is not None and availability_delta < 0:
        score += min(10.0, abs(float(availability_delta)) * 2.0)

    return {
        "status": HISTORY_STATUS_READY if change_pct is not None else HISTORY_STATUS_LOW_HISTORY,
        "market_pressure_label": label,
        "market_pressure_score": round(max(-100.0, min(100.0, score)), 2),
        "peer_median_change_pct": change_pct,
        "peer_median_change_eur": _as_float(_row_get(row, "peer_median_change_eur")),
        "current_peer_median_price_per_night": current_median,
        "previous_peer_median_price_per_night": previous_median,
        "peer_property_count": _as_int(_row_get(row, "peer_property_count")),
        "peer_available_property_count": peer_available,
        "previous_peer_available_property_count": previous_peer_available,
        "availability_delta": availability_delta,
    }


def market_pressure_index(movements: pd.DataFrame) -> dict[str, Any]:
    """Summarize the latest peer-market movement in a dashboard-ready dict.

    The index is deliberately transparent: it is the peer median percent move,
    expressed as points, with a small positive bump when peer availability has
    compressed. It is not a demand model.
    """

    if movements.empty:
        return {
            "status": HISTORY_STATUS_LOW_HISTORY,
            "market_pressure_label": "insufficient_history",
            "market_pressure_score": 0.0,
            "snapshot_date": None,
            "message": "No movement rows are available.",
        }

    if "snapshot_date" not in movements:
        raise MovementHistoryError("price movement is missing required columns: snapshot_date")

    snapshot_dates = pd.to_datetime(movements["snapshot_date"], errors="coerce")
    if snapshot_dates.isna().all():
        raise MovementHistoryError("price movement has no valid snapshot_date values")
    latest_snapshot = snapshot_dates.max().normalize()
    latest_rows = movements.loc[snapshot_dates.dt.normalize().eq(latest_snapshot)]
    if "is_subject" in latest_rows:
        subject_rows = latest_rows.loc[latest_rows["is_subject"].astype(bool)]
    else:
        subject_rows = latest_rows.iloc[0:0]
    row = (subject_rows if not subject_rows.empty else latest_rows).iloc[0]
    context = _market_context_from_row(row)
    context.update(
        {
            "snapshot_date": latest_snapshot,
            "previous_snapshot_date": _row_get(row, "previous_snapshot_date"),
            "subject_url": _row_get(row, "property_url"),
            "subject_price_change_pct": _as_float(_row_get(row, "price_change_pct")),
            "subject_price_change_eur": _as_float(_row_get(row, "price_change_eur")),
            "price_gap_to_peer_median_pct": _as_float(
                _row_get(row, "price_gap_to_peer_median_pct")
            ),
            "message": (
                "Peer market is "
                f"{context['market_pressure_label']} "
                f"({context['market_pressure_score']:.1f} index points)."
            ),
        }
    )
    return context


def _covariate_row_for_context(
    row: pd.Series | dict[str, Any],
    covariates: pd.DataFrame | None,
) -> pd.Series | None:
    if covariates is None or covariates.empty:
        return None
    _require_columns(covariates, DEMAND_COVARIATE_REQUIRED_COLUMNS, "demand covariates")
    checkin = pd.to_datetime(_row_get(row, "checkin"), errors="coerce")
    market = _row_get(row, "market")
    if pd.isna(checkin) or _is_missing(market):
        return None
    checkins = pd.to_datetime(covariates["checkin"], errors="coerce").dt.normalize()
    matches = covariates.loc[
        checkins.eq(checkin.normalize()) & covariates["market"].astype(str).eq(str(market))
    ]
    if matches.empty:
        return None
    return matches.iloc[-1]


def movement_confidence_flags(
    row: pd.Series | dict[str, Any],
    market_context: dict[str, Any] | None = None,
    covariates: pd.DataFrame | None = None,
) -> list[str]:
    """Return deterministic warnings that qualify a movement action."""

    context = market_context or _market_context_from_row(row)
    flags: list[str] = []
    if context.get("status") != HISTORY_STATUS_READY:
        flags.append("low_history")
    if _is_missing(_row_get(row, "previous_snapshot_date")):
        flags.append("missing_previous_snapshot")
    if _row_get(row, "availability_state") != MOVEMENT_STATUS_AVAILABLE:
        flags.append("availability_not_comparable")
    peer_count = _as_int(context.get("peer_property_count"))
    if peer_count is None or peer_count < LOW_PEER_COVERAGE_THRESHOLD:
        flags.append("low_peer_coverage")
    if (
        _as_float(context.get("current_peer_median_price_per_night")) is None
        or _as_float(context.get("previous_peer_median_price_per_night")) is None
    ):
        flags.append("missing_peer_market_median")
    if _covariate_row_for_context(row, covariates) is None:
        flags.append(REASON_EXTERNAL_COVARIATES_MISSING)
    return flags


def _confidence_from_flags(flags: Iterable[str]) -> str:
    flag_set = set(flags)
    low_flags = {
        "low_history",
        "missing_previous_snapshot",
        "availability_not_comparable",
        "missing_peer_market_median",
    }
    if flag_set & low_flags:
        return CONFIDENCE_LOW
    medium_flags = {"low_peer_coverage", REASON_EXTERNAL_COVARIATES_MISSING}
    if flag_set & medium_flags:
        return CONFIDENCE_MEDIUM
    return CONFIDENCE_HIGH


def movement_reason_codes(
    row: pd.Series | dict[str, Any],
    market_context: dict[str, Any] | None = None,
    covariates: pd.DataFrame | None = None,
) -> list[str]:
    """Return transparent v1 reason codes for a movement row.

    Covariates only add labels; they never change the price movement math.
    """

    context = market_context or _market_context_from_row(row)
    codes: list[str] = []
    market_change = _as_float(context.get("peer_median_change_pct"))
    property_change = _as_float(_row_get(row, "price_change_pct"))
    gap_to_peer = _as_float(_row_get(row, "price_gap_to_peer_median_pct"))

    if market_change is not None and market_change >= MARKET_MOVE_PCT_THRESHOLD:
        _append_reason(codes, REASON_MARKET_FIRMING)
    if market_change is not None and market_change <= -MARKET_MOVE_PCT_THRESHOLD:
        _append_reason(codes, REASON_MARKET_SOFTENING)

    if property_change is not None:
        relative_change = property_change - (market_change or 0.0)
        if (
            property_change >= PROPERTY_SPECIFIC_MOVE_PCT_THRESHOLD
            and relative_change >= PROPERTY_SPECIFIC_MOVE_PCT_THRESHOLD
        ):
            _append_reason(codes, REASON_PROPERTY_SPECIFIC_INCREASE)
        if (
            property_change <= -PROPERTY_SPECIFIC_MOVE_PCT_THRESHOLD
            and relative_change <= -PROPERTY_SPECIFIC_MOVE_PCT_THRESHOLD
        ):
            _append_reason(codes, REASON_PROPERTY_SPECIFIC_DISCOUNT)

    lead_time = _as_int(_row_get(row, "lead_time_days"))
    previous_lead_time = _as_int(_row_get(row, "previous_lead_time_days"))
    if lead_time is not None and previous_lead_time is not None and lead_time < previous_lead_time:
        _append_reason(codes, REASON_LEAD_TIME_COMPRESSION)

    availability_delta = _as_int(context.get("availability_delta"))
    if availability_delta is not None and availability_delta < 0:
        _append_reason(codes, REASON_AVAILABILITY_COMPRESSION)

    if (
        market_change is not None
        and market_change <= -MARKET_MOVE_PCT_THRESHOLD
        and gap_to_peer is not None
        and gap_to_peer > PRICE_GAP_PCT_THRESHOLD
    ):
        _append_reason(codes, REASON_NEARBY_UNDERCUTTERS_DISCOUNTING)

    if gap_to_peer is not None and gap_to_peer >= HIGH_PREMIUM_PCT_THRESHOLD:
        _append_reason(codes, REASON_PREMIUM_NOT_FEATURE_SUPPORTED)
    if (
        gap_to_peer is not None
        and gap_to_peer <= -PRICE_GAP_PCT_THRESHOLD
        and market_change is not None
        and market_change >= MARKET_MOVE_PCT_THRESHOLD
    ):
        _append_reason(codes, REASON_POSSIBLE_PRICE_HEADROOM)

    covariate = _covariate_row_for_context(row, covariates)
    if covariate is None:
        _append_reason(codes, REASON_EXTERNAL_COVARIATES_MISSING)
    else:
        trends = _as_float(covariate.get("google_trends_index"))
        if trends is not None and trends >= SEARCH_DEMAND_RISING_THRESHOLD:
            _append_reason(codes, REASON_SEARCH_DEMAND_RISING)
        if trends is not None and trends <= SEARCH_DEMAND_SOFTENING_THRESHOLD:
            _append_reason(codes, REASON_SEARCH_DEMAND_SOFTENING)
        if bool(covariate.get("holiday_flag")) or bool(covariate.get("event_flag")):
            _append_reason(codes, REASON_HOLIDAY_OR_EVENT_PRESSURE)
        temperature = _as_float(covariate.get("weather_temp_c"))
        rain = _as_float(covariate.get("weather_rain_mm"))
        if (
            temperature is not None
            and temperature >= HOT_WEATHER_TEMP_C_THRESHOLD
            or rain is not None
            and rain >= RAIN_WEATHER_MM_THRESHOLD
        ):
            _append_reason(codes, REASON_WEATHER_POSSIBLE_FACTOR)

    flags = movement_confidence_flags(row, context, covariates)
    confidence = _confidence_from_flags(flags)
    if confidence == CONFIDENCE_LOW:
        _append_reason(codes, REASON_LOW_CONFIDENCE_LOW_HISTORY)
    return codes


def movement_action_payload(
    row: pd.Series | dict[str, Any],
    market_context: dict[str, Any] | None = None,
    covariates: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Return the v1 recommended action, rationale, confidence, and flags."""

    context = market_context or _market_context_from_row(row)
    codes = movement_reason_codes(row, context, covariates)
    flags = movement_confidence_flags(row, context, covariates)
    confidence = _confidence_from_flags(flags)

    if confidence == CONFIDENCE_LOW:
        if _row_get(row, "availability_state") != MOVEMENT_STATUS_AVAILABLE:
            action = ACTION_NO_SIGNAL
            rationale = "Availability or scrape status prevents a comparable price-move signal."
        else:
            action = ACTION_WATCH
            rationale = "Movement history or peer coverage is too thin for a price test."
    elif (
        REASON_NEARBY_UNDERCUTTERS_DISCOUNTING in codes
        or REASON_PREMIUM_NOT_FEATURE_SUPPORTED in codes
    ):
        action = ACTION_DISCOUNT_TEST
        rationale = "Peers are softening or undercutting while the subject sits above peer median."
    elif (
        REASON_POSSIBLE_PRICE_HEADROOM in codes
        and REASON_PROPERTY_SPECIFIC_INCREASE not in codes
    ):
        action = ACTION_INCREASE_TEST
        rationale = "The subject is below comparable peer median while peer-market prices are firming."
    elif (
        REASON_MARKET_FIRMING in codes
        or REASON_SEARCH_DEMAND_RISING in codes
        or REASON_HOLIDAY_OR_EVENT_PRESSURE in codes
    ):
        action = ACTION_HOLD
        rationale = "Market context is supportive but does not show clear incremental price headroom."
    elif REASON_MARKET_SOFTENING in codes or REASON_SEARCH_DEMAND_SOFTENING in codes:
        action = ACTION_WATCH
        rationale = "Peer-market context is softening; wait for a clearer discount signal."
    else:
        action = ACTION_NO_SIGNAL
        rationale = "No deterministic movement rule crossed its action threshold."

    return {
        "recommended_action": action,
        "rationale": rationale,
        "confidence": confidence,
        "confidence_flags": flags,
        "reason_codes": codes,
        "market_pressure_label": context["market_pressure_label"],
        "market_pressure_score": context["market_pressure_score"],
    }


def add_movement_signals(
    movement: pd.DataFrame,
    covariates: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Add reason codes and action payload columns to peer movement rows."""

    if movement.empty:
        empty = movement.copy()
        for column in MOVEMENT_SIGNAL_COLUMNS:
            empty[column] = pd.Series(dtype="object")
        empty.attrs.update(movement.attrs)
        return empty

    out = movement.copy()
    payloads = [
        movement_action_payload(row, _market_context_from_row(row), covariates)
        for _, row in out.iterrows()
    ]
    for column in MOVEMENT_SIGNAL_COLUMNS:
        out[column] = [payload[column] for payload in payloads]

    out.attrs.update(movement.attrs)
    columns = (
        list(SIGNALLED_PEER_MARKET_MOVEMENT_COLUMNS)
        if set(PEER_MARKET_MOVEMENT_COLUMNS).issubset(out.columns)
        else list(out.columns)
    )
    return out.loc[:, columns].reset_index(drop=True)


def build_peer_market_movement_table(
    observations: pd.DataFrame,
    presence: pd.DataFrame,
    modelling_frame: pd.DataFrame,
    subject_url: str,
    windows: Iterable[dict[str, Any]] | None,
    *,
    max_peers: int = 25,
    w_geo: float = 0.5,
    w_sim: float = 0.5,
    max_distance_km: float = 8.0,
    include_guest_house: bool = False,
    covariates: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build movement rows with comparable-peer market medians and rank changes."""

    peers = select_movement_peers(
        subject_url,
        modelling_frame,
        max_peers=max_peers,
        w_geo=w_geo,
        w_sim=w_sim,
        max_distance_km=max_distance_km,
        include_guest_house=include_guest_house,
    )
    peer_property_urls = peers["property_url"].tolist() if not peers.empty else []
    movement = build_price_movement_table(
        observations,
        presence,
        subject_url=subject_url,
        windows=windows,
        peer_property_urls=peer_property_urls,
    )
    enriched = add_peer_market_context(movement)
    enriched = add_movement_signals(enriched, covariates)
    enriched.attrs.update(movement.attrs)
    enriched.attrs["peer_property_urls"] = peer_property_urls
    enriched.attrs["peer_count"] = len(peer_property_urls)
    return enriched


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
