"""Hedonic price adjustment and gap explanation for self-catering comps."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import GroupKFold

from tourism_pricing_analytics.analysis.segment import segment_self_catering
from tourism_pricing_analytics.features.encoders import normalize_amenity

RANDOM_SEED = 10001

IDENTIFIER_OR_LEAKAGE_COLUMNS = {
    "property_name",
    "property_url",
    "room_name",
    "room_id",
    "block_id",
    "captured_at",
    "current_price_text",
    "original_price_text",
    "current_price_value",
    "original_price_value",
    "price_per_night",
    "occupancy_text",
    "conditions_text",
    "scarcity_text",
    "house_rules",
    "quantity_options",
    "max_persons",
}

BASE_NUMERIC_FEATURES = (
    "room_size_sqm",
    "bed_count",
    "star_rating",
    "review_score",
    "review_count",
    "nearest_poi_km",
    "nearby_poi_count",
)

WINDOW_NUMERIC_FEATURES = (
    "lead_time_days",
    "stay_length_days",
    "checkin_month",
    "checkin_is_weekend",
)

ORDINAL_FEATURES = (
    "meal_plan_ordinal",
    "cancellation_flexibility_ordinal",
)

CATEGORICAL_FEATURES = (
    "property_type",
    "crete_season",
)

RAW_GEO_FEATURES = (
    "latitude",
    "longitude",
)

PROFILE_COLUMNS = (
    "property_name",
    "property_url",
    "property_type",
    "latitude",
    "longitude",
    "room_size_sqm",
    "bed_count",
    "star_rating",
    "review_score",
    "review_count",
    "amenities",
    "property_facilities",
    "review_subscores",
    "nearby_poi",
    "meal_plan_ordinal",
    "cancellation_flexibility_ordinal",
)


class HedonicModelError(ValueError):
    """Raised when the hedonic model cannot be safely built or used."""


@dataclass(frozen=True)
class HedonicFeatureMeta:
    """Feature contract needed to transform future rows like training rows."""

    feature_columns: tuple[str, ...]
    ols_feature_columns: tuple[str, ...]
    gbm_feature_columns: tuple[str, ...]
    numeric_features: tuple[str, ...]
    missing_flag_features: tuple[str, ...]
    categorical_levels: dict[str, tuple[str, ...]]
    amenity_vocabulary: tuple[str, ...]
    facility_vocabulary: tuple[str, ...]
    imputation_values: dict[str, float]
    target_column: str = "price_per_night"
    group_column: str = "property_url"


@dataclass(frozen=True)
class HedonicModelBundle:
    """Fitted OLS and gradient-boosting models with their shared feature contract."""

    feature_meta: HedonicFeatureMeta
    ols_results: Any
    gbm_model: GradientBoostingRegressor
    cv_metrics: dict[str, float | int | None]
    training_rows: int
    training_properties: int


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    if value is pd.NA:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return False


def _clean_token(value: object) -> str | None:
    if _is_missing(value):
        return None
    text = normalize_amenity(str(value))
    return text or None


def _safe_feature_name(prefix: str, token: str) -> str:
    cleaned = re.sub(r"[^0-9a-zA-Z]+", "_", token).strip("_").lower()
    cleaned = cleaned or "value"
    return f"{prefix}{cleaned[:80]}"


def _tokens_from_value(value: object) -> set[str]:
    if _is_missing(value):
        return set()
    if isinstance(value, dict):
        tokens: set[str] = set()
        for key, item in value.items():
            key_token = _clean_token(key)
            if key_token:
                tokens.add(key_token)
            tokens.update(_tokens_from_value(item))
        return tokens
    if isinstance(value, (list, tuple, set, frozenset)):
        tokens = set()
        for item in value:
            tokens.update(_tokens_from_value(item))
        return tokens
    token = _clean_token(value)
    return {token} if token else set()


def _row_token_sets(series: pd.Series) -> list[set[str]]:
    return [_tokens_from_value(value) for value in series.tolist()]


def _frequency_vocabulary(series: pd.Series, min_frequency: int) -> tuple[str, ...]:
    counts: dict[str, int] = {}
    for tokens in _row_token_sets(series):
        for token in tokens:
            counts[token] = counts.get(token, 0) + 1
    return tuple(sorted(token for token, count in counts.items() if count >= min_frequency))


def _numeric_or_none(value: object) -> float | None:
    if _is_missing(value):
        return None
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return None
    return float(numeric)


def _nearby_poi_stats(value: object) -> tuple[float | None, int]:
    if not isinstance(value, list):
        return None, 0
    distances: list[float] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        distance = _numeric_or_none(item.get("distance"))
        if distance is None:
            continue
        unit = str(item.get("unit") or "km").lower()
        if unit in {"m", "meter", "meters", "metre", "metres"}:
            distance = distance / 1000.0
        distances.append(distance)
    return (min(distances) if distances else None, len(distances))


def _subscore_column_name(key: object) -> str:
    token = _clean_token(key) or "unknown"
    return _safe_feature_name("subscore_", token)


def _prepare_feature_frame(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if "checkin_month" not in out and "checkin" in out:
        out["checkin_month"] = pd.to_datetime(out["checkin"], errors="coerce").dt.month
    if "checkin_is_weekend" not in out and "checkin" in out:
        out["checkin_is_weekend"] = (
            pd.to_datetime(out["checkin"], errors="coerce").dt.dayofweek >= 5
        )

    if "nearby_poi" in out:
        stats = out["nearby_poi"].map(_nearby_poi_stats)
        if "nearest_poi_km" not in out:
            out["nearest_poi_km"] = stats.map(lambda item: item[0])
        if "nearby_poi_count" not in out:
            out["nearby_poi_count"] = stats.map(lambda item: item[1])
    else:
        out["nearest_poi_km"] = np.nan
        out["nearby_poi_count"] = 0

    subscore_keys: set[str] = set()
    if "review_subscores" in out:
        for value in out["review_subscores"].tolist():
            if isinstance(value, dict):
                subscore_keys.update(_subscore_column_name(key) for key in value)
    for column in sorted(subscore_keys):
        if column not in out:
            out[column] = out["review_subscores"].map(
                lambda scores, col=column: _subscore_value(scores, col)
            )
    return out


def _subscore_value(scores: object, column: str) -> float | None:
    if not isinstance(scores, dict):
        return None
    for key, value in scores.items():
        if _subscore_column_name(key) == column:
            return _numeric_or_none(value)
    return None


def _stable_levels(series: pd.Series) -> tuple[str, ...]:
    values = [
        str(value).strip()
        for value in series.dropna().tolist()
        if str(value).strip()
    ]
    return tuple(sorted(set(values)))


def _fit_feature_meta(
    frame: pd.DataFrame,
    *,
    min_token_frequency: int,
) -> HedonicFeatureMeta:
    if min_token_frequency <= 0:
        raise HedonicModelError("min_token_frequency must be positive")

    prepared = _prepare_feature_frame(frame)
    subscore_features = tuple(sorted(column for column in prepared if column.startswith("subscore_")))
    numeric_features = (
        *BASE_NUMERIC_FEATURES,
        *WINDOW_NUMERIC_FEATURES,
        *ORDINAL_FEATURES,
        *subscore_features,
        *RAW_GEO_FEATURES,
    )

    imputation_values: dict[str, float] = {}
    missing_flag_features: list[str] = []
    for column in numeric_features:
        values = pd.to_numeric(prepared[column], errors="coerce") if column in prepared else pd.Series(dtype=float)
        median = values.median(skipna=True)
        imputation_values[column] = 0.0 if pd.isna(median) else float(median)
        if values.isna().any() or column not in prepared:
            missing_flag_features.append(f"{column}_missing")

    categorical_levels = {
        column: _stable_levels(prepared[column]) if column in prepared else ()
        for column in CATEGORICAL_FEATURES
    }
    amenity_vocabulary = (
        _frequency_vocabulary(prepared["amenities"], min_token_frequency)
        if "amenities" in prepared
        else ()
    )
    facility_vocabulary = (
        _frequency_vocabulary(prepared["property_facilities"], min_token_frequency)
        if "property_facilities" in prepared
        else ()
    )

    feature_columns: list[str] = []
    for column in numeric_features:
        feature_columns.append(column)
        missing_flag = f"{column}_missing"
        if missing_flag in missing_flag_features:
            feature_columns.append(missing_flag)
    for column, levels in categorical_levels.items():
        feature_columns.extend(_safe_feature_name(f"{column}__", level) for level in levels)
    feature_columns.extend(_safe_feature_name("amenity__", token) for token in amenity_vocabulary)
    feature_columns.extend(_safe_feature_name("facility__", token) for token in facility_vocabulary)

    leakage = set(feature_columns) & IDENTIFIER_OR_LEAKAGE_COLUMNS
    if leakage:
        raise HedonicModelError(f"Leakage columns entered design matrix: {sorted(leakage)}")

    gbm_feature_columns = tuple(feature_columns)
    first_categorical_levels = {
        _safe_feature_name(f"{column}__", levels[0])
        for column, levels in categorical_levels.items()
        if levels
    }
    ols_feature_columns = tuple(
        column
        for column in feature_columns
        if column not in RAW_GEO_FEATURES
        and column not in first_categorical_levels
        and not column.startswith("amenity__")
        and not column.startswith("facility__")
    )
    return HedonicFeatureMeta(
        feature_columns=tuple(feature_columns),
        ols_feature_columns=ols_feature_columns,
        gbm_feature_columns=gbm_feature_columns,
        numeric_features=tuple(numeric_features),
        missing_flag_features=tuple(missing_flag_features),
        categorical_levels=categorical_levels,
        amenity_vocabulary=amenity_vocabulary,
        facility_vocabulary=facility_vocabulary,
        imputation_values=imputation_values,
    )


def _transform_with_meta(frame: pd.DataFrame, meta: HedonicFeatureMeta) -> pd.DataFrame:
    prepared = _prepare_feature_frame(frame)
    feature_data: dict[str, Iterable[float | int]] = {}

    for column in meta.numeric_features:
        values = (
            pd.to_numeric(prepared[column], errors="coerce")
            if column in prepared
            else pd.Series(np.nan, index=prepared.index)
        )
        missing_flag = f"{column}_missing"
        if missing_flag in meta.missing_flag_features:
            feature_data[missing_flag] = values.isna().astype(int)
        feature_data[column] = values.fillna(meta.imputation_values[column]).astype(float)

    for column, levels in meta.categorical_levels.items():
        values = prepared[column].astype(str) if column in prepared else pd.Series("", index=prepared.index)
        for level in levels:
            feature_data[_safe_feature_name(f"{column}__", level)] = (values == level).astype(int)

    amenity_tokens = _row_token_sets(prepared["amenities"]) if "amenities" in prepared else [set()] * len(prepared)
    for token in meta.amenity_vocabulary:
        feature_data[_safe_feature_name("amenity__", token)] = [int(token in tokens) for tokens in amenity_tokens]

    facility_tokens = (
        _row_token_sets(prepared["property_facilities"])
        if "property_facilities" in prepared
        else [set()] * len(prepared)
    )
    for token in meta.facility_vocabulary:
        feature_data[_safe_feature_name("facility__", token)] = [int(token in tokens) for tokens in facility_tokens]

    features = pd.DataFrame(feature_data, index=prepared.index)
    for column in meta.feature_columns:
        if column not in features:
            features[column] = 0.0
    return features.loc[:, list(meta.feature_columns)].astype(float)


def build_design_matrix(
    frame: pd.DataFrame,
    *,
    feature_meta: HedonicFeatureMeta | None = None,
    min_token_frequency: int = 25,
) -> tuple[pd.DataFrame, pd.Series, pd.Series, HedonicFeatureMeta]:
    """Build ``X``, log target ``y``, property groups, and feature metadata."""

    if frame.empty:
        raise HedonicModelError("Cannot build a design matrix from an empty frame")
    meta = feature_meta or _fit_feature_meta(frame, min_token_frequency=min_token_frequency)
    X = _transform_with_meta(frame, meta)

    if meta.target_column in frame:
        prices = pd.to_numeric(frame[meta.target_column], errors="coerce")
        if prices.isna().any() or (prices <= 0).any():
            raise HedonicModelError("price_per_night must be positive for every model row")
        y = np.log(prices).rename("log_price_per_night")
    else:
        y = pd.Series(np.nan, index=frame.index, name="log_price_per_night")

    groups = (
        frame[meta.group_column].astype(str)
        if meta.group_column in frame
        else pd.Series([str(index) for index in frame.index], index=frame.index)
    )
    return X, y, groups, meta


def group_kfold_splits(
    groups: pd.Series,
    *,
    n_splits: int = 5,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Return deterministic ``GroupKFold`` train/test indexes."""

    unique_groups = pd.Series(groups).dropna().nunique()
    if unique_groups < 2:
        return []
    splits = min(n_splits, int(unique_groups))
    return list(GroupKFold(n_splits=splits).split(np.zeros(len(groups)), groups=groups))


def train_ols(
    X: pd.DataFrame,
    y: pd.Series,
    meta: HedonicFeatureMeta,
) -> Any:
    """Fit an OLS model with HC3 robust covariance for interpretable premia."""

    design = sm.add_constant(X.loc[:, list(meta.ols_feature_columns)], has_constant="add")
    model = sm.OLS(y.astype(float), design.astype(float))
    return model.fit(cov_type="HC3")


def train_gradient_boosting(
    X: pd.DataFrame,
    y: pd.Series,
    groups: pd.Series,
    meta: HedonicFeatureMeta,
    *,
    random_state: int = RANDOM_SEED,
) -> tuple[GradientBoostingRegressor, dict[str, float | int | None]]:
    """Fit grouped-validation gradient boosting and return final model + metrics."""

    feature_frame = X.loc[:, list(meta.gbm_feature_columns)]
    splits = group_kfold_splits(groups)
    fold_metrics: list[dict[str, float]] = []
    for train_idx, test_idx in splits:
        fold_model = GradientBoostingRegressor(
            random_state=random_state,
            n_estimators=160,
            learning_rate=0.04,
            max_depth=3,
            min_samples_leaf=2,
        )
        fold_model.fit(feature_frame.iloc[train_idx], y.iloc[train_idx])
        predictions = pd.Series(fold_model.predict(feature_frame.iloc[test_idx]), index=y.iloc[test_idx].index)
        actual = y.iloc[test_idx]
        fold_metrics.append(
            {
                "r2_log": float(r2_score(actual, predictions)),
                "mae_log": float(mean_absolute_error(actual, predictions)),
                "mae_eur": float(mean_absolute_error(np.exp(actual), np.exp(predictions))),
            }
        )

    final_model = GradientBoostingRegressor(
        random_state=random_state,
        n_estimators=160,
        learning_rate=0.04,
        max_depth=3,
        min_samples_leaf=2,
    )
    final_model.fit(feature_frame, y)

    if not fold_metrics:
        metrics: dict[str, float | int | None] = {
            "folds": 0,
            "r2_log_mean": None,
            "mae_log_mean": None,
            "mae_eur_mean": None,
        }
    else:
        metrics = {
            "folds": len(fold_metrics),
            "r2_log_mean": float(np.mean([item["r2_log"] for item in fold_metrics])),
            "mae_log_mean": float(np.mean([item["mae_log"] for item in fold_metrics])),
            "mae_eur_mean": float(np.mean([item["mae_eur"] for item in fold_metrics])),
        }
    return final_model, metrics


def fit_hedonic_models(
    frame: pd.DataFrame,
    *,
    include_guest_house: bool = False,
    min_token_frequency: int = 25,
) -> HedonicModelBundle:
    """Train OLS and grouped gradient boosting on the self-catering segment."""

    segment = segment_self_catering(frame, include_guest_house=include_guest_house)
    X, y, groups, meta = build_design_matrix(segment, min_token_frequency=min_token_frequency)
    ols_results = train_ols(X, y, meta)
    gbm_model, cv_metrics = train_gradient_boosting(X, y, groups, meta)
    return HedonicModelBundle(
        feature_meta=meta,
        ols_results=ols_results,
        gbm_model=gbm_model,
        cv_metrics=cv_metrics,
        training_rows=int(segment.shape[0]),
        training_properties=int(segment["property_url"].nunique(dropna=True)),
    )


def predict_log_prices(bundle: HedonicModelBundle, rows: pd.DataFrame) -> pd.Series:
    """Predict log EUR/night with the fitted gradient-boosting model."""

    X, _, _, _ = build_design_matrix(rows, feature_meta=bundle.feature_meta)
    values = bundle.gbm_model.predict(X.loc[:, list(bundle.feature_meta.gbm_feature_columns)])
    return pd.Series(values, index=rows.index, name="predicted_log_price")


def predict_prices(bundle: HedonicModelBundle, rows: pd.DataFrame) -> pd.Series:
    """Predict EUR/night with the fitted gradient-boosting model."""

    return np.exp(predict_log_prices(bundle, rows)).rename("predicted_price_per_night")


def _mode_or_first(series: pd.Series) -> Any:
    values = [value for value in series.tolist() if not _is_missing(value)]
    if not values:
        return None
    try:
        counts = pd.Series(values).value_counts()
        return counts.index[0]
    except TypeError:
        return values[0]


def _median_or_first(series: pd.Series) -> Any:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if not numeric.empty:
        return float(numeric.median())
    return _mode_or_first(series)


def _profile_values(client: str | dict[str, Any] | pd.Series, frame: pd.DataFrame) -> dict[str, Any]:
    if isinstance(client, pd.Series):
        return {column: client.get(column) for column in PROFILE_COLUMNS if column in client}
    if isinstance(client, dict):
        return {column: client.get(column) for column in PROFILE_COLUMNS if column in client}
    rows = frame.loc[frame["property_url"] == client]
    if rows.empty:
        raise HedonicModelError(f"Client property not found: {client}")
    values: dict[str, Any] = {}
    for column in PROFILE_COLUMNS:
        if column not in rows:
            continue
        if column in {
            "latitude",
            "longitude",
            "room_size_sqm",
            "bed_count",
            "star_rating",
            "review_score",
            "review_count",
            "meal_plan_ordinal",
            "cancellation_flexibility_ordinal",
        }:
            values[column] = _median_or_first(rows[column])
        else:
            values[column] = _mode_or_first(rows[column])
    return values


def _rows_from_subject(subject: str | dict[str, Any] | pd.Series, frame: pd.DataFrame | None) -> pd.DataFrame:
    if isinstance(subject, pd.Series):
        return pd.DataFrame([subject.to_dict()])
    if isinstance(subject, dict):
        return pd.DataFrame([subject])
    if frame is None:
        raise HedonicModelError("A frame is required when subject is a property URL")
    rows = frame.loc[frame["property_url"] == subject].copy()
    if rows.empty:
        raise HedonicModelError(f"Property not found: {subject}")
    median_price = pd.to_numeric(rows["price_per_night"], errors="coerce").median()
    order = (pd.to_numeric(rows["price_per_night"], errors="coerce") - median_price).abs().sort_values()
    return rows.loc[[order.index[0]]].copy()


def feature_adjusted_peer_prices(
    client: str | dict[str, Any] | pd.Series,
    peer_rows: pd.DataFrame,
    frame: pd.DataFrame,
    bundle: HedonicModelBundle,
) -> pd.DataFrame:
    """Return peer rows adjusted to the client's feature profile."""

    if peer_rows.empty:
        return peer_rows.copy()
    client_values = _profile_values(client, frame)
    client_like_rows = peer_rows.copy()
    for column, value in client_values.items():
        if isinstance(value, (list, tuple, dict, set, frozenset)):
            client_like_rows[column] = [value] * len(client_like_rows)
        else:
            client_like_rows[column] = value

    peer_predicted_log = predict_log_prices(bundle, peer_rows)
    client_predicted_log = predict_log_prices(bundle, client_like_rows)
    adjusted = peer_rows.copy()
    adjusted["predicted_peer_price_per_night"] = np.exp(peer_predicted_log)
    adjusted["predicted_client_like_price_per_night"] = np.exp(client_predicted_log)
    adjusted["feature_adjustment_factor"] = np.exp(client_predicted_log - peer_predicted_log)
    adjusted["feature_adjusted_price_per_night"] = (
        pd.to_numeric(adjusted["price_per_night"], errors="coerce")
        * adjusted["feature_adjustment_factor"]
    )
    return adjusted


def explain_price_gap(
    client: str | dict[str, Any] | pd.Series,
    competitor: str | dict[str, Any] | pd.Series,
    frame: pd.DataFrame | None = None,
    bundle: HedonicModelBundle | None = None,
) -> dict[str, Any]:
    """Split an observed price gap into feature-explained and residual parts."""

    if bundle is None:
        if frame is None:
            raise HedonicModelError("Either frame+bundle or frame alone is required")
        bundle = fit_hedonic_models(frame)

    client_row = _rows_from_subject(client, frame)
    competitor_row = _rows_from_subject(competitor, frame)
    rows = pd.concat([client_row, competitor_row], ignore_index=True)
    predicted_prices = predict_prices(bundle, rows)
    observed_prices = pd.to_numeric(rows["price_per_night"], errors="coerce")
    if observed_prices.isna().any():
        raise HedonicModelError("Both client and competitor rows need price_per_night")

    observed_gap = float(observed_prices.iloc[0] - observed_prices.iloc[1])
    feature_explained_gap = float(predicted_prices.iloc[0] - predicted_prices.iloc[1])
    residual_gap = observed_gap - feature_explained_gap
    return {
        "client_price_per_night": float(observed_prices.iloc[0]),
        "competitor_price_per_night": float(observed_prices.iloc[1]),
        "observed_gap": observed_gap,
        "feature_explained_gap": feature_explained_gap,
        "residual_gap": residual_gap,
        "client_predicted_price_per_night": float(predicted_prices.iloc[0]),
        "competitor_predicted_price_per_night": float(predicted_prices.iloc[1]),
        "top_feature_contributions_log_points": _shap_gap_contributions(bundle, rows),
    }


def _shap_gap_contributions(
    bundle: HedonicModelBundle,
    rows: pd.DataFrame,
    *,
    limit: int = 10,
) -> list[dict[str, float | str]]:
    try:
        import shap

        X, _, _, _ = build_design_matrix(rows, feature_meta=bundle.feature_meta)
        explainer = shap.TreeExplainer(bundle.gbm_model)
        values = explainer.shap_values(X.loc[:, list(bundle.feature_meta.gbm_feature_columns)])
        difference = np.asarray(values[0]) - np.asarray(values[1])
    except Exception:
        return []

    records = [
        {"feature": feature, "contribution_log_points": float(value)}
        for feature, value in zip(bundle.feature_meta.gbm_feature_columns, difference)
    ]
    records.sort(key=lambda item: abs(float(item["contribution_log_points"])), reverse=True)
    return records[:limit]
