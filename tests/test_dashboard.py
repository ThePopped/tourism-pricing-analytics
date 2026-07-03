import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.request import urlopen

import pandas as pd

from scripts.run_dashboard import DashboardService, _make_handler
from tests.test_price_observations import sample_offer_presence, sample_price_observation
from tests.test_hedonic import sample_hedonic_frame
from tourism_pricing_analytics.analysis.movement import (
    DEMAND_COVARIATE_COLUMNS,
    OFFER_PRESENCE_COLUMNS,
    PRICE_OBSERVATION_COLUMNS,
)
from tourism_pricing_analytics.analysis.dashboard import (
    DEFAULT_SUBJECT_URL,
    default_subject_url,
    render_index_html,
    shape_dashboard_payload,
    subject_catalog,
    window_options,
)
from scripts.run_hedonic import build_report_payload
from tourism_pricing_analytics.analysis.hedonic import fit_hedonic_models


class SubjectCatalogTests(unittest.TestCase):
    def test_catalog_lists_self_catering_only_and_is_ordered(self) -> None:
        catalog = subject_catalog(sample_hedonic_frame())
        urls = [record["property_url"] for record in catalog]

        # The lone Hotel row is excluded from the self-catering segment.
        self.assertNotIn("hotel", urls)
        self.assertEqual(len(catalog), 6)
        # Every record carries the fields the UI selector renders.
        first = catalog[0]
        self.assertIn("property_name", first)
        self.assertIn("property_type", first)
        self.assertEqual(first["price_row_count"], 2)
        self.assertIsNotNone(first["median_price_per_night"])
        # Ties on row count break by name, so the order is stable.
        names = [record["property_name"] for record in catalog]
        self.assertEqual(names, sorted(names))
        json.dumps(catalog)

    def test_window_options_are_sorted_and_json_safe(self) -> None:
        windows = window_options(sample_hedonic_frame())
        self.assertEqual(windows["lead_time_days"], [7])
        self.assertEqual(windows["stay_length_days"], [4])
        self.assertEqual(windows["crete_season"], ["Peak"])
        self.assertEqual(windows["checkin"], ["2026-07-01", "2026-08-01"])
        json.dumps(windows)


class ShapePayloadTests(unittest.TestCase):
    def test_shape_payload_is_compact_and_serializable(self) -> None:
        frame = sample_hedonic_frame()
        report = build_report_payload(
            frame,
            source_table="synthetic.parquet",
            client="subject",
            windows=[{"checkin": "2026-07-01", "lead_time_days": 7, "stay_length_days": 4}],
            max_peers=3,
            min_token_frequency=1,
        )
        payload = shape_dashboard_payload(report)

        for key in [
            "client",
            "kpis",
            "peer_price_distribution",
            "adjusted_peer_price_distribution",
            "adjusted_peer_price_band",
            "peers",
            "ols_premia",
            "model",
        ]:
            self.assertIn(key, payload)
        self.assertEqual(payload["client"]["property_name"], "Subject Stay")
        self.assertLessEqual(len(payload["ols_premia"]), 10)
        self.assertIn("subject_percentile_vs_peers", payload["kpis"])
        # Phase E: the selected-model identity and conformal band ride along.
        self.assertEqual(payload["model"]["model_family"], "hist_gradient_boosting")
        self.assertIn("conformal_coverage", payload["model"])
        band = payload["adjusted_peer_price_band"]
        if band is not None:
            self.assertLessEqual(band["lower"], band["price"])
            self.assertLessEqual(band["price"], band["upper"])
        # Must round-trip through JSON without custom encoders.
        self.assertEqual(json.loads(json.dumps(payload))["client"]["property_url"], "subject")


class RenderIndexTests(unittest.TestCase):
    def test_index_html_has_mount_points(self) -> None:
        html = render_index_html()
        self.assertIn("Competitive Pricing Dashboard", html)
        self.assertIn('id="subject"', html)
        self.assertIn("api/benchmark", html)
        self.assertIn("api/meta", html)

    def test_index_html_has_price_movements_tab_and_mount_points(self) -> None:
        html = render_index_html()
        # The Price Movements tab is wired to the movements API.
        self.assertIn("Price Movements", html)
        self.assertIn('data-tab="movements"', html)
        self.assertIn("api/movements", html)
        # Compact tab mount points: KPIs, action panel, competitor table, timeline.
        for mount in [
            'id="movements-view"',
            'id="mv-kpis"',
            'id="mv-action"',
            'id="mv-peers"',
            'id="mv-timeline"',
            'id="mv-history"',
        ]:
            self.assertIn(mount, html)

    def test_index_html_has_subject_box_and_trend_chart_mounts(self) -> None:
        html = render_index_html()
        # The "benchmark run for" subject boxes on both tabs.
        self.assertIn('id="bench-subject"', html)
        self.assertIn('id="mv-subject"', html)
        self.assertIn("Benchmark run for", html)
        # The competitor trend chart mount and its renderer.
        self.assertIn('id="mv-chart"', html)
        self.assertIn("function lineChart", html)
        # The default subject is preselected in the dropdown.
        self.assertIn("meta.default_subject_url", html)


class DefaultSubjectTests(unittest.TestCase):
    def test_default_prefers_client_url_when_present(self) -> None:
        catalog = [
            {"property_url": "other", "property_name": "Other"},
            {"property_url": DEFAULT_SUBJECT_URL, "property_name": "Stavros"},
        ]
        self.assertEqual(default_subject_url(catalog), DEFAULT_SUBJECT_URL)

    def test_default_falls_back_to_first_entry(self) -> None:
        catalog = [
            {"property_url": "first", "property_name": "First"},
            {"property_url": "second", "property_name": "Second"},
        ]
        self.assertEqual(default_subject_url(catalog), "first")

    def test_default_is_none_for_empty_catalog(self) -> None:
        self.assertIsNone(default_subject_url([]))


class DashboardServiceTests(unittest.TestCase):
    def test_service_fits_once_and_answers_benchmarks(self) -> None:
        frame = sample_hedonic_frame()
        service = _dashboard_service_without_history(frame)

        meta = service.meta()
        self.assertEqual(meta["default_subject_url"], service.catalog[0]["property_url"])
        self.assertTrue(meta["subjects"])

        bundle_id = id(service.bundle)
        payload = service.benchmark(
            subject_url="subject",
            lead_time_days=7,
            stay_length_days=4,
            season="Peak",
            max_peers=3,
            max_distance_km=25.0,
        )
        # The cached bundle is reused across requests, not refit.
        self.assertEqual(id(service.bundle), bundle_id)
        self.assertEqual(payload["client"]["property_url"], "subject")
        json.dumps(payload)

    def test_benchmark_defaults_to_first_catalog_subject(self) -> None:
        frame = sample_hedonic_frame()
        service = _dashboard_service_without_history(frame)
        payload = service.benchmark(
            subject_url=None,
            lead_time_days=None,
            stay_length_days=None,
            season=None,
            max_peers=3,
            max_distance_km=25.0,
        )
        self.assertEqual(payload["client"]["property_url"], service.catalog[0]["property_url"])

    def test_movements_payload_is_json_safe_and_preserves_previous_snapshot(self) -> None:
        service = DashboardService(
            sample_hedonic_frame(),
            source_table="synthetic.parquet",
            min_token_frequency=1,
            observations=_movement_observations_for_dashboard(),
            presence=_movement_presence_for_dashboard(),
            covariates=_covariates_for_dashboard(),
        )

        payload = service.movements(
            subject_url="subject",
            lead_time_days=1,
            stay_length_days=4,
            season="Peak",
            max_peers=2,
            max_distance_km=25.0,
        )

        self.assertEqual(payload["query"]["subject_url"], "subject")
        self.assertFalse(payload["history"]["is_low_history"])
        self.assertEqual(payload["subject_movement"]["property_url"], "subject")
        self.assertEqual(payload["subject_movement"]["previous_snapshot_date"], "2026-06-29")
        self.assertEqual(len(payload["peer_movements"]), 2)
        self.assertIn("market_pressure_label", payload["market_pressure"])
        self.assertIn("recommended_action", payload["action_payload"])
        self.assertIn("reason_codes", payload)
        # Both snapshots share the same constant-maturity window (lead 1), so
        # the timeline spans both the previous (06-29) and current (06-30) points.
        self.assertEqual(len(payload["timeline"]), 2)
        self.assertEqual(
            [entry["snapshot_date"] for entry in payload["timeline"]],
            ["2026-06-29", "2026-06-30"],
        )
        # The trend-chart series carries the subject line, per-competitor lines,
        # and a property-weighted mean aligned to both snapshot dates.
        series = payload["peer_timeseries"]
        self.assertEqual(series["snapshot_dates"], ["2026-06-29", "2026-06-30"])
        self.assertEqual(series["subject"]["property_url"], "subject")
        self.assertEqual(series["subject"]["prices"], [100.0, 105.0])
        self.assertTrue(series["peers"])
        self.assertTrue(all(url != "subject" for url in (p["property_url"] for p in series["peers"])))
        self.assertEqual(len(series["mean_prices"]), 2)
        self.assertTrue(all(value is not None for value in series["mean_prices"]))
        self.assertEqual(payload["query"]["subject_name"], "Subject Stay")
        json.dumps(payload, allow_nan=False)

    def test_movements_endpoint_returns_json_payload(self) -> None:
        service = DashboardService(
            sample_hedonic_frame(),
            source_table="synthetic.parquet",
            min_token_frequency=1,
            observations=_movement_observations_for_dashboard(),
            presence=_movement_presence_for_dashboard(),
            covariates=_covariates_for_dashboard(),
        )
        handler = _make_handler(service)
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = server.server_address
            with urlopen(
                f"http://{host}:{port}/api/movements?"
                "subject_url=subject&lead_time_days=1&stay_length_days=4&season=Peak&max_peers=2",
                timeout=5,
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(payload["subject_movement"]["property_url"], "subject")
        self.assertEqual(payload["status"], "ready")
        json.dumps(payload, allow_nan=False)


def _movement_observation_for_dashboard(
    property_url: str,
    property_name: str,
    snapshot_date: str,
    price_per_night: float,
    latitude: float,
    longitude: float,
) -> dict[str, object]:
    snapshot = pd.Timestamp(snapshot_date)
    # Constant-maturity window: lead stays 1, checkin shifts with the snapshot
    # (checkin = snapshot + 1), mirroring the scraper. The 2026-06-30 snapshot
    # therefore has checkin 2026-07-01, matching the demand covariate below.
    lead_time_days = 1
    checkin = snapshot + pd.Timedelta(days=lead_time_days)
    checkout = checkin + pd.Timedelta(days=4)
    checkin_str = checkin.strftime("%Y-%m-%d")
    checkout_str = checkout.strftime("%Y-%m-%d")
    return sample_price_observation(
        snapshot_date=snapshot_date,
        captured_at=f"{snapshot_date}T09:15:00",
        run_id=f"{snapshot.strftime('%Y%m%d')}_091500_000000",
        property_url=property_url,
        property_name=property_name,
        room_id=f"{property_url}-room",
        room_name="Dashboard Test Room",
        block_id=f"{property_url}-{checkin_str}-{checkout_str}",
        checkin=checkin_str,
        checkout=checkout_str,
        lead_time_days=lead_time_days,
        stay_length_days=4,
        price_per_night=price_per_night,
        current_price_value=price_per_night * 4,
        latitude=latitude,
        longitude=longitude,
    )


def _movement_presence_for_dashboard_row(
    property_url: str,
    property_name: str,
    snapshot_date: str,
    latitude: float,
    longitude: float,
) -> dict[str, object]:
    snapshot = pd.Timestamp(snapshot_date)
    lead_time_days = 1
    checkin = snapshot + pd.Timedelta(days=lead_time_days)
    checkout = checkin + pd.Timedelta(days=4)
    return sample_offer_presence(
        snapshot_date=snapshot_date,
        captured_at=f"{snapshot_date}T09:15:00",
        run_id=f"{snapshot.strftime('%Y%m%d')}_091500_000000",
        property_url=property_url,
        property_name=property_name,
        checkin=checkin.strftime("%Y-%m-%d"),
        checkout=checkout.strftime("%Y-%m-%d"),
        lead_time_days=lead_time_days,
        stay_length_days=4,
        latitude=latitude,
        longitude=longitude,
    )


def _movement_observations_for_dashboard() -> pd.DataFrame:
    specs = [
        ("subject", "Subject Stay", 35.500, 24.000, 100.0, 105.0),
        ("near", "Near Peer", 35.501, 24.001, 120.0, 130.0),
        ("middle", "Middle Peer", 35.520, 24.000, 150.0, 165.0),
    ]
    rows: list[dict[str, object]] = []
    for property_url, property_name, latitude, longitude, old_price, new_price in specs:
        rows.append(
            _movement_observation_for_dashboard(
                property_url,
                property_name,
                "2026-06-29",
                old_price,
                latitude,
                longitude,
            )
        )
        rows.append(
            _movement_observation_for_dashboard(
                property_url,
                property_name,
                "2026-06-30",
                new_price,
                latitude,
                longitude,
            )
        )
    return pd.DataFrame(rows, columns=PRICE_OBSERVATION_COLUMNS)


def _movement_presence_for_dashboard() -> pd.DataFrame:
    specs = [
        ("subject", "Subject Stay", 35.500, 24.000),
        ("near", "Near Peer", 35.501, 24.001),
        ("middle", "Middle Peer", 35.520, 24.000),
    ]
    rows: list[dict[str, object]] = []
    for property_url, property_name, latitude, longitude in specs:
        rows.append(
            _movement_presence_for_dashboard_row(
                property_url,
                property_name,
                "2026-06-29",
                latitude,
                longitude,
            )
        )
        rows.append(
            _movement_presence_for_dashboard_row(
                property_url,
                property_name,
                "2026-06-30",
                latitude,
                longitude,
            )
        )
    return pd.DataFrame(rows, columns=OFFER_PRESENCE_COLUMNS)


def _covariates_for_dashboard() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": "2026-06-30",
                "checkin": "2026-07-01",
                "market": "Chania",
                "google_trends_index": 72,
                "holiday_flag": False,
                "event_flag": True,
                "weather_temp_c": 30.0,
                "weather_rain_mm": 0.0,
                "notes": "Synthetic dashboard test context.",
            }
        ],
        columns=DEMAND_COVARIATE_COLUMNS,
    )


def _dashboard_service_without_history(frame: pd.DataFrame) -> DashboardService:
    return DashboardService(
        frame,
        source_table="synthetic.parquet",
        min_token_frequency=1,
        observations=pd.DataFrame(columns=PRICE_OBSERVATION_COLUMNS),
        presence=pd.DataFrame(columns=OFFER_PRESENCE_COLUMNS),
        covariates=pd.DataFrame(columns=DEMAND_COVARIATE_COLUMNS),
    )


if __name__ == "__main__":
    unittest.main()
