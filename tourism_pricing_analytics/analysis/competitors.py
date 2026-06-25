"""Comparable-set benchmarking for self-catering price analysis."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Iterable

import pandas as pd

from tourism_pricing_analytics.analysis.segment import segment_self_catering

EARTH_RADIUS_KM = 6371.0088

FEATURE_COMPONENT_WEIGHTS = {
    "property_type_similarity": 0.25,
    "room_size_similarity": 0.20,
    "review_score_similarity": 0.20,
    "star_rating_similarity": 0.15,
    "facility_similarity": 0.20,
}


class ComparableBenchmarkError(ValueError):
    """Raised when a comparable benchmark cannot be produced."""


@dataclass(frozen=True)
class ComparableBenchmarkConfig:
    """Controls comparable-set selection and price coverage flags."""

    max_peers: int = 25
    min_peers: int = 5
    max_distance_km: float = 8.0
    min_peer_price_rows: int = 10
    distance_weight: float = 0.5
    feature_weight: float = 0.5
    context_columns: tuple[str, ...] = (
        "checkin",
        "lead_time_days",
        "stay_length_days",
    )

    def __post_init__(self) -> None:
        if self.max_peers <= 0:
            raise ComparableBenchmarkError("max_peers must be positive")
        if self.min_peers < 0:
            raise ComparableBenchmarkError("min_peers cannot be negative")
        if self.max_distance_km <= 0:
            raise ComparableBenchmarkError("max_distance_km must be positive")
        if self.min_peer_price_rows < 0:
            raise ComparableBenchmarkError("min_peer_price_rows cannot be negative")
        if self.distance_weight < 0 or self.feature_weight < 0:
            raise ComparableBenchmarkError("similarity weights cannot be negative")
        if self.distance_weight + self.feature_weight <= 0:
            raise ComparableBenchmarkError("at least one similarity weight must be positive")


def haversine_km(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    """Return the great-circle distance between two coordinates in kilometers."""

    lat_a = math.radians(latitude_a)
    lon_a = math.radians(longitude_a)
    lat_b = math.radians(latitude_b)
    lon_b = math.radians(longitude_b)
    d_lat = lat_b - lat_a
    d_lon = lon_b - lon_a

    hav = (
        math.sin(d_lat / 2.0) ** 2
        + math.cos(lat_a) * math.cos(lat_b) * math.sin(d_lon / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_KM * math.asin(math.sqrt(hav))


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return value is pd.NA


def _clean_text(value: object) -> str | None:
    if _is_missing(value):
        return None
    text = str(value).strip()
    return text or None


def _mode_text(series: pd.Series) -> str | None:
    values = [_clean_text(value) for value in series.tolist()]
    values = [value for value in values if value is not None]
    if not values:
        return None
    counts = pd.Series(values).value_counts()
    return str(sorted(counts.index, key=lambda item: (-int(counts[item]), str(item)))[0])


def _median_numeric(series: pd.Series) -> float | None:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return None
    return float(values.median())


def _normalize_token(value: object) -> str | None:
    text = _clean_text(value)
    if text is None:
        return None
    return " ".join(text.casefold().split())


def _tokens_from_value(value: object) -> set[str]:
    if _is_missing(value):
        return set()
    if isinstance(value, dict):
        tokens: set[str] = set()
        for key, item in value.items():
            key_token = _normalize_token(key)
            if key_token is not None:
                tokens.add(key_token)
            if isinstance(item, (list, tuple, set, dict)):
                tokens.update(_tokens_from_value(item))
            else:
                item_token = _normalize_token(item)
                if item_token is not None:
                    tokens.add(item_token)
        return tokens
    if isinstance(value, (list, tuple, set, frozenset)):
        tokens = set()
        for item in value:
            tokens.update(_tokens_from_value(item))
        return tokens
    token = _normalize_token(value)
    return {token} if token is not None else set()


def _feature_tokens(rows: pd.DataFrame) -> frozenset[str]:
    tokens: set[str] = set()
    for column in ("amenities", "property_facilities"):
        if column not in rows:
            continue
        for value in rows[column].tolist():
            tokens.update(_tokens_from_value(value))
    return frozenset(tokens)


def _numeric_similarity(
    subject_value: float | None,
    candidate_value: float | None,
    scale: float | None = None,
) -> float | None:
    if subject_value is None or candidate_value is None:
        return None
    if scale is None:
        scale = max(abs(subject_value), abs(candidate_value), 1.0)
    if scale <= 0:
        return None
    return max(0.0, 1.0 - min(abs(subject_value - candidate_value) / scale, 1.0))


def _jaccard_similarity(subject_tokens: Iterable[str], candidate_tokens: Iterable[str]) -> float | None:
    subject = set(subject_tokens)
    candidate = set(candidate_tokens)
    if not subject or not candidate:
        return None
    return len(subject & candidate) / len(subject | candidate)


def _weighted_feature_similarity(
    subject: pd.Series,
    candidate: pd.Series,
) -> tuple[float, dict[str, float | None]]:
    components = {
        "property_type_similarity": None,
        "room_size_similarity": _numeric_similarity(
            subject["median_room_size_sqm"],
            candidate["median_room_size_sqm"],
        ),
        "review_score_similarity": _numeric_similarity(
            subject["median_review_score"],
            candidate["median_review_score"],
            scale=10.0,
        ),
        "star_rating_similarity": _numeric_similarity(
            subject["median_star_rating"],
            candidate["median_star_rating"],
            scale=5.0,
        ),
        "facility_similarity": _jaccard_similarity(
            subject["feature_tokens"],
            candidate["feature_tokens"],
        ),
    }

    if subject["property_type"] is not None and candidate["property_type"] is not None:
        components["property_type_similarity"] = (
            1.0 if subject["property_type"] == candidate["property_type"] else 0.0
        )

    weighted_total = 0.0
    weight_sum = 0.0
    for component, weight in FEATURE_COMPONENT_WEIGHTS.items():
        value = components[component]
        if value is None:
            continue
        weighted_total += value * weight
        weight_sum += weight
    similarity = weighted_total / weight_sum if weight_sum else 0.0
    return similarity, components


def _round_or_none(value: object, digits: int = 4) -> float | int | str | None:
    if _is_missing(value):
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value, digits)
    if hasattr(value, "item"):
        return _round_or_none(value.item(), digits=digits)
    return str(value)


def _price_distribution(values: pd.Series) -> dict[str, float | int | None]:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty:
        return {
            "count": 0,
            "min": None,
            "p10": None,
            "p25": None,
            "median": None,
            "mean": None,
            "p75": None,
            "p90": None,
            "max": None,
        }

    quantiles = numeric.quantile([0.10, 0.25, 0.50, 0.75, 0.90])
    return {
        "count": int(numeric.shape[0]),
        "min": float(numeric.min()),
        "p10": float(quantiles.loc[0.10]),
        "p25": float(quantiles.loc[0.25]),
        "median": float(quantiles.loc[0.50]),
        "mean": float(numeric.mean()),
        "p75": float(quantiles.loc[0.75]),
        "p90": float(quantiles.loc[0.90]),
        "max": float(numeric.max()),
    }


def _percentile_rank(value: float | None, peer_values: pd.Series) -> float | None:
    if value is None:
        return None
    numeric = pd.to_numeric(peer_values, errors="coerce").dropna()
    if numeric.empty:
        return None
    return round(float((numeric <= value).mean() * 100.0), 2)


def build_property_profiles(frame: pd.DataFrame) -> pd.DataFrame:
    """Return one deterministic profile row per property in ``frame``."""

    required_columns = {"property_url", "property_name", "latitude", "longitude"}
    missing = sorted(required_columns - set(frame.columns))
    if missing:
        raise ComparableBenchmarkError(f"Missing required columns: {', '.join(missing)}")

    profiles = []
    for property_url, rows in frame.groupby("property_url", sort=True):
        if _clean_text(property_url) is None:
            continue
        profile = {
            "property_url": str(property_url),
            "property_name": _mode_text(rows["property_name"]),
            "property_type": _mode_text(rows["property_type"]) if "property_type" in rows else None,
            "latitude": _median_numeric(rows["latitude"]),
            "longitude": _median_numeric(rows["longitude"]),
            "median_price_per_night": _median_numeric(rows["price_per_night"])
            if "price_per_night" in rows
            else None,
            "price_row_count": int(rows.shape[0]),
            "room_count": int(rows["room_id"].nunique(dropna=True)) if "room_id" in rows else None,
            "median_room_size_sqm": _median_numeric(rows["room_size_sqm"])
            if "room_size_sqm" in rows
            else None,
            "median_review_score": _median_numeric(rows["review_score"])
            if "review_score" in rows
            else None,
            "median_review_count": _median_numeric(rows["review_count"])
            if "review_count" in rows
            else None,
            "median_star_rating": _median_numeric(rows["star_rating"])
            if "star_rating" in rows
            else None,
            "feature_tokens": _feature_tokens(rows),
        }
        profiles.append(profile)

    return pd.DataFrame(profiles).sort_values("property_url").reset_index(drop=True)


def build_comparable_candidates(
    frame: pd.DataFrame,
    subject_property_url: str,
    config: ComparableBenchmarkConfig | None = None,
) -> pd.DataFrame:
    """Score candidate peer properties against one subject property."""

    config = config or ComparableBenchmarkConfig()
    profiles = build_property_profiles(frame)
    subject_matches = profiles.loc[profiles["property_url"] == subject_property_url]
    if subject_matches.empty:
        raise ComparableBenchmarkError(f"Subject property not found: {subject_property_url}")
    subject = subject_matches.iloc[0]
    if subject["latitude"] is None or subject["longitude"] is None:
        raise ComparableBenchmarkError("Subject property is missing latitude/longitude")

    scored_rows = []
    for _, candidate in profiles.iterrows():
        if candidate["property_url"] == subject_property_url:
            continue
        if candidate["latitude"] is None or candidate["longitude"] is None:
            continue

        distance_km = haversine_km(
            float(subject["latitude"]),
            float(subject["longitude"]),
            float(candidate["latitude"]),
            float(candidate["longitude"]),
        )
        if distance_km > config.max_distance_km:
            continue

        geographic_similarity = max(0.0, 1.0 - distance_km / config.max_distance_km)
        feature_similarity, components = _weighted_feature_similarity(subject, candidate)
        weight_sum = config.distance_weight + config.feature_weight
        overall_similarity = (
            geographic_similarity * config.distance_weight
            + feature_similarity * config.feature_weight
        ) / weight_sum

        scored_rows.append(
            {
                "property_url": candidate["property_url"],
                "property_name": candidate["property_name"],
                "property_type": candidate["property_type"],
                "distance_km": distance_km,
                "geographic_similarity": geographic_similarity,
                "feature_similarity": feature_similarity,
                "overall_similarity": overall_similarity,
                "median_price_per_night": candidate["median_price_per_night"],
                "price_row_count": candidate["price_row_count"],
                "room_count": candidate["room_count"],
                **components,
            }
        )

    if not scored_rows:
        return pd.DataFrame(
            columns=[
                "property_url",
                "property_name",
                "property_type",
                "distance_km",
                "geographic_similarity",
                "feature_similarity",
                "overall_similarity",
                "median_price_per_night",
                "price_row_count",
                "room_count",
                *FEATURE_COMPONENT_WEIGHTS.keys(),
            ]
        )

    candidates = pd.DataFrame(scored_rows)
    candidates = candidates.sort_values(
        ["overall_similarity", "distance_km", "property_name", "property_url"],
        ascending=[False, True, True, True],
    )
    return candidates.head(config.max_peers).reset_index(drop=True)


def _matching_peer_rows(
    frame: pd.DataFrame,
    subject_property_url: str,
    peer_property_urls: Iterable[str],
    context_columns: tuple[str, ...],
) -> tuple[pd.DataFrame, int, int]:
    subject_rows = frame.loc[frame["property_url"] == subject_property_url].copy()
    peer_rows = frame.loc[frame["property_url"].isin(list(peer_property_urls))].copy()

    usable_context_columns = tuple(
        column for column in context_columns if column in subject_rows and column in peer_rows
    )
    if not usable_context_columns:
        return peer_rows, 0, 0

    subject_contexts = subject_rows[list(usable_context_columns)].drop_duplicates()
    matched = peer_rows.merge(subject_contexts, on=list(usable_context_columns), how="inner")
    matched_context_count = (
        matched[list(usable_context_columns)].drop_duplicates().shape[0]
        if not matched.empty
        else 0
    )
    return matched, int(subject_contexts.shape[0]), int(matched_context_count)


def _candidate_records(candidates: pd.DataFrame) -> list[dict[str, Any]]:
    records = []
    for record in candidates.to_dict(orient="records"):
        records.append({key: _round_or_none(value) for key, value in record.items()})
    return records


def _row_value(value: object) -> float | int | str | None:
    if _is_missing(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if hasattr(value, "isoformat") and value.__class__.__name__ in {"date", "datetime"}:
        return value.isoformat()
    return _round_or_none(value)


def _peer_price_row_records(peer_rows: pd.DataFrame) -> list[dict[str, Any]]:
    columns = [
        "property_url",
        "property_name",
        "room_id",
        "room_name",
        "block_id",
        "checkin",
        "checkout",
        "lead_time_days",
        "stay_length_days",
        "price_per_night",
        "current_price_value",
    ]
    available_columns = [column for column in columns if column in peer_rows]
    sorted_columns = [
        column
        for column in [
            "property_name",
            "property_url",
            "checkin",
            "stay_length_days",
            "lead_time_days",
            "room_id",
            "block_id",
        ]
        if column in peer_rows
    ]
    rows = peer_rows[available_columns]
    if sorted_columns:
        rows = peer_rows.sort_values(sorted_columns)[available_columns]
    return [
        {key: _row_value(value) for key, value in record.items()}
        for record in rows.to_dict(orient="records")
    ]


def comparable_benchmark(
    frame: pd.DataFrame,
    subject_property_url: str,
    config: ComparableBenchmarkConfig | None = None,
    *,
    include_guest_house: bool = False,
) -> dict[str, Any]:
    """Return an explainable comparable-set benchmark for one subject property."""

    config = config or ComparableBenchmarkConfig()
    segment = segment_self_catering(frame, include_guest_house=include_guest_house)
    profiles = build_property_profiles(segment)
    subject_matches = profiles.loc[profiles["property_url"] == subject_property_url]
    if subject_matches.empty:
        raise ComparableBenchmarkError(
            f"Subject property not found in analysis segment: {subject_property_url}"
        )
    subject_profile = subject_matches.iloc[0]
    candidates = build_comparable_candidates(segment, subject_property_url, config)
    peer_urls = candidates["property_url"].tolist() if not candidates.empty else []

    subject_rows = segment.loc[segment["property_url"] == subject_property_url]
    peer_rows, subject_context_count, matched_context_count = _matching_peer_rows(
        segment,
        subject_property_url,
        peer_urls,
        config.context_columns,
    )

    subject_distribution = _price_distribution(subject_rows["price_per_night"])
    peer_distribution = _price_distribution(peer_rows["price_per_night"])
    subject_median = subject_distribution["median"]
    peer_median = peer_distribution["median"]
    price_gap = (
        float(subject_median) - float(peer_median)
        if subject_median is not None and peer_median is not None
        else None
    )
    price_gap_pct = (
        price_gap / float(peer_median)
        if price_gap is not None and peer_median not in (None, 0)
        else None
    )

    flags = []
    if len(peer_urls) < config.min_peers:
        flags.append("weak_peer_set")
    if peer_distribution["count"] < config.min_peer_price_rows:
        flags.append("sparse_peer_price_coverage")
    if not peer_urls:
        flags.append("no_candidate_peers")
    if peer_distribution["count"] == 0:
        flags.append("no_peer_price_rows")
    if subject_context_count and matched_context_count < subject_context_count:
        flags.append("partial_context_match")

    peer_properties_with_prices = (
        int(peer_rows["property_url"].nunique(dropna=True)) if not peer_rows.empty else 0
    )
    return {
        "subject": {
            "property_url": subject_profile["property_url"],
            "property_name": subject_profile["property_name"],
            "property_type": subject_profile["property_type"],
            "latitude": _round_or_none(subject_profile["latitude"]),
            "longitude": _round_or_none(subject_profile["longitude"]),
            "median_price_per_night": _round_or_none(subject_median),
            "price_row_count": int(subject_profile["price_row_count"]),
        },
        "config": asdict(config),
        "peer_set": {
            "candidate_properties": int(candidates.shape[0]),
            "peer_properties_with_prices": peer_properties_with_prices,
            "flags": sorted(flags),
        },
        "coverage": {
            "subject_contexts": subject_context_count,
            "matched_peer_contexts": matched_context_count,
            "peer_price_rows": int(peer_distribution["count"]),
        },
        "subject_price_distribution": subject_distribution,
        "peer_price_distribution": peer_distribution,
        "subject_percentile_vs_peers": _percentile_rank(subject_median, peer_rows["price_per_night"]),
        "price_gap_to_peer_median": _round_or_none(price_gap),
        "price_gap_to_peer_median_pct": _round_or_none(price_gap_pct),
        "peers": _candidate_records(candidates),
        "peer_price_rows": _peer_price_row_records(peer_rows),
    }


def comparable_benchmarks(
    frame: pd.DataFrame,
    subject_property_urls: Iterable[str],
    config: ComparableBenchmarkConfig | None = None,
    *,
    include_guest_house: bool = False,
) -> list[dict[str, Any]]:
    """Return comparable benchmarks for multiple subject properties."""

    config = config or ComparableBenchmarkConfig()
    return [
        comparable_benchmark(
            frame,
            subject_property_url,
            config,
            include_guest_house=include_guest_house,
        )
        for subject_property_url in subject_property_urls
    ]
