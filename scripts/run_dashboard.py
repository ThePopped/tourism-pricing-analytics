"""Serve a small local competitive-pricing dashboard.

This is a zero-dependency local app: it loads the committed modelling table,
fits the hedonic model once at startup, and serves a single-page UI plus a JSON
benchmark API over Python's stdlib ``http.server``. Each subject/window
selection re-runs only the cheap peer benchmark and re-uses the cached hedonic
bundle, so interaction stays responsive.

Usage::

    .\\.venv\\Scripts\\python.exe scripts\\run_dashboard.py
    .\\.venv\\Scripts\\python.exe scripts\\run_dashboard.py --port 8800 --no-browser
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_hedonic import build_report_payload
from tourism_pricing_analytics.analysis.competitors import ComparableBenchmarkConfig
from tourism_pricing_analytics.analysis.dashboard import (
    default_subject_url,
    render_index_html,
    shape_dashboard_payload,
    subject_catalog,
    window_options,
)
from tourism_pricing_analytics.analysis.hedonic import (
    SELECTED_MIN_TOKEN_FREQUENCY,
    fit_selected_hedonic_models,
)
from tourism_pricing_analytics.analysis.loader import (
    DEFAULT_HEDONIC_TRAINING_TABLE,
    DEFAULT_MODELLING_TABLE,
    load_modelling_table,
)
from tourism_pricing_analytics.analysis.movement import (
    ACTION_NO_SIGNAL,
    CONFIDENCE_LOW,
    DEFAULT_DEMAND_COVARIATES_PATH,
    DEFAULT_OFFER_PRESENCE_PATH,
    DEFAULT_PRICE_OBSERVATIONS_PATH,
    HISTORY_STATUS_LOW_HISTORY,
    build_peer_market_movement_table,
    load_demand_covariates,
    load_offer_presence,
    load_price_observations,
    market_pressure_index,
    movement_history_status,
)


def _json_safe(value: object) -> Any:
    """Coerce pandas/numpy scalars and missing values into strict JSON values."""

    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return None
        if value.time() == pd.Timestamp(value.date()).time():
            return value.date().isoformat()
        return value.isoformat()
    if hasattr(value, "item"):
        return _json_safe(value.item())
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    try:
        missing = pd.isna(value)
    except TypeError:
        missing = False
    if isinstance(missing, bool) and missing:
        return None
    return value


def _movement_record(row: pd.Series) -> dict[str, Any]:
    return {column: _json_safe(row[column]) for column in row.index}


def _latest_movement_rows(movement: pd.DataFrame) -> pd.DataFrame:
    if movement.empty or "snapshot_date" not in movement.columns:
        return movement.iloc[0:0].copy()
    snapshot_dates = pd.to_datetime(movement["snapshot_date"], errors="coerce")
    if snapshot_dates.isna().all():
        return movement.iloc[0:0].copy()
    latest_snapshot = snapshot_dates.max().normalize()
    return movement.loc[snapshot_dates.dt.normalize().eq(latest_snapshot)].copy()


def _movement_timeline(movement: pd.DataFrame) -> list[dict[str, Any]]:
    if movement.empty or "snapshot_date" not in movement.columns:
        return []

    records: list[dict[str, Any]] = []
    for snapshot, rows in movement.groupby("snapshot_date", dropna=False, sort=True):
        subject_rows = rows.loc[rows["is_subject"].astype(bool)] if "is_subject" in rows else rows.iloc[0:0]
        subject = subject_rows.iloc[0] if not subject_rows.empty else None
        peer_rows = rows.loc[~rows["is_subject"].astype(bool)] if "is_subject" in rows else rows
        peer_prices = pd.to_numeric(peer_rows.get("current_price_per_night"), errors="coerce")
        records.append(
            {
                "snapshot_date": _json_safe(snapshot),
                "subject_price_per_night": None
                if subject is None
                else _json_safe(subject.get("current_price_per_night")),
                "subject_price_change_pct": None
                if subject is None
                else _json_safe(subject.get("price_change_pct")),
                "peer_median_price_per_night": None
                if subject is None
                else _json_safe(subject.get("current_peer_median_price_per_night")),
                "peer_median_change_pct": None
                if subject is None
                else _json_safe(subject.get("peer_median_change_pct")),
                "peer_available_property_count": int(peer_prices.notna().sum()),
            }
        )
    return records


def _movement_series(movement: pd.DataFrame) -> dict[str, Any]:
    """Build per-property price series over all snapshots for the trend chart.

    Each property is collapsed to one median ``current_price_per_night`` per
    snapshot (property-weighted across the selected windows), aligned to a
    common sorted list of snapshot dates. Returns the subject series, one series
    per competitor, and a property-weighted mean-of-competitors line.
    """

    empty = {"snapshot_dates": [], "subject": None, "peers": [], "mean_prices": []}
    if movement.empty or "snapshot_date" not in movement.columns:
        return empty

    frame = movement.copy()
    frame["snapshot_date"] = pd.to_datetime(frame["snapshot_date"], errors="coerce")
    frame["current_price_per_night"] = pd.to_numeric(
        frame.get("current_price_per_night"), errors="coerce"
    )
    frame = frame.loc[frame["snapshot_date"].notna()]
    if frame.empty:
        return empty

    snapshot_dates = sorted(frame["snapshot_date"].dt.normalize().unique())
    date_labels = [pd.Timestamp(value).date().isoformat() for value in snapshot_dates]
    date_index = {label: position for position, label in enumerate(date_labels)}

    is_subject = frame.get("is_subject")
    subject_mask = is_subject.astype(bool) if is_subject is not None else pd.Series(False, index=frame.index)

    def _series_for(rows: pd.DataFrame) -> list[float | None]:
        prices: list[float | None] = [None] * len(date_labels)
        rows = rows.copy()
        rows["snapshot_label"] = rows["snapshot_date"].dt.normalize().apply(
            lambda value: pd.Timestamp(value).date().isoformat()
        )
        medians = rows.groupby("snapshot_label")["current_price_per_night"].median()
        for label, value in medians.items():
            position = date_index.get(label)
            if position is not None:
                prices[position] = _json_safe(value)
        return prices

    subject_block: dict[str, Any] | None = None
    subject_rows = frame.loc[subject_mask]
    if not subject_rows.empty:
        subject_block = {
            "property_name": _json_safe(subject_rows["property_name"].dropna().iloc[0])
            if subject_rows["property_name"].notna().any()
            else None,
            "property_url": _json_safe(subject_rows["property_url"].iloc[0]),
            "prices": _series_for(subject_rows),
        }

    peers: list[dict[str, Any]] = []
    peer_rows = frame.loc[~subject_mask]
    for property_url, rows in peer_rows.groupby("property_url", dropna=False):
        names = rows["property_name"].dropna()
        peers.append(
            {
                "property_name": _json_safe(names.iloc[0]) if not names.empty else None,
                "property_url": _json_safe(property_url),
                "prices": _series_for(rows),
            }
        )

    # Property-weighted mean line: average each snapshot across the peer medians.
    mean_prices: list[float | None] = []
    for position in range(len(date_labels)):
        column = [peer["prices"][position] for peer in peers if peer["prices"][position] is not None]
        mean_prices.append(round(sum(column) / len(column), 4) if column else None)

    return {
        "snapshot_dates": date_labels,
        "subject": subject_block,
        "peers": peers,
        "mean_prices": mean_prices,
    }


def _default_low_history_action(message: str) -> dict[str, Any]:
    return {
        "recommended_action": ACTION_NO_SIGNAL,
        "rationale": message,
        "confidence": CONFIDENCE_LOW,
        "confidence_flags": ["low_history"],
        "reason_codes": [],
    }


class DashboardService:
    """Loads the table, fits the hedonic model once, and answers benchmarks."""

    def __init__(
        self,
        frame: pd.DataFrame,
        *,
        source_table: str,
        training_frame: pd.DataFrame | None = None,
        training_source_table: str | None = None,
        min_token_frequency: int = SELECTED_MIN_TOKEN_FREQUENCY,
        observations: pd.DataFrame | None = None,
        presence: pd.DataFrame | None = None,
        covariates: pd.DataFrame | None = None,
    ) -> None:
        self.frame = frame
        self.source_table = source_table
        self.training_source_table = training_source_table or source_table
        self.observations = observations if observations is not None else load_price_observations()
        self.presence = presence if presence is not None else load_offer_presence()
        self.covariates = covariates if covariates is not None else load_demand_covariates()
        self.bundle = fit_selected_hedonic_models(
            training_frame if training_frame is not None else frame,
            min_token_frequency=min_token_frequency,
        )
        self.catalog = subject_catalog(frame)
        self.windows = window_options(frame)
        self._default_subject_url = default_subject_url(self.catalog)
        self._subject_names = {
            record["property_url"]: record["property_name"] for record in self.catalog
        }

    def meta(self) -> dict[str, Any]:
        return {
            "subjects": self.catalog,
            "windows": self.windows,
            "source_table": self.source_table,
            "training_source_table": self.training_source_table,
            "default_subject_url": self._default_subject_url,
        }

    def benchmark(
        self,
        *,
        subject_url: str | None,
        lead_time_days: int | None,
        stay_length_days: int | None,
        season: str | None,
        max_peers: int,
        max_distance_km: float,
    ) -> dict[str, Any]:
        client = subject_url or self._default_subject_url
        if client is None:
            raise ValueError("No self-catering subject property is available.")

        window: dict[str, Any] = {}
        if lead_time_days is not None:
            window["lead_time_days"] = lead_time_days
        if stay_length_days is not None:
            window["stay_length_days"] = stay_length_days
        if season:
            window["crete_season"] = season
        windows = [window] if window else None

        report_payload = build_report_payload(
            self.frame,
            source_table=self.source_table,
            client=client,
            windows=windows,
            max_peers=max_peers,
            max_distance_km=max_distance_km,
            bundle=self.bundle,
            training_source_table=self.training_source_table,
        )
        return shape_dashboard_payload(report_payload)

    def movements(
        self,
        *,
        subject_url: str | None,
        lead_time_days: int | None,
        stay_length_days: int | None,
        season: str | None,
        max_peers: int,
        max_distance_km: float,
    ) -> dict[str, Any]:
        client = subject_url or self._default_subject_url
        if client is None:
            raise ValueError("No self-catering subject property is available.")

        window: dict[str, Any] = {}
        if stay_length_days is not None:
            window["stay_length_days"] = stay_length_days
        if season:
            window["crete_season"] = season
        windows = [window] if window else None

        movement = build_peer_market_movement_table(
            self.observations,
            self.presence,
            self.frame,
            subject_url=client,
            windows=windows,
            max_peers=max_peers,
            max_distance_km=max_distance_km,
            covariates=self.covariates,
        )
        if lead_time_days is not None and not movement.empty:
            movement_attrs = dict(movement.attrs)
            lead_values = pd.to_numeric(movement["lead_time_days"], errors="coerce")
            movement = movement.loc[lead_values.eq(lead_time_days)].copy()
            movement.attrs.update(movement_attrs)
        history = movement.attrs.get(
            "low_history",
            movement_history_status(self.observations, self.presence),
        )
        market_pressure = market_pressure_index(movement)
        latest = _latest_movement_rows(movement)
        latest_subject_rows = (
            latest.loc[latest["is_subject"].astype(bool)]
            if "is_subject" in latest
            else latest.iloc[0:0]
        )
        latest_peer_rows = (
            latest.loc[~latest["is_subject"].astype(bool)]
            if "is_subject" in latest
            else latest
        )

        if latest_subject_rows.empty:
            subject_movement = None
            action_payload = _default_low_history_action(history["message"])
        else:
            subject_row = latest_subject_rows.iloc[0]
            subject_movement = _movement_record(subject_row)
            action_payload = {
                "recommended_action": _json_safe(subject_row.get("recommended_action")),
                "rationale": _json_safe(subject_row.get("rationale")),
                "confidence": _json_safe(subject_row.get("confidence")),
                "confidence_flags": _json_safe(subject_row.get("confidence_flags")),
                "reason_codes": _json_safe(subject_row.get("reason_codes")),
            }

        return {
            "query": {
                "subject_url": client,
                "subject_name": self._subject_names.get(client),
                "lead_time_days": lead_time_days,
                "stay_length_days": stay_length_days,
                "season": season,
                "max_peers": max_peers,
            },
            "history": _json_safe(history),
            "covariates": {
                "status": _json_safe(
                    self.covariates.attrs.get("covariate_status", "Unknown covariate status.")
                ),
                "source_path": _json_safe(self.covariates.attrs.get("source_path")),
                "row_count": int(self.covariates.shape[0]),
            },
            "market_pressure": _json_safe(market_pressure),
            "subject_movement": subject_movement,
            "peer_movements": [_movement_record(row) for _, row in latest_peer_rows.iterrows()],
            "timeline": _movement_timeline(movement),
            "peer_timeseries": _movement_series(movement),
            "reason_codes": action_payload["reason_codes"],
            "action_payload": action_payload,
            "confidence_flags": action_payload["confidence_flags"],
            "peer_property_urls": _json_safe(movement.attrs.get("peer_property_urls", [])),
            "peer_count": _json_safe(movement.attrs.get("peer_count", 0)),
            "status": _json_safe(history.get("status", HISTORY_STATUS_LOW_HISTORY)),
        }


def _int_param(values: dict[str, list[str]], key: str) -> int | None:
    raw = values.get(key, [None])[0]
    if raw is None or raw == "":
        return None
    return int(raw)


def _make_handler(service: DashboardService) -> type[BaseHTTPRequestHandler]:
    index_html = render_index_html().encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        server_version = "PricingDashboard/1.0"

        def log_message(self, *args: Any) -> None:  # noqa: D401 - quiet by default
            return

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self._send(status, body, "application/json; charset=utf-8")

        def do_GET(self) -> None:  # noqa: N802 - http.server API
            parsed = urlparse(self.path)
            route = parsed.path.rstrip("/") or "/"

            if route == "/":
                self._send(200, index_html, "text/html; charset=utf-8")
                return
            if route == "/api/meta":
                self._send_json(200, service.meta())
                return
            if route == "/api/benchmark":
                params = parse_qs(parsed.query)
                try:
                    payload = service.benchmark(
                        subject_url=params.get("subject_url", [None])[0] or None,
                        lead_time_days=_int_param(params, "lead_time_days"),
                        stay_length_days=_int_param(params, "stay_length_days"),
                        season=params.get("season", [None])[0] or None,
                        max_peers=_int_param(params, "max_peers")
                        or ComparableBenchmarkConfig.max_peers,
                        max_distance_km=ComparableBenchmarkConfig.max_distance_km,
                    )
                except Exception as exc:  # surface as a clean JSON error to the UI
                    self._send_json(400, {"error": str(exc)})
                    return
                self._send_json(200, payload)
                return
            if route == "/api/movements":
                params = parse_qs(parsed.query)
                try:
                    payload = service.movements(
                        subject_url=params.get("subject_url", [None])[0] or None,
                        lead_time_days=_int_param(params, "lead_time_days"),
                        stay_length_days=_int_param(params, "stay_length_days"),
                        season=params.get("season", [None])[0] or None,
                        max_peers=_int_param(params, "max_peers")
                        or ComparableBenchmarkConfig.max_peers,
                        max_distance_km=ComparableBenchmarkConfig.max_distance_km,
                    )
                except Exception as exc:  # surface as a clean JSON error to the UI
                    self._send_json(400, {"error": str(exc)})
                    return
                self._send_json(200, payload)
                return

            self._send_json(404, {"error": "not found"})

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=DEFAULT_MODELLING_TABLE)
    parser.add_argument(
        "--training-path",
        type=Path,
        default=DEFAULT_HEDONIC_TRAINING_TABLE,
        help="Broader table for hedonic model training.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--min-token-frequency", type=int, default=SELECTED_MIN_TOKEN_FREQUENCY)
    parser.add_argument("--observations-path", type=Path, default=DEFAULT_PRICE_OBSERVATIONS_PATH)
    parser.add_argument("--presence-path", type=Path, default=DEFAULT_OFFER_PRESENCE_PATH)
    parser.add_argument("--covariates-path", type=Path, default=DEFAULT_DEMAND_COVARIATES_PATH)
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser tab.")
    args = parser.parse_args()

    print(f"Loading modelling table from {args.path} ...")
    frame = load_modelling_table(args.path)
    print(f"Loading hedonic training table from {args.training_path} ...")
    training_frame = load_modelling_table(args.training_path)
    print(f"Loading price observations from {args.observations_path} ...")
    observations = load_price_observations(args.observations_path)
    print(f"Loading offer presence from {args.presence_path} ...")
    presence = load_offer_presence(args.presence_path)
    print(f"Loading demand covariates from {args.covariates_path} ...")
    covariates = load_demand_covariates(args.covariates_path)
    print("Fitting hedonic model (one-time startup cost) ...")
    service = DashboardService(
        frame,
        source_table=str(args.path),
        training_frame=training_frame,
        training_source_table=str(args.training_path),
        min_token_frequency=args.min_token_frequency,
        observations=observations,
        presence=presence,
        covariates=covariates,
    )
    print(
        f"Ready: {len(service.catalog)} self-catering subjects, "
        f"{service.bundle.training_rows} training rows."
    )
    print(
        "Movement history: "
        f"{movement_history_status(observations, presence)['message']} "
        f"{covariates.attrs.get('covariate_status', '')}"
    )

    handler = _make_handler(service)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    url = f"http://{args.host}:{args.port}/"
    print(f"Serving dashboard at {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
