"""Deterministic exploratory summaries for the modelling table."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tourism_pricing_analytics.analysis.segment import (
    property_type_counts,
    segment_self_catering,
)

SUMMARY_PRICE_COLUMNS = (
    "current_price_value",
    "price_per_night",
    "room_size_sqm",
    "review_score",
    "review_count",
)


def _json_ready(value: Any) -> Any:
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def _date_bound(series: pd.Series, method: str) -> str | None:
    parsed = pd.to_datetime(series, errors="coerce").dropna()
    if parsed.empty:
        return None
    value = parsed.min() if method == "min" else parsed.max()
    return value.date().isoformat()


def numeric_distribution(frame: pd.DataFrame, column: str) -> dict[str, float | int | None]:
    """Return a compact distribution summary for one numeric column."""

    values = pd.to_numeric(frame[column], errors="coerce") if column in frame else pd.Series(dtype=float)
    values = values.dropna()
    if values.empty:
        return {
            "count": 0,
            "min": None,
            "p25": None,
            "median": None,
            "mean": None,
            "p75": None,
            "p90": None,
            "max": None,
        }

    quantiles = values.quantile([0.25, 0.5, 0.75, 0.9])
    return {
        "count": int(values.shape[0]),
        "min": float(values.min()),
        "p25": float(quantiles.loc[0.25]),
        "median": float(quantiles.loc[0.5]),
        "mean": float(values.mean()),
        "p75": float(quantiles.loc[0.75]),
        "p90": float(quantiles.loc[0.9]),
        "max": float(values.max()),
    }


def missing_share(frame: pd.DataFrame, columns: tuple[str, ...]) -> dict[str, float | None]:
    """Return null shares for selected columns, rounded for stable reporting."""

    if frame.empty:
        return {column: None for column in columns}
    return {
        column: round(float(frame[column].isna().mean()), 4) if column in frame else None
        for column in columns
    }


def modelling_table_summary(
    frame: pd.DataFrame,
    *,
    include_guest_house: bool = False,
) -> dict[str, Any]:
    """Return a JSON-serializable EDA summary for the modelling table."""

    self_catering = segment_self_catering(
        frame,
        include_guest_house=include_guest_house,
    )
    lead_times = sorted(_json_ready(value) for value in frame["lead_time_days"].dropna().unique())
    stay_lengths = sorted(_json_ready(value) for value in frame["stay_length_days"].dropna().unique())

    return {
        "rows": int(frame.shape[0]),
        "columns": int(frame.shape[1]),
        "properties": int(frame["property_url"].nunique(dropna=True)),
        "rooms": int(
            frame.dropna(subset=["room_id"])[["property_url", "room_id"]]
            .drop_duplicates()
            .shape[0]
        )
        if "room_id" in frame
        else None,
        "rate_blocks": int(frame["block_id"].nunique(dropna=True)),
        "checkin_min": _date_bound(frame["checkin"], "min"),
        "checkin_max": _date_bound(frame["checkin"], "max"),
        "lead_time_days": lead_times,
        "stay_length_days": stay_lengths,
        "property_type_counts": property_type_counts(frame),
        "self_catering": {
            "include_guest_house": include_guest_house,
            "rows": int(self_catering.shape[0]),
            "properties": int(self_catering["property_url"].nunique(dropna=True)),
            "property_type_counts": property_type_counts(self_catering),
            "price_per_night": numeric_distribution(self_catering, "price_per_night"),
        },
        "missing_share": missing_share(
            frame,
            (
                "room_id",
                "room_size_sqm",
                "bed_count",
                "star_rating",
                "review_score",
                "latitude",
                "longitude",
            ),
        ),
        "numeric": {
            column: numeric_distribution(frame, column)
            for column in SUMMARY_PRICE_COLUMNS
        },
    }
