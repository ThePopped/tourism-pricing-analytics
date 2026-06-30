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
    "subject_catalog",
    "window_options",
    "shape_dashboard_payload",
    "render_index_html",
]


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
        "flags": list(benchmark["peer_set"]["flags"]),
        "peers": _peer_table(benchmark["peers"], peer_limit),
        "ols_premia": premia,
        "model": {
            "training_rows": _json_safe(report_payload["training_rows"]),
            "training_properties": _json_safe(report_payload["training_properties"]),
            "gbm_r2_log_mean": _json_safe(metrics["r2_log_mean"]),
            "gbm_mae_eur_mean": _json_safe(metrics["mae_eur_mean"]),
            "ols_r2": _json_safe(report_payload["ols_r2"]),
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
    <button id="run">Run benchmark</button>
  </div>
  <div id="status">Loading catalog&hellip;</div>
  <div id="report" hidden>
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
</main>
<script>
const $ = (id) => document.getElementById(id);
const money = (v) => v == null ? "n/a" : "EUR " + Number(v).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
const pct = (v) => v == null ? "n/a" : Number(v).toFixed(1) + "%";
const num = (v, d=2) => v == null ? "n/a" : Number(v).toFixed(d);

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
  fillSelect($("lead"), meta.windows.lead_time_days, {anyLabel: "Any"});
  fillSelect($("stay"), meta.windows.stay_length_days, {anyLabel: "Any"});
  fillSelect($("season"), meta.windows.crete_season, {anyLabel: "Any"});
  $("status").textContent = "";
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
  $("adjusted").innerHTML = tableHtml([
    {key:"k",label:"Metric",fmt:v=>v},{key:"v",label:"Value",num:true,fmt:v=>v}],
    [{k:"Raw peer median",v:money(pd.median)},{k:"Adjusted peer median",v:money(a.median)},
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
  $("model").innerHTML = tableHtml([{key:"k",label:"Metric",fmt:v=>v},{key:"v",label:"Value",fmt:v=>v}],
    [{k:"Comparable source table",v:d.source_table},{k:"Hedonic training table",v:d.training_source_table},
     {k:"Training rows",v:m.training_rows},{k:"Training properties",v:m.training_properties},
     {k:"GBM mean log R2",v:num(m.gbm_r2_log_mean,3)},{k:"GBM mean EUR/night MAE",v:money(m.gbm_mae_eur_mean)},
     {k:"OLS R2",v:num(m.ols_r2,3)},{k:"Price unit",v:d.price_unit}]);

  $("report").hidden = false;
}

async function runBenchmark() {
  const p = new URLSearchParams();
  if ($("subject").value) p.set("subject_url", $("subject").value);
  if ($("lead").value) p.set("lead_time_days", $("lead").value);
  if ($("stay").value) p.set("stay_length_days", $("stay").value);
  if ($("season").value) p.set("season", $("season").value);
  if ($("peers").value) p.set("max_peers", $("peers").value);
  $("run").disabled = true; $("status").className = ""; $("status").textContent = "Running benchmark…";
  try {
    const res = await fetch("api/benchmark?" + p.toString());
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || ("HTTP " + res.status));
    render(data); $("status").textContent = "";
  } catch (e) {
    $("status").className = "err"; $("status").textContent = "Error: " + e.message; $("report").hidden = true;
  } finally { $("run").disabled = false; }
}

$("run").addEventListener("click", runBenchmark);
loadMeta().then(runBenchmark).catch(e => { $("status").className="err"; $("status").textContent = "Failed to load catalog: " + e.message; });
</script>
</body>
</html>
"""


def render_index_html() -> str:
    """Return the static single-page dashboard shell."""

    return _INDEX_HTML
