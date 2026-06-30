"""Client-facing positioning narrative for the pricing analytics deliverable.

This module is intentionally pure: it consumes the report payload produced by
``scripts.run_hedonic.build_report_payload`` (a plain JSON-safe dict) and turns
the raw technical figures from the comparable benchmark and hedonic adjustment
into a single plain-language positioning narrative for a non-technical operator.

It does not load data or fit models, so it can be tested against synthetic
payloads without the modelling table or scikit-learn.
"""

from __future__ import annotations

from typing import Any

__all__ = ["render_positioning_narrative"]


def _num(value: object) -> float | None:
    """Coerce a payload value to ``float`` or ``None`` when it is missing."""

    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result:  # NaN guard without importing math/pandas.
        return None
    return result


def _fmt_money(value: object) -> str:
    number = _num(value)
    if number is None:
        return "n/a"
    return f"EUR {number:,.2f}"


def _fmt_pct(value: object, *, digits: int = 1) -> str:
    number = _num(value)
    if number is None:
        return "n/a"
    return f"{number:.{digits}f}%"


def _percentile_band(percentile: float | None) -> str:
    """Plain-language band for the subject's percentile against peers."""

    if percentile is None:
        return "an unclear position relative to"
    if percentile >= 90:
        return "at the very top of"
    if percentile >= 75:
        return "well above the middle of"
    if percentile >= 55:
        return "above the middle of"
    if percentile > 45:
        return "around the middle of"
    if percentile > 25:
        return "below the middle of"
    if percentile > 10:
        return "well below the middle of"
    return "at the very bottom of"


def _position_class(residual_pct: float | None) -> str:
    """Classify the feature-adjusted position from the residual premium share.

    ``residual_pct`` is the subject's price above (or below) the feature-matched
    comparable median, as a fraction of that median. This is the actionable
    number: it isolates how much is charged beyond a like-for-like rival, after
    accounting for the subject's measurable feature profile.
    """

    if residual_pct is None:
        return "insufficient"
    if residual_pct > 0.15:
        return "unjustified_premium"
    if residual_pct > 0.05:
        return "mixed_premium"
    if residual_pct >= -0.05:
        return "fair"
    return "underpriced"


def _client_name(payload: dict[str, Any]) -> str:
    client = payload.get("benchmark", {}).get("client", {}) or {}
    name = client.get("property_name")
    if name:
        return str(name)
    if client.get("property_url"):
        return str(client["property_url"])
    return "your property"


def _bottom_line(
    *,
    name: str,
    percentile: float | None,
    gap_pct: float | None,
    position_class: str,
) -> list[str]:
    band = _percentile_band(percentile)
    if gap_pct is None:
        position = (
            f"{name} sits {band} the comparable local market, but there were not "
            "enough matched peer prices to quantify the gap precisely."
        )
    elif gap_pct > 2:
        position = (
            f"{name} is priced above its comparable local rivals, sitting {band} "
            f"the peer set at about {_fmt_pct(gap_pct)} over the peer median asking price."
        )
    elif gap_pct < -2:
        position = (
            f"{name} is priced below its comparable local rivals, sitting {band} "
            f"the peer set at about {_fmt_pct(abs(gap_pct))} under the peer median asking price."
        )
    else:
        position = (
            f"{name} is priced roughly in line with its comparable local rivals, "
            f"sitting {band} the peer set."
        )

    lines = [position]

    feature_adjusted = {
        "unjustified_premium": (
            "Even after adjusting for measurable features, you sit well above a "
            "like-for-like rival, so most of the gap reads as pricing power to defend "
            "or an over-pricing risk to watch."
        ),
        "mixed_premium": (
            "After adjusting for measurable features, a modest premium remains over a "
            "like-for-like rival, reflecting pricing power or a little over-pricing risk."
        ),
        "fair": (
            "Once features are accounted for, you are priced fairly against a "
            "like-for-like rival."
        ),
        "underpriced": (
            "Once features are accounted for, like-for-like rivals list above your price, "
            "suggesting headroom you are not capturing."
        ),
    }.get(position_class)
    if feature_adjusted is not None:
        lines.append(feature_adjusted)
    return lines


def _peer_set_lines(payload: dict[str, Any]) -> list[str]:
    benchmark = payload.get("benchmark", {})
    coverage = benchmark.get("coverage", {}) or {}
    peer_set = benchmark.get("peer_set", {}) or {}
    peers = benchmark.get("peers", []) or []

    peer_rows = coverage.get("peer_price_rows")
    peer_props = peer_set.get("peer_properties_with_prices")

    lines = [
        "Your peer set is built from nearby self-catering properties that most "
        "resemble yours on type, size, and guest-rated quality, then matched on the "
        "same check-in dates, lead times, and stay lengths you were scraped for.",
        "",
        f"- Comparable properties with live prices: {peer_props if peer_props is not None else 'n/a'}",
        f"- Matched peer price offers: {peer_rows if peer_rows is not None else 'n/a'}",
    ]

    named = [p for p in peers if p.get("median_price_per_night") is not None][:5]
    if named:
        lines.append("")
        lines.append("Closest comparables by proximity and similarity:")
        lines.append("")
        for peer in named:
            name = peer.get("property_name") or peer.get("property_url") or "Unnamed property"
            ptype = peer.get("property_type") or "n/a"
            distance = _num(peer.get("distance_km"))
            distance_text = "n/a" if distance is None else f"{distance:.1f} km away"
            price = _fmt_money(peer.get("median_price_per_night"))
            lines.append(f"- {name} ({ptype}, {distance_text}) at {price} median")

    flags = peer_set.get("flags") or []
    if flags:
        lines.append("")
        lines.append(
            "Coverage caveats: " + ", ".join(str(flag) for flag in flags) + "."
        )
    return lines


def _price_position_lines(payload: dict[str, Any]) -> list[str]:
    benchmark = payload.get("benchmark", {})
    peer_dist = benchmark.get("peer_price_distribution", {}) or {}
    subject_dist = benchmark.get("subject_price_distribution", {}) or {}
    percentile = _num(benchmark.get("subject_percentile_vs_peers"))
    gap = benchmark.get("price_gap_to_peer_median")
    gap_pct_raw = _num(benchmark.get("price_gap_to_peer_median_pct"))
    gap_pct = None if gap_pct_raw is None else gap_pct_raw * 100

    return [
        f"- Your median asking price in these windows: {_fmt_money(subject_dist.get('median'))}",
        f"- Comparable peer median: {_fmt_money(peer_dist.get('median'))}",
        f"- Typical peer range (middle 50%): {_fmt_money(peer_dist.get('p25'))} to {_fmt_money(peer_dist.get('p75'))}",
        f"- Where you land among peers: {_fmt_pct(percentile)} percentile",
        f"- Gap to the peer median: {_fmt_money(gap)} ({_fmt_pct(gap_pct)})",
    ]


def _premium_lines(
    *,
    raw_peer_median: float | None,
    adjusted_peer_median: float | None,
    subject_median: float | None,
    feature_premium: float | None,
    residual_premium: float | None,
    gap_payload: dict[str, Any] | None,
) -> list[str]:
    lines = [
        "A raw price comparison is unfair if your property is genuinely better "
        "or differently equipped than the peers. The hedonic model adjusts peer "
        "prices to your measurable feature and quality profile, so you compare "
        "like with like.",
        "",
        f"- Raw comparable median: {_fmt_money(raw_peer_median)}",
        f"- Feature-matched comparable median (peers adjusted to your quality): {_fmt_money(adjusted_peer_median)}",
        f"- Your median asking price: {_fmt_money(subject_median)}",
    ]

    if feature_premium is not None and residual_premium is not None:
        lines.extend(
            [
                "",
                "Splitting your gap over the raw comparable median:",
                "",
                f"- Feature adjustment versus raw peers: {_fmt_money(feature_premium)}",
                f"- Unexplained premium (pricing power or over-pricing risk): {_fmt_money(residual_premium)}",
            ]
        )

    if gap_payload is not None:
        lines.extend(
            [
                "",
                "Worked example for one matched offer:",
                "",
                f"- Your price: {_fmt_money(gap_payload.get('client_price_per_night'))}",
                f"- Competitor price: {_fmt_money(gap_payload.get('competitor_price_per_night'))}",
                f"- Feature-explained part of the gap: {_fmt_money(gap_payload.get('feature_explained_gap'))}",
                f"- Residual part of the gap: {_fmt_money(gap_payload.get('residual_gap'))}",
            ]
        )
    return lines


def _recommendation_lines(*, name: str, position_class: str) -> list[str]:
    return {
        "insufficient": [
            "There were not enough matched comparable prices to make a confident "
            "recommendation. Widen the date windows or peer radius before acting."
        ],
        "unjustified_premium": [
            f"{name} is charging a clear premium that the measurable features do not "
            "justify. Defend it with the strengths guests actually rate, and watch "
            "conversion: if availability lingers, the unexplained premium is the first "
            "lever to test.",
        ],
        "mixed_premium": [
            f"{name} carries a modest unexplained premium after measurable features are "
            "accounted for. The position looks broadly defensible, but revisit the top end "
            "if occupancy softens.",
        ],
        "underpriced": [
            f"{name} appears to be leaving money on the table: feature-matched rivals "
            "list above your price. Test a measured increase toward the feature-matched "
            "comparable median, monitoring conversion as you go.",
        ],
        "fair": [
            f"{name} is positioned fairly against like-for-like rivals. Hold the current "
            "level and revisit when the next scrape refreshes the comparable set.",
        ],
    }[position_class]


def render_positioning_narrative(payload: dict[str, Any]) -> str:
    """Render a single client-facing positioning narrative from a report payload.

    ``payload`` is the dict returned by ``run_hedonic.build_report_payload`` and
    is treated as untrusted: every figure is missing-safe.
    """

    benchmark = payload.get("benchmark", {}) or {}
    peer_dist = benchmark.get("peer_price_distribution", {}) or {}
    subject_dist = benchmark.get("subject_price_distribution", {}) or {}
    adjusted_dist = payload.get("adjusted_peer_price_distribution", {}) or {}

    name = _client_name(payload)
    percentile = _num(benchmark.get("subject_percentile_vs_peers"))
    gap_pct_raw = _num(benchmark.get("price_gap_to_peer_median_pct"))
    gap_pct = None if gap_pct_raw is None else gap_pct_raw * 100

    raw_peer_median = _num(peer_dist.get("median"))
    adjusted_peer_median = _num(adjusted_dist.get("median"))
    subject_median = _num(subject_dist.get("median"))

    feature_premium = None
    residual_premium = None
    residual_pct = None
    if raw_peer_median is not None and adjusted_peer_median is not None:
        feature_premium = adjusted_peer_median - raw_peer_median
    if subject_median is not None and adjusted_peer_median is not None:
        residual_premium = subject_median - adjusted_peer_median
        if adjusted_peer_median:
            residual_pct = residual_premium / adjusted_peer_median
    position_class = _position_class(residual_pct)

    metrics = payload.get("cv_metrics", {}) or {}

    lines: list[str] = [
        f"# Competitive Pricing Position: {name}",
        "",
        "A plain-language read of where this property sits against its comparable "
        "local market, and how much of any price gap is explained by measurable "
        "features versus left unexplained.",
        "",
        "## Bottom line",
        "",
        *_bottom_line(
            name=name,
            percentile=percentile,
            gap_pct=gap_pct,
            position_class=position_class,
        ),
        "",
        "## Who you are compared against",
        "",
        *_peer_set_lines(payload),
        "",
        "## Your price position today",
        "",
        *_price_position_lines(payload),
        "",
        "## Is the premium justified?",
        "",
        *_premium_lines(
            raw_peer_median=raw_peer_median,
            adjusted_peer_median=adjusted_peer_median,
            subject_median=subject_median,
            feature_premium=feature_premium,
            residual_premium=residual_premium,
            gap_payload=payload.get("gap_explanation"),
        ),
        "",
        "## Recommendation",
        "",
        *_recommendation_lines(name=name, position_class=position_class),
        "",
        "## How to read these numbers",
        "",
        "- Prices are EUR per night for a 2-guest Booking.com search. They are "
        "listed asking prices for available offers, not transacted prices or demand.",
        "- Large-party villa economics are not captured here, because every villa "
        "price was scraped at 2-guest occupancy.",
        "- The feature adjustment comes from a gradient-boosted hedonic model "
        f"(grouped cross-validated log R-squared about {_fmt_pct((_num(metrics.get('r2_log_mean')) or 0) * 100)}, "
        f"typical error about {_fmt_money(metrics.get('mae_eur_mean'))} per night). Treat it as a "
        "directional adjustment, not an exact valuation.",
        f"- Comparable source table: `{payload.get('source_table', 'n/a')}`",
        f"- Hedonic training table: `{payload.get('training_source_table', payload.get('source_table', 'n/a'))}`",
        "",
    ]
    return "\n".join(lines)
