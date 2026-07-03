"""Write a markdown hedonic adjustment and price-gap report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tourism_pricing_analytics.analysis.competitors import (
    ComparableBenchmarkConfig,
    peer_price_benchmark,
)
from tourism_pricing_analytics.analysis.hedonic import (
    SELECTED_MIN_TOKEN_FREQUENCY,
    HedonicModelBundle,
    explain_price_gap,
    feature_adjusted_peer_prices,
    fit_selected_hedonic_models,
    price_band,
)
from tourism_pricing_analytics.analysis.loader import (
    DEFAULT_HEDONIC_TRAINING_TABLE,
    DEFAULT_MODELLING_TABLE,
    load_modelling_table,
)
from tourism_pricing_analytics.analysis.segment import segment_self_catering

DEFAULT_REPORT_PATH = REPO_ROOT / "data" / "modelling" / "hedonic_report.md"


def _default_subject_url(frame: pd.DataFrame) -> str:
    segment = segment_self_catering(frame)
    grouped = (
        segment.groupby(["property_url", "property_name"], dropna=False)
        .size()
        .reset_index(name="price_row_count")
    )
    selected = grouped.sort_values(
        ["price_row_count", "property_name", "property_url"],
        ascending=[False, True, True],
    ).head(1)
    if selected.empty:
        raise SystemExit("No self-catering subject property is available.")
    return str(selected.iloc[0]["property_url"])


def _load_spec(args: argparse.Namespace) -> dict[str, Any] | None:
    if args.spec_json and args.spec_path:
        raise SystemExit("Use either --spec-json or --spec-path, not both.")
    if args.spec_json:
        return json.loads(args.spec_json)
    if args.spec_path:
        return json.loads(args.spec_path.read_text(encoding="utf-8"))
    return None


def _normalize_windows(raw: list[str] | None) -> list[dict[str, Any]] | None:
    if not raw:
        return None
    return [json.loads(value) for value in raw]


def _date_key(value: object) -> str | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date().isoformat()


def _filter_rows_by_windows(rows: pd.DataFrame, windows: list[dict[str, Any]]) -> pd.DataFrame:
    if not windows:
        return rows.copy()
    masks = []
    for window in windows:
        mask = pd.Series(True, index=rows.index)
        for key, value in window.items():
            if key not in rows:
                continue
            if key in {"checkin", "checkout"}:
                mask &= rows[key].map(_date_key) == _date_key(value)
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


def _distribution(series: pd.Series) -> dict[str, float | int | None]:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return {"count": 0, "p25": None, "median": None, "p75": None}
    quantiles = values.quantile([0.25, 0.5, 0.75])
    return {
        "count": int(values.shape[0]),
        "p25": float(quantiles.loc[0.25]),
        "median": float(quantiles.loc[0.5]),
        "p75": float(quantiles.loc[0.75]),
    }


def _json_safe_value(value: object) -> Any:
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if hasattr(value, "isoformat") and value.__class__.__name__ in {"date", "datetime"}:
        return value.isoformat()
    if isinstance(value, float) and pd.isna(value):
        return None
    if value is pd.NA:
        return None
    if hasattr(value, "item"):
        return _json_safe_value(value.item())
    return value


def _adjusted_peer_row_records(adjusted_rows: pd.DataFrame) -> list[dict[str, Any]]:
    columns = [
        "property_name",
        "property_url",
        "room_id",
        "room_name",
        "block_id",
        "checkin",
        "checkout",
        "lead_time_days",
        "stay_length_days",
        "price_per_night",
        "predicted_peer_price_per_night",
        "predicted_client_like_price_per_night",
        "feature_adjustment_factor",
        "feature_adjusted_price_per_night",
    ]
    available = [column for column in columns if column in adjusted_rows]
    sort_columns = [
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
        if column in adjusted_rows
    ]
    rows = adjusted_rows.sort_values(sort_columns)[available] if sort_columns else adjusted_rows[available]
    return [
        {key: _json_safe_value(value) for key, value in record.items()}
        for record in rows.to_dict(orient="records")
    ]


def _fmt_money(value: object) -> str:
    if value is None:
        return "n/a"
    return f"EUR {float(value):,.2f}"


def _fmt_number(value: object, digits: int = 3) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.{digits}f}"


def _fmt_coverage(value: object) -> str:
    if value is None:
        return "n/a"
    return f"{float(value) * 100:.0f}%"


def _model_label(params: object) -> str:
    if not isinstance(params, dict) or not params:
        return "default parameters"
    return ", ".join(f"{key}={params[key]}" for key in sorted(params))


def _ols_table(payload: dict[str, Any], limit: int = 12) -> list[str]:
    rows = payload["ols_coefficients"][:limit]
    lines = [
        "| Feature | Coefficient | Robust SE | p-value |",
        "| --- | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            "| {feature} | {coef} | {se} | {pvalue} |".format(
                feature=row["feature"],
                coef=_fmt_number(row["coefficient"], 4),
                se=_fmt_number(row["robust_se"], 4),
                pvalue=_fmt_number(row["p_value"], 4),
            )
        )
    return lines


def _gap_lines(gap: dict[str, Any] | None) -> list[str]:
    if gap is None:
        return ["No matched subject/peer row was available for a gap example."]
    return [
        f"- Client observed price: {_fmt_money(gap['client_price_per_night'])}",
        f"- Competitor observed price: {_fmt_money(gap['competitor_price_per_night'])}",
        f"- Observed gap: {_fmt_money(gap['observed_gap'])}",
        f"- Feature-explained gap: {_fmt_money(gap['feature_explained_gap'])}",
        f"- Residual gap: {_fmt_money(gap['residual_gap'])}",
    ]


def render_markdown_report(payload: dict[str, Any]) -> str:
    benchmark = payload["benchmark"]
    adjusted = payload["adjusted_peer_price_distribution"]
    adjusted_band = payload.get("adjusted_peer_price_band")
    metrics = payload["cv_metrics"]
    gap = payload["gap_explanation"]
    coverage = payload.get("conformal_coverage", metrics.get("conformal_coverage"))

    lines = [
        "# Hedonic Price Adjustment",
        "",
        f"Comparable source table: `{payload['source_table']}`",
        f"Hedonic training table: `{payload['training_source_table']}`",
        "",
        "Price unit: EUR/night for a 2-guest Booking.com search. The model explains listed asking prices for available offers, not transacted demand.",
        "",
        "## Training Summary",
        "",
        f"- Rows: {payload['training_rows']}",
        f"- Properties: {payload['training_properties']}",
        f"- Grouped CV folds: {metrics['folds']}",
        f"- GBM mean log R2: {_fmt_number(metrics['r2_log_mean'])}",
        f"- GBM mean log MAE: {_fmt_number(metrics['mae_log_mean'])}",
        f"- GBM mean EUR/night MAE: {_fmt_money(metrics['mae_eur_mean'])}",
        f"- OLS R2: {_fmt_number(payload['ols_r2'])}",
        f"- OLS condition number: {_fmt_number(payload['ols_condition_number'], 1)}",
        "",
        "## Selected Model",
        "",
        f"- Family: {metrics.get('model_family', 'n/a')} (grouped-CV bake-off winner)",
        f"- Params: {_model_label(metrics.get('model_params'))}",
        f"- Amenity token floor: {metrics.get('min_token_frequency', 'n/a')}",
        f"- Prediction band: {_fmt_coverage(coverage)} split-conformal interval from "
        f"{metrics.get('conformal_residual_count', 'n/a')} out-of-fold residuals",
        "",
        "## OLS Market Premia",
        "",
        *_ols_table(payload),
        "",
        "## Feature-Adjusted Comparable Benchmark",
        "",
        f"- Client: {benchmark['client'].get('property_name') or 'n/a'}",
        f"- Raw peer median: {_fmt_money(benchmark['peer_price_distribution']['median'])}",
        f"- Feature-adjusted peer median: {_fmt_money(adjusted['median'])}",
        f"- {_fmt_coverage(coverage)} conformal band: "
        + (
            f"{_fmt_money(adjusted_band['lower'])} to {_fmt_money(adjusted_band['upper'])}"
            if adjusted_band
            else "n/a"
        ),
        f"- Feature-adjusted IQR: {_fmt_money(adjusted['p25'])} to {_fmt_money(adjusted['p75'])}",
        f"- Adjusted peer rows: {adjusted['count']}",
        "",
        "## Price Gap Decomposition",
        "",
        *_gap_lines(gap),
        "",
    ]
    return "\n".join(lines)


def _coefficient_records(bundle) -> list[dict[str, float | str]]:
    params = bundle.ols_results.params.drop(labels=["const"], errors="ignore")
    bse = bundle.ols_results.bse.reindex(params.index)
    pvalues = bundle.ols_results.pvalues.reindex(params.index)
    rows = [
        {
            "feature": str(feature),
            "coefficient": float(params.loc[feature]),
            "robust_se": float(bse.loc[feature]),
            "p_value": float(pvalues.loc[feature]),
        }
        for feature in params.index
    ]
    rows.sort(key=lambda row: abs(float(row["coefficient"])), reverse=True)
    return rows


def build_report_payload(
    frame: pd.DataFrame,
    *,
    source_table: str,
    client: str | dict[str, Any],
    windows: list[dict[str, Any]] | None = None,
    max_peers: int = ComparableBenchmarkConfig.max_peers,
    max_distance_km: float = ComparableBenchmarkConfig.max_distance_km,
    min_token_frequency: int = SELECTED_MIN_TOKEN_FREQUENCY,
    bundle: HedonicModelBundle | None = None,
    training_frame: pd.DataFrame | None = None,
    training_source_table: str | None = None,
) -> dict[str, Any]:
    if bundle is None:
        bundle = fit_selected_hedonic_models(
            training_frame if training_frame is not None else frame,
            min_token_frequency=min_token_frequency,
        )
    benchmark = peer_price_benchmark(
        client,
        frame,
        windows,
        k=max_peers,
        max_distance_km=max_distance_km,
    )

    segment = segment_self_catering(frame)
    peer_urls = [peer["property_url"] for peer in benchmark["peers"]]
    peer_rows = segment.loc[segment["property_url"].isin(peer_urls)].copy()
    peer_rows = _filter_rows_by_windows(peer_rows, benchmark["benchmark_windows"])
    adjusted_rows = feature_adjusted_peer_prices(client, peer_rows, segment, bundle)
    adjusted_distribution = (
        _distribution(adjusted_rows["feature_adjusted_price_per_night"])
        if not adjusted_rows.empty
        else _distribution(pd.Series(dtype=float))
    )
    adjusted_median = adjusted_distribution["median"]
    adjusted_band = (
        price_band(adjusted_median, bundle) if adjusted_median is not None else None
    )

    gap = None
    subject_url = benchmark["client"].get("property_url")
    if subject_url and not adjusted_rows.empty:
        subject_rows = segment.loc[segment["property_url"] == subject_url].copy()
        subject_rows = _filter_rows_by_windows(subject_rows, benchmark["benchmark_windows"])
        if not subject_rows.empty:
            gap = explain_price_gap(
                subject_rows.sort_values(["checkin", "price_per_night"]).iloc[0],
                adjusted_rows.sort_values(["checkin", "price_per_night"]).iloc[0],
                segment,
                bundle,
            )

    return {
        "source_table": source_table,
        "training_source_table": training_source_table or source_table,
        "training_rows": bundle.training_rows,
        "training_properties": bundle.training_properties,
        "cv_metrics": bundle.cv_metrics,
        "ols_r2": float(bundle.ols_results.rsquared),
        "ols_condition_number": float(bundle.ols_results.condition_number),
        "ols_coefficients": _coefficient_records(bundle),
        "benchmark": benchmark,
        "adjusted_peer_price_distribution": adjusted_distribution,
        "adjusted_peer_price_band": adjusted_band,
        "conformal_coverage": float(bundle.conformal_coverage),
        "adjusted_peer_price_rows": _adjusted_peer_row_records(adjusted_rows),
        "gap_explanation": gap,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=DEFAULT_MODELLING_TABLE)
    parser.add_argument(
        "--training-path",
        type=Path,
        default=DEFAULT_HEDONIC_TRAINING_TABLE,
        help="Broader table for hedonic model training. Defaults to the committed broad training table.",
    )
    parser.add_argument("--subject-url", default=None)
    parser.add_argument("--spec-json", default=None)
    parser.add_argument("--spec-path", type=Path, default=None)
    parser.add_argument("--window", action="append", help="Benchmark window as JSON. Repeatable.")
    parser.add_argument("--max-peers", type=int, default=ComparableBenchmarkConfig.max_peers)
    parser.add_argument("--max-distance-km", type=float, default=ComparableBenchmarkConfig.max_distance_km)
    parser.add_argument("--min-token-frequency", type=int, default=SELECTED_MIN_TOKEN_FREQUENCY)
    parser.add_argument("--out", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args()

    frame = load_modelling_table(args.path)
    training_frame = load_modelling_table(args.training_path)
    spec = _load_spec(args)
    if spec is not None and args.subject_url:
        raise SystemExit("Use either --subject-url or a spec, not both.")
    client: str | dict[str, Any] = spec or args.subject_url or _default_subject_url(frame)
    payload = build_report_payload(
        frame,
        source_table=str(args.path),
        client=client,
        windows=_normalize_windows(args.window),
        max_peers=args.max_peers,
        max_distance_km=args.max_distance_km,
        min_token_frequency=args.min_token_frequency,
        training_frame=training_frame,
        training_source_table=str(args.training_path),
    )
    report = render_markdown_report(payload)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report + "\n", encoding="utf-8")
    print(report)

    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
