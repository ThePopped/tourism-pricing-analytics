"""Comparable-set benchmarking for self-catering price analysis."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any, Iterable

import pandas as pd

from tourism_pricing_analytics.analysis.segment import segment_self_catering

EARTH_RADIUS_KM = 6371.0088

FEATURE_COMPONENT_WEIGHTS = {
    "property_type_similarity": 0.22,
    "room_size_similarity": 0.18,
    "bed_count_similarity": 0.15,
    "review_score_similarity": 0.17,
    "star_rating_similarity": 0.12,
    "facility_similarity": 0.16,
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


@dataclass(frozen=True)
class ComparableClientSpec:
    """Hand-entered client profile for benchmark subjects outside the scrape."""

    property_url: str | None = None
    property_name: str | None = None
    property_type: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    room_size_sqm: float | None = None
    bed_count: float | None = None
    star_rating: float | None = None
    review_score: float | None = None
    amenities: tuple[str, ...] = ()
    property_facilities: tuple[str, ...] = ()
    price_per_night: float | None = None


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


def _coerce_float(value: object) -> float | None:
    if _is_missing(value):
        return None
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return None
    return float(numeric)


def _coerce_tokens(value: object) -> tuple[str, ...]:
    if _is_missing(value):
        return ()
    if isinstance(value, str):
        parts = [part.strip() for part in value.split("|")]
        return tuple(part for part in parts if part)
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(str(item) for item in value if not _is_missing(item))
    return (str(value),)


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
        "bed_count_similarity": _numeric_similarity(
            subject["median_bed_count"],
            candidate["median_bed_count"],
            scale=4.0,
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
            "median_bed_count": _median_numeric(rows["bed_count"])
            if "bed_count" in rows
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


def client_spec_from_mapping(values: dict[str, Any]) -> ComparableClientSpec:
    """Parse a hand-entered client mapping into a stable comparable profile."""

    return ComparableClientSpec(
        property_url=_clean_text(values.get("property_url")),
        property_name=_clean_text(values.get("property_name")),
        property_type=_clean_text(values.get("property_type")),
        latitude=_coerce_float(values.get("latitude")),
        longitude=_coerce_float(values.get("longitude")),
        room_size_sqm=_coerce_float(values.get("room_size_sqm")),
        bed_count=_coerce_float(values.get("bed_count")),
        star_rating=_coerce_float(values.get("star_rating")),
        review_score=_coerce_float(values.get("review_score")),
        amenities=_coerce_tokens(values.get("amenities")),
        property_facilities=_coerce_tokens(values.get("property_facilities")),
        price_per_night=_coerce_float(values.get("price_per_night")),
    )


def _spec_to_profile(spec: ComparableClientSpec) -> pd.Series:
    feature_tokens = set()
    feature_tokens.update(_tokens_from_value(spec.amenities))
    feature_tokens.update(_tokens_from_value(spec.property_facilities))
    return pd.Series(
        {
            "property_url": spec.property_url or "__client_spec__",
            "property_name": spec.property_name or "Hand-entered client spec",
            "property_type": spec.property_type,
            "latitude": spec.latitude,
            "longitude": spec.longitude,
            "median_price_per_night": spec.price_per_night,
            "price_row_count": 0,
            "room_count": None,
            "median_room_size_sqm": spec.room_size_sqm,
            "median_bed_count": spec.bed_count,
            "median_review_score": spec.review_score,
            "median_review_count": None,
            "median_star_rating": spec.star_rating,
            "feature_tokens": frozenset(feature_tokens),
        }
    )


def _profiles_from_frame_or_profiles(frame: pd.DataFrame) -> pd.DataFrame:
    if {"median_room_size_sqm", "feature_tokens", "price_row_count"}.issubset(frame.columns):
        return frame.copy().reset_index(drop=True)
    return build_property_profiles(frame)


def _resolve_client_profile(
    client: str | dict[str, Any] | ComparableClientSpec | pd.Series,
    profiles: pd.DataFrame,
) -> pd.Series:
    if isinstance(client, pd.Series):
        return client
    if isinstance(client, str):
        matches = profiles.loc[profiles["property_url"] == client]
        if matches.empty:
            raise ComparableBenchmarkError(f"Client property not found: {client}")
        return matches.iloc[0]
    if isinstance(client, dict):
        property_url = _clean_text(client.get("property_url"))
        spec_keys = {
            "latitude",
            "longitude",
            "room_size_sqm",
            "bed_count",
            "star_rating",
            "review_score",
            "amenities",
            "property_facilities",
            "price_per_night",
        }
        if property_url and not any(key in client for key in spec_keys):
            return _resolve_client_profile(property_url, profiles)
        return _spec_to_profile(client_spec_from_mapping(client))
    if isinstance(client, ComparableClientSpec):
        if client.property_url and not any(
            value is not None
            for value in (
                client.latitude,
                client.longitude,
                client.room_size_sqm,
                client.bed_count,
                client.star_rating,
                client.review_score,
                client.price_per_night,
            )
        ) and not client.amenities and not client.property_facilities:
            return _resolve_client_profile(client.property_url, profiles)
        return _spec_to_profile(client)
    raise ComparableBenchmarkError(f"Unsupported client input: {type(client).__name__}")


def _empty_scored_candidates() -> pd.DataFrame:
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


def _score_candidate_profiles(
    client_profile: pd.Series,
    profiles: pd.DataFrame,
    *,
    distance_weight: float,
    feature_weight: float,
    max_distance_km: float,
    max_peers: int | None,
    enforce_distance_limit: bool,
) -> pd.DataFrame:
    if distance_weight < 0 or feature_weight < 0:
        raise ComparableBenchmarkError("similarity weights cannot be negative")
    if distance_weight + feature_weight <= 0:
        raise ComparableBenchmarkError("at least one similarity weight must be positive")
    if max_distance_km <= 0:
        raise ComparableBenchmarkError("max_distance_km must be positive")
    if max_peers is not None and max_peers <= 0:
        raise ComparableBenchmarkError("k/max_peers must be positive")
    if distance_weight > 0 and (
        _is_missing(client_profile["latitude"]) or _is_missing(client_profile["longitude"])
    ):
        raise ComparableBenchmarkError("Client is missing latitude/longitude")

    scored_rows = []
    for _, candidate in profiles.iterrows():
        if candidate["property_url"] == client_profile["property_url"]:
            continue

        distance_km = None
        geographic_similarity = None
        if (
            not _is_missing(client_profile["latitude"])
            and not _is_missing(client_profile["longitude"])
            and not _is_missing(candidate["latitude"])
            and not _is_missing(candidate["longitude"])
        ):
            distance_km = haversine_km(
                float(client_profile["latitude"]),
                float(client_profile["longitude"]),
                float(candidate["latitude"]),
                float(candidate["longitude"]),
            )
            geographic_similarity = max(0.0, 1.0 - distance_km / max_distance_km)

        if distance_weight > 0 and distance_km is None:
            continue
        if enforce_distance_limit and distance_km is not None and distance_km > max_distance_km:
            continue

        candidate_feature_similarity, components = _weighted_feature_similarity(
            client_profile,
            candidate,
        )
        weighted_total = candidate_feature_similarity * feature_weight
        if distance_weight > 0:
            weighted_total += float(geographic_similarity or 0.0) * distance_weight
        overall_similarity = weighted_total / (distance_weight + feature_weight)

        scored_rows.append(
            {
                "property_url": candidate["property_url"],
                "property_name": candidate["property_name"],
                "property_type": candidate["property_type"],
                "distance_km": distance_km,
                "geographic_similarity": geographic_similarity,
                "feature_similarity": candidate_feature_similarity,
                "overall_similarity": overall_similarity,
                "median_price_per_night": candidate["median_price_per_night"],
                "price_row_count": candidate["price_row_count"],
                "room_count": candidate["room_count"],
                **components,
            }
        )

    if not scored_rows:
        return _empty_scored_candidates()

    candidates = pd.DataFrame(scored_rows)
    candidates = candidates.sort_values(
        ["overall_similarity", "distance_km", "property_name", "property_url"],
        ascending=[False, True, True, True],
        na_position="last",
    )
    if max_peers is not None:
        candidates = candidates.head(max_peers)
    return candidates.reset_index(drop=True)


def feature_similarity(
    client: str | dict[str, Any] | ComparableClientSpec | pd.Series,
    candidates: pd.DataFrame,
) -> pd.DataFrame:
    """Return feature-only similarity scores between a client and candidates."""

    profiles = _profiles_from_frame_or_profiles(candidates)
    client_profile = _resolve_client_profile(client, profiles)
    return _score_candidate_profiles(
        client_profile,
        profiles,
        distance_weight=0.0,
        feature_weight=1.0,
        max_distance_km=ComparableBenchmarkConfig.max_distance_km,
        max_peers=None,
        enforce_distance_limit=False,
    )


def rank_competitors(
    client: str | dict[str, Any] | ComparableClientSpec | pd.Series,
    frame: pd.DataFrame,
    *,
    w_geo: float = 0.5,
    w_sim: float = 0.5,
    k: int = 25,
    max_distance_km: float = 8.0,
    include_guest_house: bool = False,
) -> pd.DataFrame:
    """Rank comparable competitors by weighted geography and profile similarity."""

    segment = segment_self_catering(frame, include_guest_house=include_guest_house)
    profiles = build_property_profiles(segment)
    client_profile = _resolve_client_profile(client, profiles)
    return _score_candidate_profiles(
        client_profile,
        profiles,
        distance_weight=w_geo,
        feature_weight=w_sim,
        max_distance_km=max_distance_km,
        max_peers=k,
        enforce_distance_limit=w_geo > 0,
    )


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
    if _is_missing(subject["latitude"]) or _is_missing(subject["longitude"]):
        raise ComparableBenchmarkError("Subject property is missing latitude/longitude")

    return _score_candidate_profiles(
        subject,
        profiles,
        distance_weight=config.distance_weight,
        feature_weight=config.feature_weight,
        max_distance_km=config.max_distance_km,
        max_peers=config.max_peers,
        enforce_distance_limit=True,
    )


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


def _client_property_url(client: str | dict[str, Any] | ComparableClientSpec | pd.Series) -> str | None:
    if isinstance(client, str):
        return client
    if isinstance(client, pd.Series):
        return _clean_text(client.get("property_url"))
    if isinstance(client, ComparableClientSpec):
        return client.property_url
    if isinstance(client, dict):
        return _clean_text(client.get("property_url"))
    return None


def _client_reference_price(
    client: str | dict[str, Any] | ComparableClientSpec | pd.Series,
    subject_rows: pd.DataFrame,
) -> float | None:
    if not subject_rows.empty and "price_per_night" in subject_rows:
        return _price_distribution(subject_rows["price_per_night"])["median"]
    if isinstance(client, ComparableClientSpec):
        return client.price_per_night
    if isinstance(client, dict):
        return _coerce_float(client.get("price_per_night"))
    if isinstance(client, pd.Series):
        return _coerce_float(client.get("median_price_per_night"))
    return None


def _date_key(value: object) -> date | None:
    if _is_missing(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def _window_record(window: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in window.items():
        if _is_missing(value):
            continue
        if key in {"checkin", "checkout"}:
            parsed = _date_key(value)
            if parsed is None:
                raise ComparableBenchmarkError(f"Window {key!r} is not a valid date")
            normalized[key] = parsed.isoformat()
        elif key in {"lead_time_days", "stay_length_days", "checkin_month"}:
            normalized[key] = int(value)
        elif key == "checkin_is_weekend":
            normalized[key] = bool(value)
        else:
            normalized[key] = str(value)
    return normalized


def _normalize_windows(windows: Iterable[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if windows is None:
        return []
    normalized = [_window_record(dict(window)) for window in windows]
    return [window for window in normalized if window]


def _infer_subject_windows(subject_rows: pd.DataFrame) -> list[dict[str, Any]]:
    if subject_rows.empty:
        return []
    columns = [
        column
        for column in ("checkin", "lead_time_days", "stay_length_days", "crete_season")
        if column in subject_rows
    ]
    records = subject_rows[columns].drop_duplicates().to_dict(orient="records")
    return _normalize_windows(records)


def _filter_rows_by_windows(rows: pd.DataFrame, windows: list[dict[str, Any]]) -> pd.DataFrame:
    if not windows:
        return rows.copy()

    masks = []
    for window in windows:
        mask = pd.Series(True, index=rows.index)
        for key, value in window.items():
            if key not in rows.columns:
                raise ComparableBenchmarkError(f"Window column is missing from table: {key}")
            if key in {"checkin", "checkout"}:
                mask &= rows[key].map(_date_key).map(lambda item: item.isoformat() if item else None) == value
            elif key in {"lead_time_days", "stay_length_days", "checkin_month"}:
                mask &= pd.to_numeric(rows[key], errors="coerce") == int(value)
            elif key == "checkin_is_weekend":
                mask &= rows[key].astype(bool) == bool(value)
            else:
                mask &= rows[key].astype(str) == str(value)
        masks.append(mask)

    combined = masks[0]
    for mask in masks[1:]:
        combined |= mask
    return rows.loc[combined].copy()


def _window_context_count(rows: pd.DataFrame, windows: list[dict[str, Any]]) -> int:
    if windows:
        return len(windows)
    return 0 if rows.empty else 1


def peer_price_benchmark(
    client: str | dict[str, Any] | ComparableClientSpec | pd.Series,
    frame: pd.DataFrame,
    windows: Iterable[dict[str, Any]] | None,
    *,
    k: int = 25,
    w_geo: float = 0.5,
    w_sim: float = 0.5,
    max_distance_km: float = 8.0,
    min_peers: int = 5,
    min_peer_price_rows: int = 10,
    include_guest_house: bool = False,
) -> dict[str, Any]:
    """Benchmark a URL or hand-entered client spec against explicit price windows."""

    segment = segment_self_catering(frame, include_guest_house=include_guest_house)
    ranked = rank_competitors(
        client,
        segment,
        w_geo=w_geo,
        w_sim=w_sim,
        k=k,
        max_distance_km=max_distance_km,
        include_guest_house=include_guest_house,
    )
    profiles = build_property_profiles(segment)
    client_profile = _resolve_client_profile(client, profiles)
    subject_url = _client_property_url(client)
    subject_rows = (
        segment.loc[segment["property_url"] == subject_url].copy()
        if subject_url is not None
        else segment.iloc[0:0].copy()
    )
    normalized_windows = _normalize_windows(windows)
    if not normalized_windows:
        normalized_windows = _infer_subject_windows(subject_rows)
    if not normalized_windows:
        raise ComparableBenchmarkError("Explicit benchmark windows are required for spec clients")

    peer_urls = ranked["property_url"].tolist() if not ranked.empty else []
    peer_rows = segment.loc[segment["property_url"].isin(peer_urls)].copy()
    peer_rows = _filter_rows_by_windows(peer_rows, normalized_windows)
    subject_rows = _filter_rows_by_windows(subject_rows, normalized_windows)

    subject_distribution = _price_distribution(subject_rows["price_per_night"])
    peer_distribution = _price_distribution(peer_rows["price_per_night"])
    subject_reference_price = _client_reference_price(client, subject_rows)
    peer_median = peer_distribution["median"]
    price_gap = (
        float(subject_reference_price) - float(peer_median)
        if subject_reference_price is not None and peer_median is not None
        else None
    )
    price_gap_pct = (
        price_gap / float(peer_median)
        if price_gap is not None and peer_median not in (None, 0)
        else None
    )

    flags = []
    if ranked.shape[0] < min_peers:
        flags.append("weak_peer_set")
    if peer_distribution["count"] < min_peer_price_rows:
        flags.append("sparse_peer_price_coverage")
    if ranked.empty:
        flags.append("no_candidate_peers")
    if peer_distribution["count"] == 0:
        flags.append("no_peer_price_rows")
    if client_profile["property_type"] == "Villa":
        flags.append("villa_2_guest_undercoverage")
    if subject_url is None or subject_rows.empty:
        flags.append("no_subject_price_rows")

    return {
        "client": {
            "property_url": None if subject_url == "__client_spec__" else subject_url,
            "property_name": client_profile["property_name"],
            "property_type": client_profile["property_type"],
            "latitude": _round_or_none(client_profile["latitude"]),
            "longitude": _round_or_none(client_profile["longitude"]),
            "room_size_sqm": _round_or_none(client_profile["median_room_size_sqm"]),
            "bed_count": _round_or_none(client_profile["median_bed_count"]),
            "star_rating": _round_or_none(client_profile["median_star_rating"]),
            "review_score": _round_or_none(client_profile["median_review_score"]),
            "reference_price_per_night": _round_or_none(subject_reference_price),
        },
        "config": {
            "k": k,
            "w_geo": w_geo,
            "w_sim": w_sim,
            "max_distance_km": max_distance_km,
            "min_peers": min_peers,
            "min_peer_price_rows": min_peer_price_rows,
        },
        "benchmark_windows": normalized_windows,
        "peer_set": {
            "candidate_properties": int(ranked.shape[0]),
            "peer_properties_with_prices": int(peer_rows["property_url"].nunique(dropna=True))
            if not peer_rows.empty
            else 0,
            "flags": sorted(flags),
        },
        "coverage": {
            "benchmark_windows": _window_context_count(peer_rows, normalized_windows),
            "peer_price_rows": int(peer_distribution["count"]),
            "subject_price_rows": int(subject_distribution["count"]),
        },
        "subject_price_distribution": subject_distribution,
        "peer_price_distribution": peer_distribution,
        "subject_percentile_vs_peers": _percentile_rank(subject_reference_price, peer_rows["price_per_night"]),
        "price_gap_to_peer_median": _round_or_none(price_gap),
        "price_gap_to_peer_median_pct": _round_or_none(price_gap_pct),
        "peers": _candidate_records(ranked),
        "peer_price_rows": _peer_price_row_records(peer_rows),
    }


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
