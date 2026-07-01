"""Analysis helpers for downstream pricing work."""

from tourism_pricing_analytics.analysis.competitors import (
    ComparableBenchmarkConfig,
    ComparableClientSpec,
    client_spec_from_mapping,
    comparable_benchmark,
    comparable_benchmarks,
    feature_similarity,
    peer_price_benchmark,
    rank_competitors,
)
from tourism_pricing_analytics.analysis.dashboard import (
    render_index_html,
    shape_dashboard_payload,
    subject_catalog,
    window_options,
)
from tourism_pricing_analytics.analysis.eda import modelling_table_summary
from tourism_pricing_analytics.analysis.hedonic import (
    HedonicFeatureMeta,
    HedonicModelBundle,
    build_design_matrix,
    explain_price_gap,
    feature_adjusted_peer_prices,
    fit_hedonic_models,
    group_kfold_splits,
)
from tourism_pricing_analytics.analysis.loader import load_modelling_table
from tourism_pricing_analytics.analysis.movement import (
    add_peer_market_context,
    build_peer_market_movement_table,
    build_price_movement_table,
    select_movement_peers,
)
from tourism_pricing_analytics.analysis.narrative import render_positioning_narrative
from tourism_pricing_analytics.analysis.segment import segment_self_catering

__all__ = [
    "ComparableBenchmarkConfig",
    "ComparableClientSpec",
    "HedonicFeatureMeta",
    "HedonicModelBundle",
    "build_design_matrix",
    "build_peer_market_movement_table",
    "build_price_movement_table",
    "client_spec_from_mapping",
    "comparable_benchmark",
    "comparable_benchmarks",
    "explain_price_gap",
    "feature_similarity",
    "feature_adjusted_peer_prices",
    "fit_hedonic_models",
    "group_kfold_splits",
    "load_modelling_table",
    "modelling_table_summary",
    "peer_price_benchmark",
    "rank_competitors",
    "render_index_html",
    "render_positioning_narrative",
    "segment_self_catering",
    "select_movement_peers",
    "shape_dashboard_payload",
    "subject_catalog",
    "window_options",
    "add_peer_market_context",
]
