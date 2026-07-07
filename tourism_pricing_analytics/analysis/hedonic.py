"""Hedonic price adjustment and gap explanation for self-catering comps."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.ensemble import GradientBoostingRegressor, HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import GroupKFold

from tourism_pricing_analytics.analysis.segment import segment_self_catering
from tourism_pricing_analytics.features.encoders import (
    is_room_size_token,
    normalize_amenity,
)
from tourism_pricing_analytics.features.geo import (
    GEO_DISTANCE_FEATURES,
    add_location_features,
)
from tourism_pricing_analytics.features.quality import (
    QUALITY_FEATURE_COLUMNS,
    quality_flags,
)

RANDOM_SEED = 10001

# Booster families evaluated in the grouped-CV bake-off. The winner becomes the
# shipped ``bundle.gbm_model``; the loser stays reproducible via the same search.
GBR_FAMILY = "gradient_boosting"
HIST_FAMILY = "hist_gradient_boosting"

# Fixed params used on the non-tuned (fast / back-compatible) path. These are the
# historical defaults the tuner is expected to beat.
DEFAULT_GBR_PARAMS: dict[str, Any] = {
    "n_estimators": 160,
    "learning_rate": 0.04,
    "max_depth": 3,
    "min_samples_leaf": 2,
}

# Small, sensible random-search spaces. Kept deliberately compact -- the design
# matrix is wide (hundreds of multi-hot columns on ~1.5k rows), so each fit is
# not cheap and a bloated grid buys little. ``max_features`` and subsampling do
# most of the regularization work against that width.
DEFAULT_SEARCH_SPACES: dict[str, dict[str, tuple]] = {
    GBR_FAMILY: {
        "n_estimators": (150, 200, 300),
        "learning_rate": (0.02, 0.03, 0.05),
        "max_depth": (2, 3),
        "min_samples_leaf": (2, 3, 5),
        "subsample": (0.6, 0.8),
        "max_features": (0.4, 0.6, 0.8),
    },
    HIST_FAMILY: {
        "max_iter": (200, 300, 400),
        "learning_rate": (0.03, 0.05, 0.08),
        "max_leaf_nodes": (15, 31),
        "min_samples_leaf": (10, 20, 30),
        "l2_regularization": (0.0, 0.1, 1.0),
        "max_features": (0.5, 0.7, 1.0),
    },
}

# Amenity/facility frequency floors tried during tuning (an outer search
# dimension because each floor rebuilds the design matrix). Lower floors add
# columns, so keep the grid short.
DEFAULT_TOKEN_FREQUENCY_GRID: tuple[int, ...] = (15, 25)

# Frozen bake-off winner from the Phase A grouped-CV tuning sweep: HistGBM at a
# token-frequency floor of 15. Reports and the dashboard ship this configuration
# on the fast path (see ``fit_selected_hedonic_models``) so every deliverable
# reflects the tuned model without re-running the search each session. The
# grouped-CV metrics and the conformal band are still recomputed deterministically
# at fit time, so the reported R2/MAE/± stay honest and reproducible.
SELECTED_MODEL_FAMILY = HIST_FAMILY
SELECTED_MODEL_PARAMS: dict[str, Any] = {
    "l2_regularization": 0.0,
    "learning_rate": 0.05,
    "max_features": 0.7,
    "max_iter": 300,
    "max_leaf_nodes": 15,
    "min_samples_leaf": 10,
}
SELECTED_MIN_TOKEN_FREQUENCY = 15

DEFAULT_SEARCH_N_ITER = 16

# Parallelism for the config search. -1 uses all cores; the per-fit matrix is a
# few MB so process fan-out is cheap in memory.
DEFAULT_SEARCH_N_JOBS = -1

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
    quality_features: tuple[str, ...]
    imputation_values: dict[str, float]
    target_column: str = "price_per_night"
    group_column: str = "property_url"


@dataclass(frozen=True)
class HedonicModelBundle:
    """Fitted OLS and gradient-boosting models with their shared feature contract."""

    feature_meta: HedonicFeatureMeta
    ols_results: Any
    gbm_model: Any
    cv_metrics: dict[str, Any]
    training_rows: int
    training_properties: int
    model_family: str = GBR_FAMILY
    model_params: dict[str, Any] = field(default_factory=dict)
    min_token_frequency: int = 25
    search_leaderboard: tuple[dict[str, Any], ...] = ()
    # Out-of-fold log-scale residuals (actual - predicted) collected over the
    # grouped folds; the basis for the split-conformal prediction band.
    conformal_residuals: np.ndarray = field(default_factory=lambda: np.empty(0))
    # Coverage the band + optional quantile models were calibrated for.
    conformal_coverage: float = 0.8
    # Optional feature-dependent width: {"lower": model, "upper": model} of
    # HistGBM quantile regressors at the conformal coverage's tail quantiles.
    quantile_models: dict[str, Any] = field(default_factory=dict)


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
    raw = str(value)
    # Room-size measurements (e.g. "25 m²") ride along in Booking's raw amenity
    # list but are captured separately as ``room_size_sqm``; keeping them here
    # would create sparse per-size one-hot tokens redundant with that numeric
    # feature and distort the hedonic fit and feature-adjustment.
    if is_room_size_token(raw):
        return None
    text = normalize_amenity(raw)
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


def _combined_quality_tokens(prepared: pd.DataFrame) -> list[set[str]]:
    """Union of normalized amenity + facility tokens per row for curated flags."""

    amenity = (
        _row_token_sets(prepared["amenities"])
        if "amenities" in prepared
        else [set()] * len(prepared)
    )
    facility = (
        _row_token_sets(prepared["property_facilities"])
        if "property_facilities" in prepared
        else [set()] * len(prepared)
    )
    return [a | f for a, f in zip(amenity, facility)]


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

    out = add_location_features(out)

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
        *GEO_DISTANCE_FEATURES,
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

    # Curated high-value binaries, evaluated independently of the frequency
    # floor. Drop any that are constant across the training segment (e.g. a
    # near-ubiquitous "air conditioning"): a column with no variance carries no
    # signal for the trees and is collinear with the OLS intercept.
    quality_rows = [quality_flags(tokens) for tokens in _combined_quality_tokens(prepared)]
    n_rows = len(quality_rows)
    quality_features = tuple(
        column
        for column in QUALITY_FEATURE_COLUMNS
        if 0 < sum(row[column] for row in quality_rows) < n_rows
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
    feature_columns.extend(quality_features)

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
        quality_features=quality_features,
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

    if meta.quality_features:
        combined = [a | f for a, f in zip(amenity_tokens, facility_tokens)]
        quality_rows = [quality_flags(tokens) for tokens in combined]
        for column in meta.quality_features:
            feature_data[column] = [row[column] for row in quality_rows]

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


def _make_estimator(family: str, params: dict[str, Any], random_state: int) -> Any:
    """Construct an unfitted booster for ``family`` with ``params``."""

    if family == HIST_FAMILY:
        return HistGradientBoostingRegressor(random_state=random_state, **params)
    if family == GBR_FAMILY:
        return GradientBoostingRegressor(random_state=random_state, **params)
    raise HedonicModelError(f"Unknown booster family: {family}")


def _cv_score_params(
    feature_frame: pd.DataFrame,
    y: pd.Series,
    splits: list[tuple[np.ndarray, np.ndarray]],
    family: str,
    params: dict[str, Any],
    random_state: int,
) -> dict[str, float | int]:
    """Mean out-of-sample metrics for one ``(family, params)`` over grouped folds."""

    fold_metrics: list[dict[str, float]] = []
    for train_idx, test_idx in splits:
        model = _make_estimator(family, params, random_state)
        model.fit(feature_frame.iloc[train_idx], y.iloc[train_idx])
        predictions = pd.Series(model.predict(feature_frame.iloc[test_idx]), index=y.iloc[test_idx].index)
        actual = y.iloc[test_idx]
        fold_metrics.append(
            {
                "r2_log": float(r2_score(actual, predictions)),
                "mae_log": float(mean_absolute_error(actual, predictions)),
                "mae_eur": float(mean_absolute_error(np.exp(actual), np.exp(predictions))),
            }
        )
    return {
        "folds": len(fold_metrics),
        "r2_log_mean": float(np.mean([item["r2_log"] for item in fold_metrics])),
        "mae_log_mean": float(np.mean([item["mae_log"] for item in fold_metrics])),
        "mae_eur_mean": float(np.mean([item["mae_eur"] for item in fold_metrics])),
    }


def _sample_param_configs(
    space: dict[str, tuple],
    n_iter: int,
    seed: int,
) -> list[dict[str, Any]]:
    """Deterministically sample up to ``n_iter`` unique configs from ``space``."""

    keys = sorted(space)
    rng = np.random.RandomState(seed)
    seen: set[tuple] = set()
    configs: list[dict[str, Any]] = []
    # Bounded attempts so a small grid does not spin forever chasing uniqueness.
    for _ in range(n_iter * 20):
        if len(configs) >= n_iter:
            break
        choice = tuple(space[key][rng.randint(len(space[key]))] for key in keys)
        if choice in seen:
            continue
        seen.add(choice)
        configs.append(dict(zip(keys, choice)))
    return configs


def grouped_random_search(
    feature_frame: pd.DataFrame,
    y: pd.Series,
    groups: pd.Series,
    family: str,
    *,
    space: dict[str, tuple] | None = None,
    n_iter: int = DEFAULT_SEARCH_N_ITER,
    splits: list[tuple[np.ndarray, np.ndarray]] | None = None,
    seed: int = RANDOM_SEED,
    n_jobs: int = 1,
) -> dict[str, Any] | None:
    """Randomly search ``family`` under GroupKFold; return the best config + metrics.

    Scored by mean out-of-sample EUR/night MAE (lower is better), ties broken by
    higher mean log R2. Returns ``None`` when there are too few groups to split.
    Config scoring is embarrassingly parallel; ``n_jobs`` fans it out while the
    deterministic winner selection stays independent of evaluation order.
    """

    space = space or DEFAULT_SEARCH_SPACES[family]
    fold_splits = splits if splits is not None else group_kfold_splits(groups)
    if not fold_splits:
        return None
    configs = _sample_param_configs(space, n_iter, seed)
    if n_jobs == 1 or len(configs) <= 1:
        scored = [_cv_score_params(feature_frame, y, fold_splits, family, params, seed) for params in configs]
    else:
        from joblib import Parallel, delayed

        scored = Parallel(n_jobs=n_jobs)(
            delayed(_cv_score_params)(feature_frame, y, fold_splits, family, params, seed)
            for params in configs
        )
    best: dict[str, Any] | None = None
    for params, metrics in zip(configs, scored):
        candidate = {"family": family, "params": params, "metrics": metrics}
        if best is None or _is_better(metrics, best["metrics"]):
            best = candidate
    return best


def _is_better(candidate: dict[str, float | int], incumbent: dict[str, float | int]) -> bool:
    """Lower EUR MAE wins; ties broken by higher log R2."""

    cand_mae = candidate["mae_eur_mean"]
    inc_mae = incumbent["mae_eur_mean"]
    if not math.isclose(cand_mae, inc_mae, rel_tol=1e-9, abs_tol=1e-9):
        return cand_mae < inc_mae
    return candidate["r2_log_mean"] > incumbent["r2_log_mean"]


def train_gradient_boosting(
    X: pd.DataFrame,
    y: pd.Series,
    groups: pd.Series,
    meta: HedonicFeatureMeta,
    *,
    family: str = GBR_FAMILY,
    params: dict[str, Any] | None = None,
    random_state: int = RANDOM_SEED,
) -> tuple[Any, dict[str, Any]]:
    """Fit one grouped-validated booster and return the refit model + CV metrics."""

    resolved = dict(params if params is not None else DEFAULT_GBR_PARAMS)
    feature_frame = X.loc[:, list(meta.gbm_feature_columns)]
    splits = group_kfold_splits(groups)
    if splits:
        metrics = _cv_score_params(feature_frame, y, splits, family, resolved, random_state)
    else:
        metrics = {"folds": 0, "r2_log_mean": None, "mae_log_mean": None, "mae_eur_mean": None}

    final_model = _make_estimator(family, resolved, random_state)
    final_model.fit(feature_frame, y)
    return final_model, metrics


def tune_hedonic_booster(
    segment: pd.DataFrame,
    *,
    token_frequency_grid: Iterable[int] = DEFAULT_TOKEN_FREQUENCY_GRID,
    families: Iterable[str] = (GBR_FAMILY, HIST_FAMILY),
    search_spaces: dict[str, dict[str, tuple]] | None = None,
    n_iter: int = DEFAULT_SEARCH_N_ITER,
    n_jobs: int = DEFAULT_SEARCH_N_JOBS,
    random_state: int = RANDOM_SEED,
) -> dict[str, Any] | None:
    """Bake-off across token-frequency floors x booster families under GroupKFold.

    Returns the winning ``{min_token_frequency, family, params, metrics}`` plus a
    compact ``leaderboard`` of the best config per (floor, family), or ``None``
    when no floor yields enough groups to cross-validate.
    """

    spaces = search_spaces or DEFAULT_SEARCH_SPACES
    leaderboard: list[dict[str, Any]] = []
    winner: dict[str, Any] | None = None
    for min_token_frequency in token_frequency_grid:
        X, y, groups, meta = build_design_matrix(segment, min_token_frequency=min_token_frequency)
        feature_frame = X.loc[:, list(meta.gbm_feature_columns)]
        splits = group_kfold_splits(groups)
        if not splits:
            continue
        for family in families:
            best = grouped_random_search(
                feature_frame,
                y,
                groups,
                family,
                space=spaces.get(family),
                n_iter=n_iter,
                splits=splits,
                seed=random_state,
                n_jobs=n_jobs,
            )
            if best is None:
                continue
            entry = {
                "min_token_frequency": int(min_token_frequency),
                "family": best["family"],
                "params": best["params"],
                "metrics": best["metrics"],
            }
            leaderboard.append(entry)
            if winner is None or _is_better(entry["metrics"], winner["metrics"]):
                winner = entry
    if winner is None:
        return None
    leaderboard.sort(key=lambda item: item["metrics"]["mae_eur_mean"])
    winner = dict(winner)
    winner["leaderboard"] = leaderboard
    return winner


def fit_hedonic_models(
    frame: pd.DataFrame,
    *,
    include_guest_house: bool = False,
    min_token_frequency: int | None = None,
    tune: bool = False,
    token_frequency_grid: Iterable[int] = DEFAULT_TOKEN_FREQUENCY_GRID,
    search_n_iter: int = DEFAULT_SEARCH_N_ITER,
    search_n_jobs: int = DEFAULT_SEARCH_N_JOBS,
    search_spaces: dict[str, dict[str, tuple]] | None = None,
    model_params: dict[str, Any] | None = None,
    model_family: str = GBR_FAMILY,
    conformal_coverage: float = 0.8,
    fit_quantile_models: bool = True,
) -> HedonicModelBundle:
    """Train OLS and a grouped-CV booster on the self-catering segment.

    Fast by default (fixed params) so interactive callers stay responsive. Two
    ways to get the tuned booster:

    - ``tune=True`` runs the GBM-vs-HistGBM bake-off over the token-frequency grid
      here and now (minutes). Used by the offline tuning script.
    - ``model_family`` + ``model_params`` (+ ``min_token_frequency``) apply an
      already-chosen config (e.g. the frozen winner loaded from disk) on the fast
      path, so reports ship the tuned model without re-searching.
    """

    segment = segment_self_catering(frame, include_guest_house=include_guest_house)

    winner: dict[str, Any] | None = None
    if tune and min_token_frequency is None:
        winner = tune_hedonic_booster(
            segment,
            token_frequency_grid=token_frequency_grid,
            search_spaces=search_spaces,
            n_iter=search_n_iter,
            n_jobs=search_n_jobs,
        )

    if winner is not None:
        resolved_mtf = winner["min_token_frequency"]
        family = winner["family"]
        params = winner["params"]
        leaderboard = tuple(winner["leaderboard"])
        cv_metrics: dict[str, Any] = dict(winner["metrics"])
    else:
        resolved_mtf = min_token_frequency if min_token_frequency is not None else 25
        family = model_family
        params = dict(model_params) if model_params is not None else dict(DEFAULT_GBR_PARAMS)
        leaderboard = ()
        cv_metrics = {}

    X, y, groups, meta = build_design_matrix(segment, min_token_frequency=resolved_mtf)
    ols_results = train_ols(X, y, meta)
    gbm_model, fold_metrics = train_gradient_boosting(X, y, groups, meta, family=family, params=params)
    if not cv_metrics:
        cv_metrics = fold_metrics

    # Calibrate the prediction band on the same grouped folds the booster is
    # validated over, so the reported ± reflects out-of-property error.
    feature_frame = X.loc[:, list(meta.gbm_feature_columns)]
    conformal_residuals = grouped_conformal_residuals(
        feature_frame, y, groups, family, params
    )
    quantile_models = (
        _fit_quantile_models(feature_frame, y, coverage=conformal_coverage)
        if fit_quantile_models
        else {}
    )

    cv_metrics = dict(cv_metrics)
    cv_metrics.update(
        {
            "model_family": family,
            "model_params": dict(params),
            "min_token_frequency": int(resolved_mtf),
            "tuned": winner is not None,
            "conformal_coverage": float(conformal_coverage),
            "conformal_residual_count": int(conformal_residuals.size),
        }
    )

    return HedonicModelBundle(
        feature_meta=meta,
        ols_results=ols_results,
        gbm_model=gbm_model,
        cv_metrics=cv_metrics,
        training_rows=int(segment.shape[0]),
        training_properties=int(segment["property_url"].nunique(dropna=True)),
        model_family=family,
        model_params=dict(params),
        min_token_frequency=int(resolved_mtf),
        search_leaderboard=leaderboard,
        conformal_residuals=conformal_residuals,
        conformal_coverage=float(conformal_coverage),
        quantile_models=quantile_models,
    )


def fit_selected_hedonic_models(
    frame: pd.DataFrame,
    *,
    include_guest_house: bool = False,
    min_token_frequency: int | None = None,
    conformal_coverage: float = 0.8,
    fit_quantile_models: bool = True,
) -> HedonicModelBundle:
    """Fit the frozen bake-off winner (see ``SELECTED_MODEL_*``).

    A thin wrapper over :func:`fit_hedonic_models` that pins the tuned family,
    params, and token-frequency floor so every deliverable ships the same chosen
    model and the same calibrated prediction band. ``min_token_frequency`` may be
    overridden (tests use a lower floor on tiny synthetic frames); everything else
    stays fixed to the selected configuration.
    """

    return fit_hedonic_models(
        frame,
        include_guest_house=include_guest_house,
        min_token_frequency=(
            SELECTED_MIN_TOKEN_FREQUENCY if min_token_frequency is None else min_token_frequency
        ),
        model_family=SELECTED_MODEL_FAMILY,
        model_params=dict(SELECTED_MODEL_PARAMS),
        conformal_coverage=conformal_coverage,
        fit_quantile_models=fit_quantile_models,
    )


def predict_log_prices(bundle: HedonicModelBundle, rows: pd.DataFrame) -> pd.Series:
    """Predict log EUR/night with the fitted gradient-boosting model."""

    X, _, _, _ = build_design_matrix(rows, feature_meta=bundle.feature_meta)
    values = bundle.gbm_model.predict(X.loc[:, list(bundle.feature_meta.gbm_feature_columns)])
    return pd.Series(values, index=rows.index, name="predicted_log_price")


def predict_prices(bundle: HedonicModelBundle, rows: pd.DataFrame) -> pd.Series:
    """Predict EUR/night with the fitted gradient-boosting model."""

    return np.exp(predict_log_prices(bundle, rows)).rename("predicted_price_per_night")


# --------------------------------------------------------------------------- #
# Prediction uncertainty
#
# The point prediction is a false-precision headline on its own. Grouped
# split-conformal turns the model's *own* out-of-sample error distribution into
# a band: we collect log-scale residuals on held-out properties (GroupKFold by
# ``property_url``, so a property never calibrates its own interval), then read
# tail quantiles of those residuals. Because the folds group by property, the
# band reflects genuine cross-property generalization error, not in-sample fit.
# Conformal is the reported headline; the optional HistGBM quantile models give
# a feature-dependent width for callers that want it.
# --------------------------------------------------------------------------- #


def grouped_conformal_residuals(
    feature_frame: pd.DataFrame,
    y: pd.Series,
    groups: pd.Series,
    family: str,
    params: dict[str, Any],
    *,
    random_state: int = RANDOM_SEED,
    splits: list[tuple[np.ndarray, np.ndarray]] | None = None,
) -> np.ndarray:
    """Out-of-fold log-scale residuals ``actual - predicted`` over grouped folds.

    Each fold refits the chosen booster on the training groups and predicts the
    held-out groups, so every residual comes from a property the fold's model
    never saw. Returns an empty array when there are too few groups to split.
    """

    fold_splits = splits if splits is not None else group_kfold_splits(groups)
    if not fold_splits:
        return np.empty(0, dtype=float)
    residuals: list[np.ndarray] = []
    for train_idx, test_idx in fold_splits:
        model = _make_estimator(family, params, random_state)
        model.fit(feature_frame.iloc[train_idx], y.iloc[train_idx])
        predictions = np.asarray(model.predict(feature_frame.iloc[test_idx]), dtype=float)
        residuals.append(np.asarray(y.iloc[test_idx], dtype=float) - predictions)
    return np.concatenate(residuals) if residuals else np.empty(0, dtype=float)


def _fit_quantile_models(
    feature_frame: pd.DataFrame,
    y: pd.Series,
    *,
    coverage: float,
    random_state: int = RANDOM_SEED,
) -> dict[str, Any]:
    """Fit lower/upper HistGBM quantile regressors at the coverage's tails."""

    lower_q, upper_q = _coverage_tail_quantiles(coverage)
    models: dict[str, Any] = {}
    for name, quantile in (("lower", lower_q), ("upper", upper_q)):
        model = HistGradientBoostingRegressor(
            loss="quantile", quantile=quantile, random_state=random_state
        )
        model.fit(feature_frame, y)
        models[name] = model
    return models


def _coverage_tail_quantiles(coverage: float) -> tuple[float, float]:
    """Two-sided tail quantiles for a central ``coverage`` interval."""

    if not 0.0 < coverage < 1.0:
        raise HedonicModelError("coverage must be strictly between 0 and 1")
    lower = (1.0 - coverage) / 2.0
    return lower, 1.0 - lower


def residual_quantiles(residuals: np.ndarray, coverage: float) -> tuple[float, float]:
    """Asymmetric log-scale residual offsets for a central ``coverage`` band.

    Uses signed-residual quantiles (not symmetric absolute error) so a skewed
    error distribution yields an asymmetric band. Returns ``(0.0, 0.0)`` when no
    residuals are available, collapsing the band onto the point prediction.
    """

    residuals = np.asarray(residuals, dtype=float)
    if residuals.size == 0:
        return 0.0, 0.0
    lower_q, upper_q = _coverage_tail_quantiles(coverage)
    return float(np.quantile(residuals, lower_q)), float(np.quantile(residuals, upper_q))


def prediction_interval(
    bundle: HedonicModelBundle,
    rows: pd.DataFrame,
    *,
    coverage: float | None = None,
) -> pd.DataFrame:
    """Point prediction plus a split-conformal EUR/night band per row.

    ``coverage`` defaults to the bundle's calibrated ``conformal_coverage``. The
    band is ``exp(pred_log + q_lo)`` .. ``exp(pred_log + q_hi)`` where the offsets
    are tail quantiles of the grouped out-of-fold residuals -- always ordered
    ``lower <= point <= upper``.
    """

    resolved_coverage = bundle.conformal_coverage if coverage is None else coverage
    log_pred = predict_log_prices(bundle, rows)
    q_lo, q_hi = residual_quantiles(bundle.conformal_residuals, resolved_coverage)
    return pd.DataFrame(
        {
            "predicted_price_per_night": np.exp(log_pred),
            "lower_price_per_night": np.exp(log_pred + q_lo),
            "upper_price_per_night": np.exp(log_pred + q_hi),
        },
        index=rows.index,
    )


def price_band(
    price: float,
    bundle: HedonicModelBundle,
    *,
    coverage: float | None = None,
) -> dict[str, float]:
    """Attach a conformal ± band to an already-computed EUR price (e.g. the
    feature-adjusted peer median or a price gap).

    The residual offsets are multiplicative on the price scale, so the band is
    ``price * exp(q_lo)`` .. ``price * exp(q_hi)``. This lets deliverables report
    "adjusted peer median EUR X (EUR lower .. EUR upper)" using the same
    calibrated width as the per-row model band.
    """

    resolved_coverage = bundle.conformal_coverage if coverage is None else coverage
    q_lo, q_hi = residual_quantiles(bundle.conformal_residuals, resolved_coverage)
    value = float(price)
    return {
        "price": value,
        "lower": value * math.exp(q_lo),
        "upper": value * math.exp(q_hi),
        "coverage": float(resolved_coverage),
    }


def quantile_interval(
    bundle: HedonicModelBundle,
    rows: pd.DataFrame,
) -> pd.DataFrame | None:
    """Feature-dependent EUR/night band from the optional HistGBM quantile models.

    Returns ``None`` when no quantile models were fitted. Lower/upper are sorted
    per row so numerical crossings never invert the band.
    """

    models = bundle.quantile_models
    if not models or "lower" not in models or "upper" not in models:
        return None
    X, _, _, _ = build_design_matrix(rows, feature_meta=bundle.feature_meta)
    feature_frame = X.loc[:, list(bundle.feature_meta.gbm_feature_columns)]
    lower_log = np.asarray(models["lower"].predict(feature_frame), dtype=float)
    upper_log = np.asarray(models["upper"].predict(feature_frame), dtype=float)
    low = np.exp(np.minimum(lower_log, upper_log))
    high = np.exp(np.maximum(lower_log, upper_log))
    point = np.exp(predict_log_prices(bundle, rows))
    return pd.DataFrame(
        {
            "predicted_price_per_night": point.to_numpy(),
            "lower_price_per_night": low,
            "upper_price_per_night": high,
        },
        index=rows.index,
    )


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


# The feature-adjustment counterfactual re-scores each peer as if it carried the
# client's features. Swapping the client's *entire* sparse amenity/facility
# token bundle into every peer pushes the tree off the training distribution and
# lets a long tail of incidental, low-frequency binary flags compound into an
# implausible adjustment (the observed +76% Stavros swing). We instead transfer
# only the coherent, dense, high-signal features -- structured numerics,
# subscores, location, property type, and the curated ``hq__`` quality flags --
# and hold each peer's own sparse one-hots fixed.
FEATURE_ADJUSTMENT_FACTOR_BOUNDS = (0.5, 2.0)


def _adjustment_transfer_columns(meta: HedonicFeatureMeta) -> tuple[str, ...]:
    """GBM feature columns whose value is taken from the client in the counterfactual.

    Everything the model sees is transferred *except* the sparse per-token
    ``amenity__``/``facility__`` one-hots, which stay at each peer's own value.
    The curated ``hq__`` quality flags are retained because they are dense,
    hand-picked, and coherent.
    """

    excluded: set[str] = set()
    for token in meta.amenity_vocabulary:
        excluded.add(_safe_feature_name("amenity__", token))
    for token in meta.facility_vocabulary:
        excluded.add(_safe_feature_name("facility__", token))
    return tuple(column for column in meta.gbm_feature_columns if column not in excluded)


def feature_adjusted_peer_prices(
    client: str | dict[str, Any] | pd.Series,
    peer_rows: pd.DataFrame,
    frame: pd.DataFrame,
    bundle: HedonicModelBundle,
    *,
    factor_bounds: tuple[float, float] | None = FEATURE_ADJUSTMENT_FACTOR_BOUNDS,
) -> pd.DataFrame:
    """Return peer rows adjusted to the client's feature profile.

    The adjustment is a curated counterfactual: each peer is re-scored with the
    client's high-signal features (size, beds, star, review score/count,
    subscores, location, property type, and curated ``hq__`` quality flags)
    substituted in, while its own sparse amenity/facility one-hots are held
    fixed. The resulting multiplier is clipped to ``factor_bounds`` as an
    outlier guard against single-peer extrapolation (pass ``None`` to disable).
    """

    if peer_rows.empty:
        return peer_rows.copy()
    meta = bundle.feature_meta
    client_values = _profile_values(client, frame)
    client_like_rows = peer_rows.copy()
    for column, value in client_values.items():
        if isinstance(value, (list, tuple, dict, set, frozenset)):
            client_like_rows[column] = [value] * len(client_like_rows)
        else:
            client_like_rows[column] = value

    gbm_columns = list(meta.gbm_feature_columns)
    X_peer, _, _, _ = build_design_matrix(peer_rows, feature_meta=meta)
    X_client_like, _, _, _ = build_design_matrix(client_like_rows, feature_meta=meta)

    # Peer baseline, then a counterfactual that copies only the curated columns
    # from the fully-client-featured encoding onto the peer's own row.
    X_counterfactual = X_peer.copy()
    for column in _adjustment_transfer_columns(meta):
        X_counterfactual[column] = X_client_like[column].to_numpy()

    peer_predicted_log = bundle.gbm_model.predict(X_peer.loc[:, gbm_columns])
    client_predicted_log = bundle.gbm_model.predict(X_counterfactual.loc[:, gbm_columns])
    factor = np.exp(client_predicted_log - peer_predicted_log)
    if factor_bounds is not None:
        factor = np.clip(factor, factor_bounds[0], factor_bounds[1])

    adjusted = peer_rows.copy()
    adjusted["predicted_peer_price_per_night"] = np.exp(peer_predicted_log)
    adjusted["predicted_client_like_price_per_night"] = np.exp(client_predicted_log)
    adjusted["feature_adjustment_factor"] = factor
    adjusted["feature_adjusted_price_per_night"] = (
        pd.to_numeric(adjusted["price_per_night"], errors="coerce").to_numpy() * factor
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
