"""Write a markdown comparable competitor benchmark report."""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tourism_pricing_analytics.analysis.competitors import (
    ComparableBenchmarkConfig,
    peer_price_benchmark,
)
from tourism_pricing_analytics.analysis.loader import DEFAULT_MODELLING_TABLE, load_modelling_table
from tourism_pricing_analytics.analysis.segment import segment_self_catering

DEFAULT_REPORT_PATH = REPO_ROOT / "data" / "modelling" / "competitor_report.md"


def _default_subject_url(frame, limit: int = 1) -> str:
    segment = segment_self_catering(frame)
    grouped = (
        segment.groupby(["property_url", "property_name"], dropna=False)
        .size()
        .reset_index(name="price_row_count")
    )
    selected = grouped.sort_values(
        ["price_row_count", "property_name", "property_url"],
        ascending=[False, True, True],
    ).head(limit)
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


def _parse_windows(args: argparse.Namespace) -> list[dict[str, Any]] | None:
    if args.window:
        return [json.loads(value) for value in args.window]
    if not any([args.checkin, args.lead_time_days, args.stay_length_days, args.season]):
        return None

    checkins = args.checkin or [None]
    lead_times = args.lead_time_days or [None]
    stay_lengths = args.stay_length_days or [None]
    seasons = args.season or [None]
    windows = []
    for checkin, lead_time, stay_length, season in itertools.product(
        checkins,
        lead_times,
        stay_lengths,
        seasons,
    ):
        window: dict[str, Any] = {}
        if checkin is not None:
            window["checkin"] = checkin
        if lead_time is not None:
            window["lead_time_days"] = lead_time
        if stay_length is not None:
            window["stay_length_days"] = stay_length
        if season is not None:
            window["crete_season"] = season
        windows.append(window)
    return windows


def _fmt_money(value: object) -> str:
    if value is None:
        return "n/a"
    return f"EUR {float(value):,.2f}"


def _fmt_pct(value: object) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.1f}%"


def _render_windows(windows: list[dict[str, Any]]) -> list[str]:
    lines = ["| Window | Criteria |", "| ---: | --- |"]
    for index, window in enumerate(windows, start=1):
        criteria = ", ".join(f"{key}={value}" for key, value in sorted(window.items()))
        lines.append(f"| {index} | {criteria} |")
    return lines


def _render_peer_table(peers: list[dict[str, Any]], limit: int = 10) -> list[str]:
    lines = [
        "| Rank | Property | Type | Distance km | Similarity | Median EUR/night |",
        "| ---: | --- | --- | ---: | ---: | ---: |",
    ]
    for index, peer in enumerate(peers[:limit], start=1):
        lines.append(
            "| {rank} | {name} | {ptype} | {distance} | {similarity} | {price} |".format(
                rank=index,
                name=peer.get("property_name") or peer.get("property_url"),
                ptype=peer.get("property_type") or "n/a",
                distance="n/a"
                if peer.get("distance_km") is None
                else f"{float(peer['distance_km']):.2f}",
                similarity="n/a"
                if peer.get("overall_similarity") is None
                else f"{float(peer['overall_similarity']):.3f}",
                price="n/a"
                if peer.get("median_price_per_night") is None
                else f"{float(peer['median_price_per_night']):.2f}",
            )
        )
    return lines


def render_markdown_report(payload: dict[str, Any]) -> str:
    benchmark = payload["benchmark"]
    client = benchmark["client"]
    peer_distribution = benchmark["peer_price_distribution"]
    subject_distribution = benchmark["subject_price_distribution"]
    flags = benchmark["peer_set"]["flags"]

    lines = [
        "# Comparable Competitor Benchmark",
        "",
        f"Source table: `{payload['source_table']}`",
        "",
        "Price unit: EUR/night for a 2-guest Booking.com search. These are listed asking prices for available offers, not transacted demand.",
        "",
        "## Client",
        "",
        f"- Property: {client.get('property_name') or 'n/a'}",
        f"- URL: {client.get('property_url') or 'hand-entered spec'}",
        f"- Type: {client.get('property_type') or 'n/a'}",
        f"- Reference price: {_fmt_money(client.get('reference_price_per_night'))}",
        "",
        "## Benchmark Windows",
        "",
        *_render_windows(benchmark["benchmark_windows"]),
        "",
        "## Peer Price Position",
        "",
        f"- Peer rows: {benchmark['coverage']['peer_price_rows']}",
        f"- Peer properties with prices: {benchmark['peer_set']['peer_properties_with_prices']}",
        f"- Peer range: {_fmt_money(peer_distribution['p25'])} to {_fmt_money(peer_distribution['p75'])} IQR; median {_fmt_money(peer_distribution['median'])}",
        f"- Subject median in these windows: {_fmt_money(subject_distribution['median'])}",
        f"- Subject percentile vs peers: {_fmt_pct(benchmark['subject_percentile_vs_peers'])}",
        f"- Gap to peer median: {_fmt_money(benchmark['price_gap_to_peer_median'])} ({_fmt_pct(benchmark['price_gap_to_peer_median_pct'] * 100 if benchmark['price_gap_to_peer_median_pct'] is not None else None)})",
        f"- Flags: {', '.join(flags) if flags else 'none'}",
        "",
        "## Top Comparable Properties",
        "",
        *_render_peer_table(benchmark["peers"]),
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=DEFAULT_MODELLING_TABLE)
    parser.add_argument("--subject-url", default=None)
    parser.add_argument("--spec-json", default=None, help="Hand-entered client spec as JSON.")
    parser.add_argument("--spec-path", type=Path, default=None, help="Path to hand-entered client spec JSON.")
    parser.add_argument("--window", action="append", help="Benchmark window as JSON. Repeatable.")
    parser.add_argument("--checkin", action="append", default=None)
    parser.add_argument("--lead-time-days", action="append", type=int, default=None)
    parser.add_argument("--stay-length-days", action="append", type=int, default=None)
    parser.add_argument("--season", action="append", default=None)
    parser.add_argument("--max-peers", type=int, default=ComparableBenchmarkConfig.max_peers)
    parser.add_argument("--min-peers", type=int, default=ComparableBenchmarkConfig.min_peers)
    parser.add_argument("--max-distance-km", type=float, default=ComparableBenchmarkConfig.max_distance_km)
    parser.add_argument(
        "--min-peer-price-rows",
        type=int,
        default=ComparableBenchmarkConfig.min_peer_price_rows,
    )
    parser.add_argument("--geo-weight", type=float, default=ComparableBenchmarkConfig.distance_weight)
    parser.add_argument("--similarity-weight", type=float, default=ComparableBenchmarkConfig.feature_weight)
    parser.add_argument("--include-guest-house", action="store_true")
    parser.add_argument("--out", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args()

    frame = load_modelling_table(args.path)
    spec = _load_spec(args)
    if spec is not None and args.subject_url:
        raise SystemExit("Use either --subject-url or a spec, not both.")
    client: str | dict[str, Any] = spec or args.subject_url or _default_subject_url(frame)
    windows = _parse_windows(args)

    benchmark = peer_price_benchmark(
        client,
        frame,
        windows,
        k=args.max_peers,
        w_geo=args.geo_weight,
        w_sim=args.similarity_weight,
        max_distance_km=args.max_distance_km,
        min_peers=args.min_peers,
        min_peer_price_rows=args.min_peer_price_rows,
        include_guest_house=args.include_guest_house,
    )
    payload = {
        "source_table": str(args.path),
        "benchmark": benchmark,
    }
    report = render_markdown_report(payload)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report + "\n", encoding="utf-8")
    print(report)

    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
