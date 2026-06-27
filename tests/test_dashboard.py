import json
import unittest

from scripts.run_dashboard import DashboardService
from tests.test_hedonic import sample_hedonic_frame
from tourism_pricing_analytics.analysis.dashboard import (
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
            "peers",
            "ols_premia",
            "model",
        ]:
            self.assertIn(key, payload)
        self.assertEqual(payload["client"]["property_name"], "Subject Stay")
        self.assertLessEqual(len(payload["ols_premia"]), 10)
        self.assertIn("subject_percentile_vs_peers", payload["kpis"])
        # Must round-trip through JSON without custom encoders.
        self.assertEqual(json.loads(json.dumps(payload))["client"]["property_url"], "subject")


class RenderIndexTests(unittest.TestCase):
    def test_index_html_has_mount_points(self) -> None:
        html = render_index_html()
        self.assertIn("Competitive Pricing Dashboard", html)
        self.assertIn('id="subject"', html)
        self.assertIn("api/benchmark", html)
        self.assertIn("api/meta", html)


class DashboardServiceTests(unittest.TestCase):
    def test_service_fits_once_and_answers_benchmarks(self) -> None:
        frame = sample_hedonic_frame()
        service = DashboardService(frame, source_table="synthetic.parquet", min_token_frequency=1)

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
        service = DashboardService(frame, source_table="synthetic.parquet", min_token_frequency=1)
        payload = service.benchmark(
            subject_url=None,
            lead_time_days=None,
            stay_length_days=None,
            season=None,
            max_peers=3,
            max_distance_km=25.0,
        )
        self.assertEqual(payload["client"]["property_url"], service.catalog[0]["property_url"])


if __name__ == "__main__":
    unittest.main()
