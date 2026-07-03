"""Export a client-facing competitive pricing workbook."""

from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_competitors import _default_subject_url, _load_spec
from scripts.run_hedonic import build_report_payload
from tourism_pricing_analytics.analysis.competitors import ComparableBenchmarkConfig
from tourism_pricing_analytics.analysis.hedonic import SELECTED_MIN_TOKEN_FREQUENCY
from tourism_pricing_analytics.analysis.loader import (
    DEFAULT_HEDONIC_TRAINING_TABLE,
    DEFAULT_MODELLING_TABLE,
    load_modelling_table,
)

DEFAULT_WORKBOOK_PATH = REPO_ROOT / "data" / "modelling" / "competitive_pricing_workbook.xlsx"


def _parse_windows(args: argparse.Namespace) -> list[dict[str, Any]] | None:
    if args.window:
        return [json.loads(value) for value in args.window]
    if not any([args.checkin, args.lead_time_days, args.stay_length_days, args.season]):
        return None

    windows = []
    for checkin, lead_time, stay_length, season in itertools.product(
        args.checkin or [None],
        args.lead_time_days or [None],
        args.stay_length_days or [None],
        args.season or [None],
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


def _coerce_cell_value(value: object) -> str | int | float | bool | None:
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, float) and pd.isna(value):
        return None
    if value is pd.NA:
        return None
    if isinstance(value, (list, tuple, set, frozenset)):
        return ", ".join(str(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    if hasattr(value, "item"):
        return _coerce_cell_value(value.item())
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _column_letter(index: int) -> str:
    letters = ""
    number = index + 1
    while number:
        number, remainder = divmod(number - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _cell_xml(row_index: int, column_index: int, value: object, style: int | None = None) -> str:
    reference = f"{_column_letter(column_index)}{row_index + 1}"
    style_attr = f' s="{style}"' if style is not None else ""
    value = _coerce_cell_value(value)
    if value is None:
        return f'<c r="{reference}"{style_attr}/>'
    if isinstance(value, bool):
        return f'<c r="{reference}" t="b"{style_attr}><v>{1 if value else 0}</v></c>'
    if isinstance(value, (int, float)):
        return f'<c r="{reference}"{style_attr}><v>{value}</v></c>'
    return f'<c r="{reference}" t="inlineStr"{style_attr}><is><t>{escape(value)}</t></is></c>'


def _sheet_xml(
    rows: list[list[object]],
    *,
    header_rows: set[int] | None = None,
    section_rows: set[int] | None = None,
    numeric_columns: set[int] | None = None,
    currency_columns: set[int] | None = None,
    percent_columns: set[int] | None = None,
    cell_styles: dict[tuple[int, int], int] | None = None,
    freeze_row: int | None = None,
    widths: dict[int, int] | None = None,
) -> str:
    header_rows = header_rows or set()
    section_rows = section_rows or set()
    numeric_columns = numeric_columns or set()
    currency_columns = currency_columns or set()
    percent_columns = percent_columns or set()
    cell_styles = cell_styles or {}
    widths = widths or {}
    max_cols = max((len(row) for row in rows), default=1)
    dimension = f"A1:{_column_letter(max_cols - 1)}{max(len(rows), 1)}"

    cols = "".join(
        f'<col min="{index + 1}" max="{index + 1}" width="{width}" customWidth="1"/>'
        for index, width in sorted(widths.items())
    )
    cols_xml = f"<cols>{cols}</cols>" if cols else ""
    if freeze_row is not None and freeze_row > 0:
        top_left = f"A{freeze_row + 1}"
        sheet_view = (
            '<sheetViews><sheetView workbookViewId="0">'
            f'<pane ySplit="{freeze_row}" topLeftCell="{top_left}" '
            'activePane="bottomLeft" state="frozen"/>'
            "</sheetView></sheetViews>"
        )
    else:
        sheet_view = '<sheetViews><sheetView workbookViewId="0"/></sheetViews>'

    row_xml = []
    for row_index, row in enumerate(rows):
        style = None
        if row_index == 0:
            style = 1
        elif row_index in section_rows:
            style = 2
        elif row_index in header_rows:
            style = 3
        cells = []
        for column_index in range(max_cols):
            value = row[column_index] if column_index < len(row) else None
            cell_style = cell_styles.get((row_index, column_index), style)
            if cell_style is None:
                if column_index in currency_columns:
                    cell_style = 4
                elif column_index in percent_columns:
                    cell_style = 5
                elif column_index in numeric_columns:
                    cell_style = 6
            cells.append(_cell_xml(row_index, column_index, value, cell_style))
        row_xml.append(f'<row r="{row_index + 1}">{"".join(cells)}</row>')

    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<dimension ref=\"{dimension}\"/>"
        f"{sheet_view}"
        f"{cols_xml}"
        f"<sheetData>{''.join(row_xml)}</sheetData>"
        "</worksheet>"
    )


def _sanitize_sheet_name(name: str, used: set[str]) -> str:
    clean = re.sub(r"[\[\]:*?/\\]", " ", name).strip() or "Sheet"
    clean = clean[:31]
    candidate = clean
    counter = 2
    while candidate in used:
        suffix = f" {counter}"
        candidate = clean[: 31 - len(suffix)] + suffix
        counter += 1
    used.add(candidate)
    return candidate


def _workbook_xml(sheet_names: list[str]) -> str:
    sheets = "".join(
        f'<sheet name="{escape(name)}" sheetId="{index}" r:id="rId{index}"/>'
        for index, name in enumerate(sheet_names, start=1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{sheets}</sheets>"
        "</workbook>"
    )


def _workbook_rels_xml(sheet_count: int) -> str:
    rels = [
        (
            f'<Relationship Id="rId{index}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{index}.xml"/>'
        )
        for index in range(1, sheet_count + 1)
    ]
    rels.append(
        f'<Relationship Id="rId{sheet_count + 1}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{''.join(rels)}"
        "</Relationships>"
    )


def _root_rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        '<Relationship Id="rId2" '
        'Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" '
        'Target="docProps/core.xml"/>'
        '<Relationship Id="rId3" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" '
        'Target="docProps/app.xml"/>'
        "</Relationships>"
    )


def _content_types_xml(sheet_count: int) -> str:
    overrides = [
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
        '<Override PartName="/docProps/core.xml" '
        'ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>',
        '<Override PartName="/docProps/app.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>',
    ]
    overrides.extend(
        '<Override PartName="/xl/worksheets/sheet{index}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'.format(
            index=index
        )
        for index in range(1, sheet_count + 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f"{''.join(overrides)}"
        "</Types>"
    )


def _styles_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <numFmts count="3">
    <numFmt numFmtId="164" formatCode="&quot;EUR&quot; #,##0.00"/>
    <numFmt numFmtId="165" formatCode="0.0%"/>
    <numFmt numFmtId="166" formatCode="#,##0.000"/>
  </numFmts>
  <fonts count="4">
    <font><sz val="10"/><name val="Aptos"/></font>
    <font><b/><sz val="14"/><color rgb="FF111827"/><name val="Aptos Display"/></font>
    <font><b/><sz val="10"/><color rgb="FFFFFFFF"/><name val="Aptos"/></font>
    <font><b/><sz val="10"/><color rgb="FF111827"/><name val="Aptos"/></font>
  </fonts>
  <fills count="4">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF1F4E79"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFD9EAF7"/></patternFill></fill>
  </fills>
  <borders count="2">
    <border><left/><right/><top/><bottom/><diagonal/></border>
    <border><left/><right/><top/><bottom style="thin"><color rgb="FFB7C9D6"/></bottom><diagonal/></border>
  </borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="7">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>
    <xf numFmtId="0" fontId="1" fillId="0" borderId="0" applyFont="1"/>
    <xf numFmtId="0" fontId="2" fillId="2" borderId="0" applyFont="1" applyFill="1"/>
    <xf numFmtId="0" fontId="3" fillId="3" borderId="1" applyFont="1" applyFill="1" applyBorder="1"/>
    <xf numFmtId="164" fontId="0" fillId="0" borderId="0" applyNumberFormat="1"/>
    <xf numFmtId="165" fontId="0" fillId="0" borderId="0" applyNumberFormat="1"/>
    <xf numFmtId="166" fontId="0" fillId="0" borderId="0" applyNumberFormat="1"/>
  </cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""


def _core_xml() -> str:
    created = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:dcmitype="http://purl.org/dc/dcmitype/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        "<dc:title>Competitive Pricing Workbook</dc:title>"
        "<dc:creator>tourism_pricing_analytics</dc:creator>"
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{created}</dcterms:created>'
        f'<dcterms:modified xsi:type="dcterms:W3CDTF">{created}</dcterms:modified>'
        "</cp:coreProperties>"
    )


def _app_xml(sheet_names: list[str]) -> str:
    titles = "".join(f'<vt:lpstr>{escape(name)}</vt:lpstr>' for name in sheet_names)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        "<Application>tourism_pricing_analytics</Application>"
        "<HeadingPairs><vt:vector size=\"2\" baseType=\"variant\">"
        "<vt:variant><vt:lpstr>Worksheets</vt:lpstr></vt:variant>"
        f"<vt:variant><vt:i4>{len(sheet_names)}</vt:i4></vt:variant>"
        "</vt:vector></HeadingPairs>"
        f'<TitlesOfParts><vt:vector size="{len(sheet_names)}" baseType="lpstr">{titles}</vt:vector></TitlesOfParts>'
        "</Properties>"
    )


def _summary_rows(payload: dict[str, Any]) -> list[list[object]]:
    benchmark = payload["benchmark"]
    client = benchmark["client"]
    peer_distribution = benchmark["peer_price_distribution"]
    subject_distribution = benchmark["subject_price_distribution"]
    adjusted = payload["adjusted_peer_price_distribution"]
    band = payload.get("adjusted_peer_price_band") or {}
    metrics = payload["cv_metrics"]
    gap = payload["gap_explanation"] or {}
    flags = benchmark["peer_set"]["flags"]
    gap_pct = benchmark["price_gap_to_peer_median_pct"]
    coverage = payload.get("conformal_coverage", metrics.get("conformal_coverage"))
    coverage_label = "n/a" if coverage is None else f"{float(coverage) * 100:.0f}% conformal band"

    return [
        ["Competitive Pricing Workbook"],
        ["Comparable source table", payload["source_table"]],
        ["Hedonic training table", payload.get("training_source_table", payload["source_table"])],
        ["Price unit", "EUR/night for a 2-guest Booking.com search"],
        [],
        ["Client"],
        ["Property", client.get("property_name")],
        ["URL", client.get("property_url") or "hand-entered spec"],
        ["Type", client.get("property_type")],
        ["Reference price", client.get("reference_price_per_night")],
        [],
        ["Peer Price Position"],
        ["Peer rows", benchmark["coverage"]["peer_price_rows"]],
        ["Peer properties with prices", benchmark["peer_set"]["peer_properties_with_prices"]],
        ["Peer p25", peer_distribution["p25"]],
        ["Peer median", peer_distribution["median"]],
        ["Peer p75", peer_distribution["p75"]],
        ["Subject median", subject_distribution["median"]],
        [
            "Subject percentile vs peers",
            None
            if benchmark["subject_percentile_vs_peers"] is None
            else float(benchmark["subject_percentile_vs_peers"]) / 100.0,
        ],
        ["Gap to peer median", benchmark["price_gap_to_peer_median"]],
        ["Gap to peer median pct", None if gap_pct is None else float(gap_pct)],
        ["Flags", ", ".join(flags) if flags else "none"],
        [],
        ["Feature-Adjusted Benchmark"],
        ["Adjusted peer rows", adjusted["count"]],
        ["Adjusted peer p25", adjusted["p25"]],
        ["Adjusted peer median", adjusted["median"]],
        ["Adjusted peer p75", adjusted["p75"]],
        [],
        ["Hedonic Training"],
        ["Training rows", payload["training_rows"]],
        ["Training properties", payload["training_properties"]],
        ["Grouped CV folds", metrics["folds"]],
        ["GBM mean log R2", metrics["r2_log_mean"]],
        ["GBM mean log MAE", metrics["mae_log_mean"]],
        ["GBM mean EUR/night MAE", metrics["mae_eur_mean"]],
        ["OLS R2", payload["ols_r2"]],
        ["OLS condition number", payload["ols_condition_number"]],
        [],
        ["Price Gap Decomposition"],
        ["Client observed price", gap.get("client_price_per_night")],
        ["Competitor observed price", gap.get("competitor_price_per_night")],
        ["Observed gap", gap.get("observed_gap")],
        ["Feature-explained gap", gap.get("feature_explained_gap")],
        ["Residual gap", gap.get("residual_gap")],
        [],
        ["Prediction Band"],
        ["Basis", coverage_label],
        ["Adjusted peer median", band.get("price")],
        ["Lower bound", band.get("lower")],
        ["Upper bound", band.get("upper")],
        [],
        ["Selected Model"],
        ["Family", metrics.get("model_family")],
        ["Min token frequency", metrics.get("min_token_frequency")],
        ["Out-of-fold residuals", metrics.get("conformal_residual_count")],
    ]


def _table_rows(title: str, rows: list[dict[str, Any]], columns: list[str]) -> list[list[object]]:
    output: list[list[object]] = [[title], [], columns]
    output.extend([[record.get(column) for column in columns] for record in rows])
    return output


def _peer_rows(payload: dict[str, Any]) -> list[list[object]]:
    columns = [
        "rank",
        "property_name",
        "property_type",
        "distance_km",
        "feature_similarity",
        "overall_similarity",
        "median_price_per_night",
        "price_row_count",
        "room_count",
        "property_url",
    ]
    rows = []
    for rank, peer in enumerate(payload["benchmark"]["peers"], start=1):
        record = dict(peer)
        record["rank"] = rank
        rows.append(record)
    return _table_rows("Peer Set", rows, columns)


def _gap_rows(payload: dict[str, Any]) -> list[list[object]]:
    gap = payload["gap_explanation"]
    rows: list[list[object]] = [["Gap Decomposition"]]
    if gap is None:
        return rows + [[], ["No matched subject/peer row was available for a gap example."]]

    rows.extend(
        [
            [],
            ["Metric", "Value"],
            ["Client observed price", gap["client_price_per_night"]],
            ["Competitor observed price", gap["competitor_price_per_night"]],
            ["Observed gap", gap["observed_gap"]],
            ["Feature-explained gap", gap["feature_explained_gap"]],
            ["Residual gap", gap["residual_gap"]],
            ["Client predicted price", gap["client_predicted_price_per_night"]],
            ["Competitor predicted price", gap["competitor_predicted_price_per_night"]],
            [],
            ["Top Feature Contributions", "Log-point contribution"],
        ]
    )
    rows.extend(
        [item["feature"], item["contribution_log_points"]]
        for item in gap.get("top_feature_contributions_log_points", [])
    )
    return rows


def workbook_sheets(payload: dict[str, Any]) -> list[tuple[str, str]]:
    peer_row_columns = [
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
        "current_price_value",
    ]
    adjusted_columns = [
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
    windows = _table_rows(
        "Benchmark Windows",
        payload["benchmark"]["benchmark_windows"],
        sorted({key for window in payload["benchmark"]["benchmark_windows"] for key in window}),
    )
    summary = _sheet_xml(
        _summary_rows(payload),
        section_rows={5, 11, 23, 29, 39, 46, 52},
        cell_styles={
            (9, 1): 4,
            (14, 1): 4,
            (15, 1): 4,
            (16, 1): 4,
            (17, 1): 4,
            (18, 1): 5,
            (19, 1): 4,
            (20, 1): 5,
            (25, 1): 4,
            (26, 1): 4,
            (27, 1): 4,
            (35, 1): 4,
            (40, 1): 4,
            (41, 1): 4,
            (42, 1): 4,
            (43, 1): 4,
            (44, 1): 4,
            (48, 1): 4,
            (49, 1): 4,
            (50, 1): 4,
        },
        numeric_columns={1},
        widths={0: 30, 1: 46},
    )
    peer_set = _sheet_xml(
        _peer_rows(payload),
        header_rows={2},
        numeric_columns={0, 3, 4, 5, 7, 8},
        currency_columns={6},
        freeze_row=3,
        widths={0: 8, 1: 32, 2: 16, 3: 13, 4: 16, 5: 16, 6: 18, 9: 60},
    )
    raw_peer_rows = _sheet_xml(
        _table_rows("Raw Peer Rows", payload["benchmark"]["peer_price_rows"], peer_row_columns),
        header_rows={2},
        numeric_columns={7, 8},
        currency_columns={9, 10},
        freeze_row=3,
        widths={0: 32, 1: 60, 2: 18, 3: 32, 4: 28, 5: 13, 6: 13, 9: 18, 10: 18},
    )
    adjusted_rows = _sheet_xml(
        _table_rows("Adjusted Peer Rows", payload["adjusted_peer_price_rows"], adjusted_columns),
        header_rows={2},
        numeric_columns={7, 8, 12},
        currency_columns={9, 10, 11, 13},
        freeze_row=3,
        widths={0: 32, 1: 60, 2: 18, 3: 32, 4: 28, 5: 13, 6: 13, 9: 18, 10: 22, 11: 28, 13: 24},
    )
    gap = _sheet_xml(
        _gap_rows(payload),
        header_rows={2, 11},
        currency_columns={1},
        numeric_columns={1},
        widths={0: 42, 1: 24},
    )
    window_sheet = _sheet_xml(
        windows,
        header_rows={2},
        numeric_columns=set(range(0, 8)),
        freeze_row=3,
        widths={0: 18, 1: 18, 2: 18, 3: 18, 4: 18},
    )
    return [
        ("Summary", summary),
        ("Benchmark Windows", window_sheet),
        ("Peer Set", peer_set),
        ("Raw Peer Rows", raw_peer_rows),
        ("Adjusted Peer Rows", adjusted_rows),
        ("Gap Decomposition", gap),
    ]


def write_pricing_workbook(payload: dict[str, Any], out: Path) -> None:
    sheets = workbook_sheets(payload)
    used_names: set[str] = set()
    sheet_names = [_sanitize_sheet_name(name, used_names) for name, _ in sheets]
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _content_types_xml(len(sheets)))
        archive.writestr("_rels/.rels", _root_rels_xml())
        archive.writestr("docProps/core.xml", _core_xml())
        archive.writestr("docProps/app.xml", _app_xml(sheet_names))
        archive.writestr("xl/workbook.xml", _workbook_xml(sheet_names))
        archive.writestr("xl/_rels/workbook.xml.rels", _workbook_rels_xml(len(sheets)))
        archive.writestr("xl/styles.xml", _styles_xml())
        for index, (_, xml) in enumerate(sheets, start=1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", xml)


def build_workbook_payload(args: argparse.Namespace) -> dict[str, Any]:
    frame = load_modelling_table(args.path)
    training_frame = load_modelling_table(args.training_path)
    spec = _load_spec(args)
    if spec is not None and args.subject_url:
        raise SystemExit("Use either --subject-url or a spec, not both.")
    client: str | dict[str, Any] = spec or args.subject_url or _default_subject_url(frame)
    return build_report_payload(
        frame,
        source_table=str(args.path),
        client=client,
        windows=_parse_windows(args),
        max_peers=args.max_peers,
        max_distance_km=args.max_distance_km,
        min_token_frequency=args.min_token_frequency,
        training_frame=training_frame,
        training_source_table=str(args.training_path),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=DEFAULT_MODELLING_TABLE)
    parser.add_argument(
        "--training-path",
        type=Path,
        default=DEFAULT_HEDONIC_TRAINING_TABLE,
        help="Broader table for hedonic model training.",
    )
    parser.add_argument("--subject-url", default=None)
    parser.add_argument("--spec-json", default=None, help="Hand-entered client spec as JSON.")
    parser.add_argument("--spec-path", type=Path, default=None, help="Path to hand-entered client spec JSON.")
    parser.add_argument("--window", action="append", help="Benchmark window as JSON. Repeatable.")
    parser.add_argument("--checkin", action="append", default=None)
    parser.add_argument("--lead-time-days", action="append", type=int, default=None)
    parser.add_argument("--stay-length-days", action="append", type=int, default=None)
    parser.add_argument("--season", action="append", default=None)
    parser.add_argument("--max-peers", type=int, default=ComparableBenchmarkConfig.max_peers)
    parser.add_argument("--max-distance-km", type=float, default=ComparableBenchmarkConfig.max_distance_km)
    parser.add_argument("--min-token-frequency", type=int, default=SELECTED_MIN_TOKEN_FREQUENCY)
    parser.add_argument("--out", type=Path, default=DEFAULT_WORKBOOK_PATH)
    args = parser.parse_args()

    payload = build_workbook_payload(args)
    write_pricing_workbook(payload, args.out)
    print(f"Wrote {args.out}")
    print(f"Client: {payload['benchmark']['client'].get('property_name') or 'n/a'}")
    print(f"Raw peer median: {_fmt_money(payload['benchmark']['peer_price_distribution']['median'])}")
    print(f"Adjusted peer median: {_fmt_money(payload['adjusted_peer_price_distribution']['median'])}")
    band = payload.get("adjusted_peer_price_band")
    if band:
        print(f"Adjusted peer band: {_fmt_money(band['lower'])} to {_fmt_money(band['upper'])}")
    print(
        "Subject percentile vs peers: "
        f"{_fmt_pct(payload['benchmark']['subject_percentile_vs_peers'])}"
    )


if __name__ == "__main__":
    main()
