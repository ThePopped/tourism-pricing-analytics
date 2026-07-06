"""Pure helpers for the local competitive-pricing dashboard.

This module holds the deterministic, dependency-light pieces the dashboard
needs: the self-catering subject catalog, the benchmark-window option lists, a
compact front-end payload shaper, and the static single-page HTML shell. The
heavy data assembly (hedonic fit, peer benchmark) stays in
``scripts/run_dashboard.py`` so this module never imports from ``scripts`` and
adds no runtime dependencies beyond pandas.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from tourism_pricing_analytics.analysis.segment import segment_self_catering

__all__ = [
    "DEFAULT_SUBJECT_URL",
    "default_subject_url",
    "subject_catalog",
    "window_options",
    "shape_dashboard_payload",
    "render_index_html",
]

# The client the dashboard is built for. When this property is present in the
# loaded catalog it is preselected as the benchmark subject; otherwise the
# dashboard falls back to the highest-coverage self-catering property.
DEFAULT_SUBJECT_URL = (
    "https://www.booking.com/hotel/gr/stavros-villas-amp-apartments.en-gb.html"
)


def default_subject_url(catalog: list[dict[str, Any]]) -> str | None:
    """Return the preselected subject URL for a catalog.

    Prefers :data:`DEFAULT_SUBJECT_URL` (the client property) when it is in the
    catalog, and otherwise falls back to the first (highest-coverage) entry so
    the dashboard always has a sensible default.
    """

    if any(record.get("property_url") == DEFAULT_SUBJECT_URL for record in catalog):
        return DEFAULT_SUBJECT_URL
    return catalog[0]["property_url"] if catalog else None


def _json_safe(value: object) -> Any:
    """Coerce a single scalar into something ``json.dumps`` accepts."""

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
        return _json_safe(value.item())
    return value


def subject_catalog(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Return the in-data self-catering properties selectable as a subject.

    Ordered by price-row coverage (descending) then name so the default
    selection is stable and matches the report runners' default subject.
    """

    segment = segment_self_catering(frame)
    if segment.empty:
        return []

    grouped = segment.groupby(["property_url", "property_name"], dropna=False)
    records: list[dict[str, Any]] = []
    for (property_url, property_name), rows in grouped:
        prices = pd.to_numeric(rows["price_per_night"], errors="coerce").dropna()
        types = rows["property_type"].dropna().astype(str)
        records.append(
            {
                "property_url": _json_safe(property_url),
                "property_name": _json_safe(property_name),
                "property_type": types.iloc[0] if not types.empty else None,
                "price_row_count": int(rows.shape[0]),
                "median_price_per_night": float(prices.median()) if not prices.empty else None,
            }
        )

    records.sort(
        key=lambda record: (
            -record["price_row_count"],
            str(record["property_name"] or ""),
            str(record["property_url"] or ""),
        )
    )
    return records


def window_options(frame: pd.DataFrame) -> dict[str, list[Any]]:
    """Return the distinct benchmark-window values present in the segment."""

    segment = segment_self_catering(frame)

    def _sorted_ints(column: str) -> list[int]:
        if column not in segment:
            return []
        values = pd.to_numeric(segment[column], errors="coerce").dropna()
        return sorted({int(value) for value in values})

    def _sorted_strings(column: str) -> list[str]:
        if column not in segment:
            return []
        values = segment[column].dropna().astype(str)
        return sorted({value for value in values if value})

    def _sorted_dates(column: str) -> list[str]:
        if column not in segment:
            return []
        values = pd.to_datetime(segment[column], errors="coerce").dropna()
        return sorted({value.date().isoformat() for value in values})

    return {
        "lead_time_days": _sorted_ints("lead_time_days"),
        "stay_length_days": _sorted_ints("stay_length_days"),
        "crete_season": _sorted_strings("crete_season"),
        "checkin": _sorted_dates("checkin"),
    }


def _distribution_block(distribution: dict[str, Any] | None) -> dict[str, Any]:
    distribution = distribution or {}
    return {
        "count": _json_safe(distribution.get("count")),
        "p25": _json_safe(distribution.get("p25")),
        "median": _json_safe(distribution.get("median")),
        "p75": _json_safe(distribution.get("p75")),
    }


def _peer_table(peers: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    table = []
    for rank, peer in enumerate(peers[:limit], start=1):
        table.append(
            {
                "rank": rank,
                "property_name": _json_safe(peer.get("property_name"))
                or _json_safe(peer.get("property_url")),
                "property_type": _json_safe(peer.get("property_type")),
                "distance_km": _json_safe(peer.get("distance_km")),
                "overall_similarity": _json_safe(peer.get("overall_similarity")),
                "median_price_per_night": _json_safe(peer.get("median_price_per_night")),
                "price_row_count": _json_safe(peer.get("price_row_count")),
            }
        )
    return table


def shape_dashboard_payload(
    report_payload: dict[str, Any],
    *,
    peer_limit: int = 15,
    premia_limit: int = 10,
) -> dict[str, Any]:
    """Reduce a full hedonic report payload to a compact front-end payload.

    The input is the dict returned by ``scripts.run_hedonic.build_report_payload``.
    The output is JSON-serializable and carries only what the single-page UI
    renders: client identity, headline KPIs, peer/adjusted distributions, the
    ranked peer table, the gap decomposition, and the top OLS market premia.
    """

    benchmark = report_payload["benchmark"]
    client = benchmark["client"]
    peer_distribution = benchmark["peer_price_distribution"]
    subject_distribution = benchmark["subject_price_distribution"]
    adjusted = report_payload["adjusted_peer_price_distribution"]
    band = report_payload.get("adjusted_peer_price_band")
    metrics = report_payload["cv_metrics"]
    gap = report_payload.get("gap_explanation")
    gap_pct = benchmark["price_gap_to_peer_median_pct"]

    premia = [
        {
            "feature": _json_safe(row["feature"]),
            "coefficient": _json_safe(row["coefficient"]),
            "p_value": _json_safe(row["p_value"]),
        }
        for row in report_payload["ols_coefficients"][:premia_limit]
    ]

    gap_block = None
    if gap is not None:
        gap_block = {
            "client_price_per_night": _json_safe(gap["client_price_per_night"]),
            "competitor_price_per_night": _json_safe(gap["competitor_price_per_night"]),
            "observed_gap": _json_safe(gap["observed_gap"]),
            "feature_explained_gap": _json_safe(gap["feature_explained_gap"]),
            "residual_gap": _json_safe(gap["residual_gap"]),
        }

    return {
        "source_table": _json_safe(report_payload["source_table"]),
        "training_source_table": _json_safe(
            report_payload.get("training_source_table", report_payload["source_table"])
        ),
        "price_unit": "EUR/night for a 2-guest Booking.com search",
        "client": {
            "property_name": _json_safe(client.get("property_name")),
            "property_url": _json_safe(client.get("property_url")),
            "property_type": _json_safe(client.get("property_type")),
            "reference_price_per_night": _json_safe(client.get("reference_price_per_night")),
        },
        "benchmark_windows": [
            {key: _json_safe(value) for key, value in window.items()}
            for window in benchmark["benchmark_windows"]
        ],
        "kpis": {
            "peer_price_rows": _json_safe(benchmark["coverage"]["peer_price_rows"]),
            "peer_properties_with_prices": _json_safe(
                benchmark["peer_set"]["peer_properties_with_prices"]
            ),
            "subject_median": _json_safe(subject_distribution["median"]),
            "subject_percentile_vs_peers": _json_safe(benchmark["subject_percentile_vs_peers"]),
            "price_gap_to_peer_median": _json_safe(benchmark["price_gap_to_peer_median"]),
            "price_gap_to_peer_median_pct": None if gap_pct is None else float(gap_pct) * 100.0,
        },
        "peer_price_distribution": _distribution_block(peer_distribution),
        "subject_price_distribution": _distribution_block(subject_distribution),
        "adjusted_peer_price_distribution": _distribution_block(adjusted),
        "adjusted_peer_price_band": None
        if not band
        else {
            "price": _json_safe(band.get("price")),
            "lower": _json_safe(band.get("lower")),
            "upper": _json_safe(band.get("upper")),
            "coverage": _json_safe(band.get("coverage")),
        },
        "flags": list(benchmark["peer_set"]["flags"]),
        "peers": _peer_table(benchmark["peers"], peer_limit),
        "ols_premia": premia,
        "model": {
            "training_rows": _json_safe(report_payload["training_rows"]),
            "training_properties": _json_safe(report_payload["training_properties"]),
            "gbm_r2_log_mean": _json_safe(metrics["r2_log_mean"]),
            "gbm_mae_eur_mean": _json_safe(metrics["mae_eur_mean"]),
            "ols_r2": _json_safe(report_payload["ols_r2"]),
            "model_family": _json_safe(metrics.get("model_family")),
            "min_token_frequency": _json_safe(metrics.get("min_token_frequency")),
            "conformal_coverage": _json_safe(metrics.get("conformal_coverage")),
            "conformal_residual_count": _json_safe(metrics.get("conformal_residual_count")),
        },
        "gap_explanation": gap_block,
    }


# The single-page shell is a static string so it is trivially testable and has
# no template-engine dependency. Data is fetched at runtime from the JSON API.
_INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Competitive Pricing Dashboard</title>
<style>
  :root { --ink:#111827; --muted:#6b7280; --line:#e5e7eb; --accent:#1f4e79;
          --accent-soft:#d9eaf7; --good:#15803d; --bad:#b91c1c; --bg:#f9fafb; }
  * { box-sizing: border-box; }
  body { margin:0; font:14px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
         color:var(--ink); background:var(--bg); }
  header { background:var(--accent); color:#fff; padding:18px 24px; }
  header h1 { margin:0; font-size:19px; }
  header p { margin:4px 0 0; font-size:12px; opacity:.85; }
  main { max-width:1100px; margin:0 auto; padding:20px 24px 60px; }
  .controls { display:flex; flex-wrap:wrap; gap:14px; align-items:flex-end;
              background:#fff; border:1px solid var(--line); border-radius:8px;
              padding:16px; margin-bottom:20px; }
  .field { display:flex; flex-direction:column; gap:4px; }
  .field label { font-size:11px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); }
  .field select, .field input { padding:7px 9px; border:1px solid var(--line);
              border-radius:6px; font-size:13px; min-width:120px; background:#fff; }
  .field.subject select { min-width:280px; }
  button { background:var(--accent); color:#fff; border:0; border-radius:6px;
           padding:9px 18px; font-size:13px; cursor:pointer; }
  button:disabled { opacity:.55; cursor:default; }
  .kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:12px; margin-bottom:20px; }
  .kpi { background:#fff; border:1px solid var(--line); border-radius:8px; padding:14px 16px; }
  .kpi .label { font-size:11px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); }
  .kpi .value { font-size:22px; font-weight:600; margin-top:4px; }
  .kpi .sub { font-size:12px; color:var(--muted); margin-top:2px; }
  section.card { background:#fff; border:1px solid var(--line); border-radius:8px;
                 padding:16px 18px; margin-bottom:18px; }
  section.card h2 { margin:0 0 12px; font-size:15px; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th, td { text-align:left; padding:7px 8px; border-bottom:1px solid var(--line); }
  th { font-size:11px; text-transform:uppercase; letter-spacing:.03em; color:var(--muted); }
  td.num, th.num { text-align:right; font-variant-numeric:tabular-nums; }
  .flags { display:flex; flex-wrap:wrap; gap:8px; }
  .flag { background:#fef3c7; color:#92400e; border-radius:999px; padding:3px 10px; font-size:12px; }
  .pos { color:var(--bad); } .neg { color:var(--good); }
  .muted { color:var(--muted); }
  .scale { position:relative; height:54px; margin:6px 4px 2px; }
  .scale .track { position:absolute; top:26px; left:0; right:0; height:4px; background:var(--line); border-radius:2px; }
  .scale .iqr { position:absolute; top:22px; height:12px; background:var(--accent-soft); border-radius:3px; }
  .scale .tick { position:absolute; top:14px; width:2px; height:28px; background:var(--accent); }
  .scale .marker { position:absolute; top:6px; width:2px; height:42px; background:var(--bad); }
  .scale .lab { position:absolute; top:-2px; font-size:10px; color:var(--muted); transform:translateX(-50%); white-space:nowrap; }
  .scale .lab.mk { color:var(--bad); top:36px; }
  #status { color:var(--muted); font-size:13px; margin-bottom:14px; min-height:18px; }
  .err { color:var(--bad); }
  .tabs { display:flex; gap:6px; border-bottom:1px solid var(--line); margin-bottom:18px; }
  .tab { background:transparent; color:var(--muted); border:0; border-bottom:2px solid transparent;
         border-radius:0; padding:9px 16px; font-size:13px; cursor:pointer; }
  .tab.active { color:var(--accent); border-bottom-color:var(--accent); font-weight:600; }
  .notice { background:#fff; border:1px solid var(--line); border-radius:8px; padding:16px 18px;
            color:var(--muted); margin-bottom:18px; }
  .notice.warn { background:#fef3c7; border-color:#fde68a; color:#92400e; }
  .subject-box { background:var(--accent-soft); border:1px solid #bcd7ee; border-left:4px solid var(--accent);
                 border-radius:8px; padding:12px 16px; margin-bottom:18px; }
  .subject-box .lab { font-size:11px; text-transform:uppercase; letter-spacing:.04em; color:var(--accent); }
  .subject-box .name { font-size:17px; font-weight:600; margin-top:2px; }
  .subject-box .meta { font-size:12px; color:var(--muted); margin-top:2px; word-break:break-all; }
  .chart { width:100%; overflow-x:auto; }
  .chart svg { display:block; }
  .chart .legend { display:flex; flex-wrap:wrap; gap:14px; margin-top:8px; font-size:12px; color:var(--muted); }
  .chart .legend .key { display:inline-flex; align-items:center; gap:6px; }
  .chart .legend .swatch { width:18px; height:0; border-top-width:3px; border-top-style:solid; display:inline-block; }
  .badge { display:inline-block; border-radius:999px; padding:4px 14px; font-size:14px; font-weight:600; }
  .badge.act-hold { background:#e0e7ff; color:#3730a3; }
  .badge.act-increase { background:#dcfce7; color:#166534; }
  .badge.act-discount { background:#fee2e2; color:#991b1b; }
  .badge.act-watch { background:#fef3c7; color:#92400e; }
  .badge.act-none { background:#f3f4f6; color:#374151; }
  .conf { font-size:12px; text-transform:uppercase; letter-spacing:.04em; margin-left:10px; }
  .conf-high { color:var(--good); } .conf-medium { color:#b45309; } .conf-low { color:var(--bad); }
  .codes { display:flex; flex-wrap:wrap; gap:8px; margin-top:10px; }
  .code { background:var(--accent-soft); color:var(--accent); border-radius:999px; padding:3px 10px; font-size:12px; }
  .code.flag { background:#fee2e2; color:#991b1b; }
  .action-rationale { margin:10px 0 0; }
</style>
</head>
<body>
<header>
  <h1>Competitive Pricing Dashboard</h1>
  <p>Listed Booking.com asking prices, EUR/night for a 2-guest search. Positioning, not demand.</p>
</header>
<main>
  <div class="controls">
    <div class="field subject">
      <label for="subject">Subject property</label>
      <select id="subject"></select>
    </div>
    <div class="field"><label for="lead">Lead time (days)</label><select id="lead"></select></div>
    <div class="field"><label for="stay">Stay length (nights)</label><select id="stay"></select></div>
    <div class="field"><label for="season">Season</label><select id="season"></select></div>
    <div class="field"><label for="peers">Max peers</label>
      <input id="peers" type="number" min="1" max="50" value="10"/></div>
    <button id="run">Run</button>
  </div>
  <nav class="tabs">
    <button class="tab active" data-tab="benchmark" id="tab-benchmark">Benchmark</button>
    <button class="tab" data-tab="movements" id="tab-movements">Price Movements</button>
  </nav>
  <div id="status">Loading catalog&hellip;</div>
  <div class="notice warn" id="inventory-notice" hidden></div>
  <div id="report" hidden>
    <div class="subject-box" id="bench-subject"></div>
    <div class="kpis" id="kpis"></div>
    <section class="card"><h2>Peer price position</h2><div class="scale" id="scale"></div>
      <p class="muted" id="scale-note"></p></section>
    <section class="card" id="flags-card" hidden><h2>Coverage flags</h2><div class="flags" id="flags"></div></section>
    <section class="card"><h2>Top comparable properties</h2><div id="peers-table"></div></section>
    <section class="card"><h2>Feature-adjusted benchmark</h2><div id="adjusted"></div>
      <p class="muted">Peer prices re-priced to the subject's feature profile via the grouped GBM hedonic model.</p></section>
    <section class="card" id="gap-card" hidden><h2>Price gap decomposition</h2><div id="gap"></div></section>
    <section class="card"><h2>OLS market premia (directional)</h2><div id="premia"></div>
      <p class="muted">High OLS condition number: read as descriptive premia, not causal estimates.</p></section>
    <section class="card"><h2>Model &amp; source</h2><div id="model"></div></section>
  </div>
  <div id="movements-view" hidden>
    <div class="subject-box" id="mv-subject"></div>
    <div class="notice" id="mv-history"></div>
    <div class="kpis" id="mv-kpis"></div>
    <section class="card" id="mv-action-card"><h2>Recommended action</h2><div id="mv-action"></div></section>
    <section class="card"><h2>Price trend over time</h2><div class="chart" id="mv-chart"></div>
      <p class="muted">Median price per property per snapshot. Bold line = subject; dashed = competitor mean; thin lines = individual competitors.</p></section>
    <section class="card"><h2>Competitor price movements</h2><div id="mv-peers"></div>
      <p class="muted">Property-weighted peer medians: each property's median first, then the peer-market median. Latest comparable snapshot. One row per lead-time and stay-length window.</p></section>
    <section class="card"><h2>Subject vs peer timeline</h2><div id="mv-timeline"></div></section>
    <div class="notice" id="mv-covariates"></div>
  </div>
</main>
<script>
const $ = (id) => document.getElementById(id);
const money = (v) => v == null ? "n/a" : "EUR " + Number(v).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
const pct = (v) => v == null ? "n/a" : Number(v).toFixed(1) + "%";
const num = (v, d=2) => v == null ? "n/a" : Number(v).toFixed(d);
let activeTab = "benchmark";
const loaded = {benchmark: false, movements: false};

function fillSelect(el, values, {anyLabel, mapper} = {}) {
  el.innerHTML = "";
  if (anyLabel) { const o = document.createElement("option"); o.value=""; o.textContent=anyLabel; el.appendChild(o); }
  for (const v of values) {
    const o = document.createElement("option");
    if (mapper) { o.value = mapper.value(v); o.textContent = mapper.label(v); }
    else { o.value = v; o.textContent = v; }
    el.appendChild(o);
  }
}

async function loadMeta() {
  const meta = await fetch("api/meta").then(r => r.json());
  fillSelect($("subject"), meta.subjects, {
    mapper: { value: s => s.property_url,
      label: s => `${s.property_name || s.property_url} (${s.property_type || "?"}, ${s.price_row_count} rows, ${money(s.median_price_per_night)})` }});
  if (meta.default_subject_url) $("subject").value = meta.default_subject_url;
  fillSelect($("lead"), meta.windows.lead_time_days, {anyLabel: "Any"});
  fillSelect($("stay"), meta.windows.stay_length_days, {anyLabel: "Any"});
  fillSelect($("season"), meta.windows.crete_season, {anyLabel: "Any"});
  renderInventoryFreshness(meta.inventory_freshness);
  $("status").textContent = "";
}

function renderInventoryFreshness(freshness) {
  const el = $("inventory-notice");
  if (!freshness || freshness.is_stale !== false) {
    const reason = freshness && freshness.reason ? freshness.reason : "Inventory/property feature freshness is unknown.";
    const threshold = freshness && freshness.stale_threshold_days != null ? freshness.stale_threshold_days : "n/a";
    el.textContent = `Inventory/property features may be stale: ${reason} Threshold: ${threshold} days.`;
    el.hidden = false;
    return;
  }
  el.textContent = "";
  el.hidden = true;
}

function subjectBox(el, name, type, url) {
  el.innerHTML =
    `<div class="lab">Benchmark run for</div>` +
    `<div class="name">${name || "Unknown subject"}</div>` +
    `<div class="meta">${[type, url].filter(Boolean).join(" &middot; ")}</div>`;
}

function scaleBar(peer, subjMedian, adjMedian) {
  const xs = [peer.p25, peer.median, peer.p75, subjMedian, adjMedian].filter(v => v != null);
  if (xs.length < 2) { $("scale").innerHTML = "<span class='muted'>Not enough data to plot.</span>"; $("scale-note").textContent=""; return; }
  let lo = Math.min(...xs), hi = Math.max(...xs); const pad = (hi-lo)*0.12 || 10; lo-=pad; hi+=pad;
  const x = (v) => ((v-lo)/(hi-lo))*100;
  let html = '<div class="track"></div>';
  if (peer.p25 != null && peer.p75 != null) html += `<div class="iqr" style="left:${x(peer.p25)}%;width:${x(peer.p75)-x(peer.p25)}%"></div>`;
  if (peer.median != null) html += `<div class="tick" style="left:${x(peer.median)}%"></div><div class="lab" style="left:${x(peer.median)}%">peer ${money(peer.median)}</div>`;
  if (adjMedian != null) html += `<div class="tick" style="left:${x(adjMedian)}%;background:#6b7280"></div><div class="lab" style="left:${x(adjMedian)}%;top:36px">adj ${money(adjMedian)}</div>`;
  if (subjMedian != null) html += `<div class="marker" style="left:${x(subjMedian)}%"></div><div class="lab mk" style="left:${x(subjMedian)}%">subject ${money(subjMedian)}</div>`;
  $("scale").innerHTML = html;
}

function tableHtml(cols, rows) {
  let h = "<table><thead><tr>" + cols.map(c => `<th class="${c.num?'num':''}">${c.label}</th>`).join("") + "</tr></thead><tbody>";
  for (const r of rows) h += "<tr>" + cols.map(c => `<td class="${c.num?'num':''}">${c.fmt(r[c.key], r)}</td>`).join("") + "</tr>";
  return h + "</tbody></table>";
}

function render(d) {
  subjectBox($("bench-subject"), d.client.property_name, d.client.property_type, d.client.property_url);
  const k = d.kpis, gapCls = (k.price_gap_to_peer_median ?? 0) >= 0 ? "pos" : "neg";
  $("kpis").innerHTML = [
    ["Subject median", money(k.subject_median), "in selected windows"],
    ["Percentile vs peers", pct(k.subject_percentile_vs_peers), `${k.peer_properties_with_prices} priced peers`],
    ["Gap to peer median", `<span class="${gapCls}">${money(k.price_gap_to_peer_median)}</span>`, pct(k.price_gap_to_peer_median_pct)],
    ["Peer price rows", k.peer_price_rows ?? "n/a", "matched offers"],
  ].map(([l,v,s]) => `<div class="kpi"><div class="label">${l}</div><div class="value">${v}</div><div class="sub">${s}</div></div>`).join("");

  scaleBar(d.peer_price_distribution, d.subject_price_distribution.median, d.adjusted_peer_price_distribution.median);
  const pd = d.peer_price_distribution;
  $("scale-note").textContent = `Peer IQR ${money(pd.p25)} to ${money(pd.p75)} across ${pd.count ?? 0} peer offers. Windows: ` +
    (d.benchmark_windows.length ? d.benchmark_windows.map(w => Object.entries(w).map(([a,b])=>`${a}=${b}`).join(", ")).join(" | ") : "all available");

  if (d.flags.length) { $("flags-card").hidden=false; $("flags").innerHTML = d.flags.map(f => `<span class="flag">${f}</span>`).join(""); }
  else $("flags-card").hidden = true;

  $("peers-table").innerHTML = d.peers.length ? tableHtml([
    {key:"rank",label:"#",num:true,fmt:v=>v},
    {key:"property_name",label:"Property",fmt:v=>v||"n/a"},
    {key:"property_type",label:"Type",fmt:v=>v||"n/a"},
    {key:"distance_km",label:"Dist km",num:true,fmt:v=>num(v,2)},
    {key:"overall_similarity",label:"Similarity",num:true,fmt:v=>num(v,3)},
    {key:"median_price_per_night",label:"Median",num:true,fmt:v=>money(v)},
    {key:"price_row_count",label:"Rows",num:true,fmt:v=>v??"n/a"},
  ], d.peers) : "<p class='muted'>No comparable peers were found.</p>";

  const a = d.adjusted_peer_price_distribution;
  const band = d.adjusted_peer_price_band;
  const bandLabel = band && band.coverage != null ? `${Math.round(band.coverage*100)}% conformal band` : "Conformal band";
  $("adjusted").innerHTML = tableHtml([
    {key:"k",label:"Metric",fmt:v=>v},{key:"v",label:"Value",num:true,fmt:v=>v}],
    [{k:"Raw peer median",v:money(pd.median)},{k:"Adjusted peer median",v:money(a.median)},
     {k:bandLabel,v:band ? `${money(band.lower)} to ${money(band.upper)}` : "n/a"},
     {k:"Adjusted IQR",v:`${money(a.p25)} to ${money(a.p75)}`},{k:"Adjusted peer rows",v:a.count ?? "n/a"}]);

  if (d.gap_explanation) {
    $("gap-card").hidden = false; const g = d.gap_explanation;
    $("gap").innerHTML = tableHtml([{key:"k",label:"Component",fmt:v=>v},{key:"v",label:"EUR/night",num:true,fmt:v=>v}],
      [{k:"Client observed price",v:money(g.client_price_per_night)},{k:"Competitor observed price",v:money(g.competitor_price_per_night)},
       {k:"Observed gap",v:money(g.observed_gap)},{k:"Feature-explained gap",v:money(g.feature_explained_gap)},
       {k:"Residual gap",v:money(g.residual_gap)}]);
  } else $("gap-card").hidden = true;

  $("premia").innerHTML = d.ols_premia.length ? tableHtml([
    {key:"feature",label:"Feature",fmt:v=>v},
    {key:"coefficient",label:"Log-coef",num:true,fmt:v=>num(v,4)},
    {key:"p_value",label:"p-value",num:true,fmt:v=>num(v,4)},
  ], d.ols_premia) : "<p class='muted'>No premia available.</p>";

  const m = d.model;
  const covLabel = m.conformal_coverage != null ? `${Math.round(m.conformal_coverage*100)}% (${m.conformal_residual_count ?? "n/a"} OOF residuals)` : "n/a";
  $("model").innerHTML = tableHtml([{key:"k",label:"Metric",fmt:v=>v},{key:"v",label:"Value",fmt:v=>v}],
    [{k:"Comparable source table",v:d.source_table},{k:"Hedonic training table",v:d.training_source_table},
     {k:"Training rows",v:m.training_rows},{k:"Training properties",v:m.training_properties},
     {k:"Selected model",v:m.model_family ?? "n/a"},{k:"Amenity token floor",v:m.min_token_frequency ?? "n/a"},
     {k:"GBM mean log R2",v:num(m.gbm_r2_log_mean,3)},{k:"GBM mean EUR/night MAE",v:money(m.gbm_mae_eur_mean)},
     {k:"Prediction band",v:covLabel},
     {k:"OLS R2",v:num(m.ols_r2,3)},{k:"Price unit",v:d.price_unit}]);

  loaded.benchmark = true;
  $("report").hidden = activeTab !== "benchmark";
}

const fracPct = (v) => v == null ? "n/a" : (Number(v) * 100).toFixed(1) + "%";
const signedFracPct = (v) => v == null ? "n/a" : (Number(v) > 0 ? "+" : "") + (Number(v) * 100).toFixed(1) + "%";
const signedMoney = (v) => v == null ? "n/a" : (Number(v) > 0 ? "+" : "") + money(v);
const ACTION_CLASS = {"Hold":"act-hold","Increase test":"act-increase","Discount test":"act-discount","Watch":"act-watch","No signal":"act-none"};
const AVAIL_LABEL = {available:"Available",newly_available:"Newly available",disappeared:"Disappeared",still_unavailable:"Still unavailable",unknown:"Unknown"};

function chips(codes, cls) {
  if (!codes || !codes.length) return "";
  return `<div class="codes">` + codes.map(c => `<span class="code ${cls||''}">${c}</span>`).join("") + `</div>`;
}

function linePath(pts) {
  // Build one or more polyline segments, breaking across null gaps.
  let segs = [], cur = [];
  for (const p of pts) {
    if (p == null) { if (cur.length) { segs.push(cur); cur = []; } }
    else cur.push(p);
  }
  if (cur.length) segs.push(cur);
  return segs;
}

function lineChart(el, ts) {
  const dates = (ts && ts.snapshot_dates) || [];
  const peers = (ts && ts.peers) || [];
  const subject = ts && ts.subject;
  const mean = (ts && ts.mean_prices) || [];
  if (dates.length === 0) { el.innerHTML = "<p class='muted'>Not enough snapshots to plot a trend yet.</p>"; return; }

  const all = [];
  for (const p of peers) for (const v of p.prices) if (v != null) all.push(v);
  for (const v of mean) if (v != null) all.push(v);
  if (subject) for (const v of subject.prices) if (v != null) all.push(v);
  if (!all.length) { el.innerHTML = "<p class='muted'>No priced snapshots to plot.</p>"; return; }

  const padL = 56, padR = 18, padT = 16, padB = 40;
  const stepX = Math.max(90, 900 / Math.max(1, dates.length - 1 || 1));
  const W = padL + padR + stepX * Math.max(1, dates.length - 1);
  const H = 300;
  let lo = Math.min(...all), hi = Math.max(...all);
  if (lo === hi) { lo -= 5; hi += 5; }
  const padY = (hi - lo) * 0.1; lo -= padY; hi += padY;
  const X = (i) => padL + (dates.length === 1 ? (W - padL - padR) / 2 : i * stepX);
  const Y = (v) => padT + (1 - (v - lo) / (hi - lo)) * (H - padT - padB);

  const seg = (prices, stroke, width, dash) => linePath(prices.map((v, i) => v == null ? null : [X(i), Y(v)]))
    .map(s => s.length === 1
      ? `<circle cx="${s[0][0].toFixed(1)}" cy="${s[0][1].toFixed(1)}" r="${(width + 1).toFixed(1)}" fill="${stroke}"/>`
      : `<polyline fill="none" stroke="${stroke}" stroke-width="${width}"${dash ? ` stroke-dasharray="${dash}"` : ""} points="${s.map(p => p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" ")}"/>`)
    .join("");

  let svg = `<svg viewBox="0 0 ${W.toFixed(0)} ${H}" width="100%" preserveAspectRatio="xMidYMid meet" role="img">`;
  // Y grid + labels (4 ticks).
  for (let t = 0; t <= 4; t++) {
    const v = lo + (hi - lo) * (t / 4), y = Y(v);
    svg += `<line x1="${padL}" y1="${y.toFixed(1)}" x2="${(W - padR).toFixed(1)}" y2="${y.toFixed(1)}" stroke="#eef1f4" stroke-width="1"/>`;
    svg += `<text x="${padL - 6}" y="${(y + 3).toFixed(1)}" text-anchor="end" font-size="10" fill="#6b7280">${Math.round(v)}</text>`;
  }
  // X labels.
  for (let i = 0; i < dates.length; i++) {
    svg += `<text x="${X(i).toFixed(1)}" y="${H - padB + 16}" text-anchor="middle" font-size="10" fill="#6b7280">${dates[i]}</text>`;
  }
  // Competitor lines (faint), then mean (dashed), then subject (bold on top).
  for (const p of peers) svg += seg(p.prices, "#cbd5e1", 1);
  svg += seg(mean, "#6b7280", 2, "5,4");
  if (subject) {
    svg += seg(subject.prices, "#1f4e79", 3);
    for (let i = 0; i < subject.prices.length; i++)
      if (subject.prices[i] != null)
        svg += `<circle cx="${X(i).toFixed(1)}" cy="${Y(subject.prices[i]).toFixed(1)}" r="3.5" fill="#1f4e79"/>`;
  }
  svg += `</svg>`;

  const legend = `<div class="legend">` +
    `<span class="key"><span class="swatch" style="border-top-color:#1f4e79;border-top-width:3px"></span>Subject</span>` +
    `<span class="key"><span class="swatch" style="border-top-color:#6b7280;border-top-style:dashed"></span>Competitor mean</span>` +
    `<span class="key"><span class="swatch" style="border-top-color:#cbd5e1"></span>Individual competitors (${peers.length})</span>` +
    `</div>`;
  el.innerHTML = svg + legend;
}

function renderMovements(d) {
  const q = d.query || {};
  subjectBox($("mv-subject"), q.subject_name, null, q.subject_url);
  const h = d.history || {};
  const histEl = $("mv-history");
  histEl.className = h.is_low_history ? "notice warn" : "notice";
  histEl.textContent = h.message || "";

  const cov = d.covariates || {};
  $("mv-covariates").textContent = cov.status || "";

  const mp = d.market_pressure || {};
  $("mv-kpis").innerHTML = [
    ["Market pressure", mp.market_pressure_label || "n/a", `${num(mp.market_pressure_score, 1)} index points`],
    ["Peer median change", signedFracPct(mp.peer_median_change_pct), signedMoney(mp.peer_median_change_eur) + " vs previous"],
    ["Subject price change", signedFracPct(mp.subject_price_change_pct), signedMoney(mp.subject_price_change_eur) + " vs previous"],
    ["Gap to peer median", signedFracPct(mp.price_gap_to_peer_median_pct), "subject vs peer median"],
  ].map(([l,v,s]) => `<div class="kpi"><div class="label">${l}</div><div class="value">${v}</div><div class="sub">${s}</div></div>`).join("");

  const ap = d.action_payload || {};
  const act = ap.recommended_action || "No signal";
  const conf = ap.confidence || "low";
  $("mv-action").innerHTML =
    `<span class="badge ${ACTION_CLASS[act] || "act-none"}">${act}</span>` +
    `<span class="conf conf-${conf}">${conf} confidence</span>` +
    `<p class="action-rationale">${ap.rationale || ""}</p>` +
    chips(ap.reason_codes, "") + chips(ap.confidence_flags, "flag");

  lineChart($("mv-chart"), d.peer_timeseries);

  $("mv-peers").innerHTML = (d.peer_movements && d.peer_movements.length) ? tableHtml([
    {key:"property_name",label:"Property",fmt:v=>v||"n/a"},
    {key:"lead_time_days",label:"Lead",num:true,fmt:v=>v==null?"n/a":num(v,0)},
    {key:"stay_length_days",label:"Stay",num:true,fmt:v=>v==null?"n/a":num(v,0)},
    {key:"availability_state",label:"Availability",fmt:v=>AVAIL_LABEL[v]||v||"n/a"},
    {key:"current_price_per_night",label:"Now",num:true,fmt:v=>money(v)},
    {key:"previous_price_per_night",label:"Previous",num:true,fmt:v=>money(v)},
    {key:"price_change_eur",label:"Change",num:true,fmt:v=>signedMoney(v)},
    {key:"price_change_pct",label:"Change %",num:true,fmt:v=>signedFracPct(v)},
    {key:"current_price_rank",label:"Rank",num:true,fmt:v=>v==null?"n/a":num(v,0)},
    {key:"price_rank_change",label:"Rank +/-",num:true,fmt:v=>v==null?"n/a":(Number(v)>0?"+":"")+num(v,0)},
  ], d.peer_movements) : "<p class='muted'>No comparable peer movements in the latest snapshot.</p>";

  $("mv-timeline").innerHTML = (d.timeline && d.timeline.length) ? tableHtml([
    {key:"snapshot_date",label:"Snapshot",fmt:v=>v||"n/a"},
    {key:"subject_price_per_night",label:"Subject",num:true,fmt:v=>money(v)},
    {key:"subject_price_change_pct",label:"Subject %",num:true,fmt:v=>signedFracPct(v)},
    {key:"peer_median_price_per_night",label:"Peer median",num:true,fmt:v=>money(v)},
    {key:"peer_median_change_pct",label:"Peer %",num:true,fmt:v=>signedFracPct(v)},
    {key:"peer_available_property_count",label:"Peers avail",num:true,fmt:v=>v==null?"n/a":num(v,0)},
  ], d.timeline) : "<p class='muted'>Not enough snapshots to plot a subject-vs-peer timeline yet.</p>";

  loaded.movements = true;
  $("movements-view").hidden = activeTab !== "movements";
}

function queryParams() {
  const p = new URLSearchParams();
  if ($("subject").value) p.set("subject_url", $("subject").value);
  if ($("lead").value) p.set("lead_time_days", $("lead").value);
  if ($("stay").value) p.set("stay_length_days", $("stay").value);
  if ($("season").value) p.set("season", $("season").value);
  if ($("peers").value) p.set("max_peers", $("peers").value);
  return p;
}

async function runBenchmark() {
  $("run").disabled = true; $("status").className = ""; $("status").textContent = "Running benchmark…";
  try {
    const res = await fetch("api/benchmark?" + queryParams().toString());
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || ("HTTP " + res.status));
    render(data); $("status").textContent = "";
  } catch (e) {
    $("status").className = "err"; $("status").textContent = "Error: " + e.message; $("report").hidden = true;
  } finally { $("run").disabled = false; }
}

async function runMovements() {
  $("run").disabled = true; $("status").className = ""; $("status").textContent = "Loading price movements…";
  try {
    const res = await fetch("api/movements?" + queryParams().toString());
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || ("HTTP " + res.status));
    renderMovements(data); $("status").textContent = "";
  } catch (e) {
    $("status").className = "err"; $("status").textContent = "Error: " + e.message; $("movements-view").hidden = true;
  } finally { $("run").disabled = false; }
}

function runActive() { return activeTab === "movements" ? runMovements() : runBenchmark(); }

function showTab(tab) {
  activeTab = tab;
  for (const b of document.querySelectorAll(".tab")) b.classList.toggle("active", b.dataset.tab === tab);
  $("report").hidden = !(tab === "benchmark" && loaded.benchmark);
  $("movements-view").hidden = !(tab === "movements" && loaded.movements);
  $("status").className = ""; $("status").textContent = "";
  if (!loaded[tab]) runActive();
}

$("run").addEventListener("click", () => { loaded[activeTab] = false; runActive(); });
for (const b of document.querySelectorAll(".tab")) b.addEventListener("click", () => showTab(b.dataset.tab));
loadMeta().then(runBenchmark).catch(e => { $("status").className="err"; $("status").textContent = "Failed to load catalog: " + e.message; });
</script>
</body>
</html>
"""


def render_index_html() -> str:
    """Return the static single-page dashboard shell."""

    return _INDEX_HTML
