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
    render_index_html,
    shape_dashboard_payload,
    subject_catalog,
    window_options,
)
from tourism_pricing_analytics.analysis.hedonic import fit_hedonic_models
from tourism_pricing_analytics.analysis.loader import (
    DEFAULT_HEDONIC_TRAINING_TABLE,
    DEFAULT_MODELLING_TABLE,
    load_modelling_table,
)


class DashboardService:
    """Loads the table, fits the hedonic model once, and answers benchmarks."""

    def __init__(
        self,
        frame: pd.DataFrame,
        *,
        source_table: str,
        training_frame: pd.DataFrame | None = None,
        training_source_table: str | None = None,
        min_token_frequency: int = 25,
    ) -> None:
        self.frame = frame
        self.source_table = source_table
        self.training_source_table = training_source_table or source_table
        self.bundle = fit_hedonic_models(
            training_frame if training_frame is not None else frame,
            min_token_frequency=min_token_frequency,
        )
        self.catalog = subject_catalog(frame)
        self.windows = window_options(frame)
        self._default_subject_url = self.catalog[0]["property_url"] if self.catalog else None

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
    parser.add_argument("--min-token-frequency", type=int, default=25)
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser tab.")
    args = parser.parse_args()

    print(f"Loading modelling table from {args.path} ...")
    frame = load_modelling_table(args.path)
    print(f"Loading hedonic training table from {args.training_path} ...")
    training_frame = load_modelling_table(args.training_path)
    print("Fitting hedonic model (one-time startup cost) ...")
    service = DashboardService(
        frame,
        source_table=str(args.path),
        training_frame=training_frame,
        training_source_table=str(args.training_path),
        min_token_frequency=args.min_token_frequency,
    )
    print(
        f"Ready: {len(service.catalog)} self-catering subjects, "
        f"{service.bundle.training_rows} training rows."
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
