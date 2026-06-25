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
from tourism_pricing_analytics.analysis.eda import modelling_table_summary
from tourism_pricing_analytics.analysis.loader import load_modelling_table
from tourism_pricing_analytics.analysis.segment import segment_self_catering

__all__ = [
    "ComparableBenchmarkConfig",
    "ComparableClientSpec",
    "client_spec_from_mapping",
    "comparable_benchmark",
    "comparable_benchmarks",
    "feature_similarity",
    "load_modelling_table",
    "modelling_table_summary",
    "peer_price_benchmark",
    "rank_competitors",
    "segment_self_catering",
]
