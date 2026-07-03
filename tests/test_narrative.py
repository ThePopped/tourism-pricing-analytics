import unittest

from tourism_pricing_analytics.analysis.narrative import render_positioning_narrative


def _payload(**overrides):
    """A representative report payload, shaped like build_report_payload output."""

    payload = {
        "source_table": "data/modelling/modelling_table.parquet",
        "training_rows": 1583,
        "training_properties": 154,
        "cv_metrics": {
            "folds": 5,
            "r2_log_mean": 0.327,
            "mae_log_mean": 0.285,
            "mae_eur_mean": 52.12,
            "model_family": "hist_gradient_boosting",
            "min_token_frequency": 15,
            "conformal_coverage": 0.8,
            "conformal_residual_count": 1583,
        },
        "conformal_coverage": 0.8,
        "adjusted_peer_price_band": {
            "price": 237.70,
            "lower": 170.00,
            "upper": 330.00,
            "coverage": 0.8,
        },
        "ols_r2": 0.625,
        "ols_condition_number": 9.4e16,
        "ols_coefficients": [],
        "benchmark": {
            "client": {
                "property_name": "Anna's House",
                "property_url": "https://example.com/anna",
                "property_type": "Aparthotel",
            },
            "peer_price_distribution": {"count": 75, "p25": 122.0, "median": 159.0, "p75": 224.0},
            "subject_price_distribution": {"count": 6, "p25": 280.0, "median": 306.73, "p75": 320.0},
            "subject_percentile_vs_peers": 92.0,
            "price_gap_to_peer_median": 147.73,
            "price_gap_to_peer_median_pct": 0.929,
            "coverage": {"peer_price_rows": 75},
            "peer_set": {"peer_properties_with_prices": 9, "flags": []},
            "peers": [
                {
                    "property_name": "River Side",
                    "property_type": "Aparthotel",
                    "distance_km": 0.63,
                    "overall_similarity": 0.82,
                    "median_price_per_night": 93.22,
                },
                {
                    "property_name": "Central",
                    "property_type": "Aparthotel",
                    "distance_km": 0.67,
                    "overall_similarity": 0.776,
                    "median_price_per_night": 110.75,
                },
            ],
        },
        "adjusted_peer_price_distribution": {"count": 75, "p25": 213.5, "median": 237.70, "p75": 259.13},
        "adjusted_peer_price_rows": [],
        "gap_explanation": {
            "client_price_per_night": 141.71,
            "competitor_price_per_night": 82.5,
            "observed_gap": 59.21,
            "feature_explained_gap": 86.05,
            "residual_gap": -26.84,
        },
    }
    payload.update(overrides)
    return payload


class PositioningNarrativeTests(unittest.TestCase):
    def test_contains_all_client_sections(self) -> None:
        report = render_positioning_narrative(_payload())
        for section in [
            "# Competitive Pricing Position: Anna's House",
            "## Bottom line",
            "## Who you are compared against",
            "## Your price position today",
            "## Is the premium justified?",
            "## Recommendation",
            "## How to read these numbers",
        ]:
            with self.subTest(section=section):
                self.assertIn(section, report)

    def test_premium_subject_reads_as_above_market(self) -> None:
        report = render_positioning_narrative(_payload())
        self.assertIn("priced above its comparable local rivals", report)
        # Residual premium (306.73 - 237.70) dominates the feature premium here.
        self.assertIn("pricing power", report)

    def test_conformal_band_is_reported(self) -> None:
        report = render_positioning_narrative(_payload())
        # The feature-matched median carries its split-conformal ± range, and the
        # reader is told what that range means.
        self.assertIn("range for that feature-matched figure", report)
        self.assertIn("EUR 170.00", report)
        self.assertIn("EUR 330.00", report)
        self.assertIn("split-conformal", report)

    def test_missing_band_is_safe(self) -> None:
        report = render_positioning_narrative(_payload(adjusted_peer_price_band=None))
        self.assertNotIn("range for that feature-matched figure", report)

    def test_distribution_level_decomposition_is_reported(self) -> None:
        report = render_positioning_narrative(_payload())
        # Feature premium = 237.70 - 159.00 = 78.70; residual = 306.73 - 237.70 = 69.03.
        self.assertIn("EUR 78.70", report)
        self.assertIn("EUR 69.03", report)

    def test_mixed_premium_does_not_claim_gap_is_mostly_earned(self) -> None:
        benchmark = _payload()["benchmark"]
        benchmark["client"]["property_name"] = "Stavros Villas & Apartments"
        benchmark["peer_price_distribution"] = {
            "count": 109,
            "p25": 95.25,
            "median": 119.0,
            "p75": 162.25,
        }
        benchmark["subject_price_distribution"] = {"count": 12, "median": 133.48}
        benchmark["subject_percentile_vs_peers"] = 57.8
        benchmark["price_gap_to_peer_median"] = 14.48
        benchmark["price_gap_to_peer_median_pct"] = 0.122
        report = render_positioning_narrative(
            _payload(
                benchmark=benchmark,
                adjusted_peer_price_distribution={
                    "count": 109,
                    "p25": 114.14,
                    "median": 120.35,
                    "p75": 129.56,
                },
            )
        )

        self.assertIn("EUR 1.35", report)
        self.assertIn("EUR 13.13", report)
        self.assertIn("modest unexplained premium", report)
        self.assertNotIn("mostly earned", report)

    def test_underpriced_subject_recommends_increase(self) -> None:
        benchmark = _payload()["benchmark"]
        benchmark["subject_price_distribution"] = {"count": 6, "median": 150.0}
        benchmark["subject_percentile_vs_peers"] = 20.0
        benchmark["price_gap_to_peer_median"] = -9.0
        benchmark["price_gap_to_peer_median_pct"] = -0.056
        report = render_positioning_narrative(_payload(benchmark=benchmark))
        self.assertIn("priced below its comparable local rivals", report)
        self.assertIn("leaving money on the table", report)

    def test_missing_figures_are_safe(self) -> None:
        sparse = {
            "source_table": "x.parquet",
            "cv_metrics": {},
            "benchmark": {
                "client": {},
                "peer_price_distribution": {},
                "subject_price_distribution": {},
                "subject_percentile_vs_peers": None,
                "price_gap_to_peer_median": None,
                "price_gap_to_peer_median_pct": None,
                "coverage": {},
                "peer_set": {"flags": ["low_peer_price_rows"]},
                "peers": [],
            },
            "adjusted_peer_price_distribution": {},
            "gap_explanation": None,
        }
        report = render_positioning_narrative(sparse)
        self.assertIn("your property", report)
        self.assertIn("n/a", report)
        self.assertIn("not enough matched", report)
        self.assertIn("low_peer_price_rows", report)


if __name__ == "__main__":
    unittest.main()
