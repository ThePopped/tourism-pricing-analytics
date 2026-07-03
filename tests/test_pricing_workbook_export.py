import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from scripts.export_pricing_workbook import write_pricing_workbook


def _payload() -> dict[str, object]:
    return {
        "source_table": "data/modelling/modelling_table.parquet",
        "training_rows": 12,
        "training_properties": 6,
        "cv_metrics": {
            "folds": 3,
            "r2_log_mean": 0.25,
            "mae_log_mean": 0.15,
            "mae_eur_mean": 40.0,
            "model_family": "hist_gradient_boosting",
            "min_token_frequency": 15,
            "conformal_coverage": 0.8,
            "conformal_residual_count": 12,
        },
        "conformal_coverage": 0.8,
        "adjusted_peer_price_band": {
            "price": 140.0,
            "lower": 105.0,
            "upper": 186.0,
            "coverage": 0.8,
        },
        "ols_r2": 0.55,
        "ols_condition_number": 1000.0,
        "benchmark": {
            "client": {
                "property_url": "subject",
                "property_name": "Subject Stay",
                "property_type": "Apartment",
                "reference_price_per_night": 150.0,
            },
            "benchmark_windows": [
                {"checkin": "2026-07-01", "lead_time_days": 7, "stay_length_days": 4}
            ],
            "coverage": {
                "peer_price_rows": 2,
                "subject_price_rows": 1,
            },
            "peer_set": {
                "peer_properties_with_prices": 2,
                "flags": [],
            },
            "peer_price_distribution": {
                "p25": 110.0,
                "median": 120.0,
                "p75": 130.0,
            },
            "subject_price_distribution": {
                "median": 150.0,
            },
            "subject_percentile_vs_peers": 75.0,
            "price_gap_to_peer_median": 30.0,
            "price_gap_to_peer_median_pct": 0.25,
            "peers": [
                {
                    "property_url": "near",
                    "property_name": "Near Peer",
                    "property_type": "Apartment",
                    "distance_km": 0.2,
                    "feature_similarity": 0.9,
                    "overall_similarity": 0.95,
                    "median_price_per_night": 120.0,
                    "price_row_count": 2,
                    "room_count": 1,
                }
            ],
            "peer_price_rows": [
                {
                    "property_name": "Near Peer",
                    "property_url": "near",
                    "room_id": "near-room",
                    "room_name": "Apartment",
                    "block_id": "near-2026-07-01",
                    "checkin": "2026-07-01",
                    "checkout": "2026-07-05",
                    "lead_time_days": 7,
                    "stay_length_days": 4,
                    "price_per_night": 120.0,
                    "current_price_value": 480.0,
                }
            ],
        },
        "adjusted_peer_price_distribution": {
            "count": 1,
            "p25": 140.0,
            "median": 140.0,
            "p75": 140.0,
        },
        "adjusted_peer_price_rows": [
            {
                "property_name": "Near Peer",
                "property_url": "near",
                "room_id": "near-room",
                "room_name": "Apartment",
                "block_id": "near-2026-07-01",
                "checkin": "2026-07-01",
                "checkout": "2026-07-05",
                "lead_time_days": 7,
                "stay_length_days": 4,
                "price_per_night": 120.0,
                "predicted_peer_price_per_night": 125.0,
                "predicted_client_like_price_per_night": 145.0,
                "feature_adjustment_factor": 1.2,
                "feature_adjusted_price_per_night": 144.0,
            }
        ],
        "gap_explanation": {
            "client_price_per_night": 150.0,
            "competitor_price_per_night": 120.0,
            "observed_gap": 30.0,
            "feature_explained_gap": 20.0,
            "residual_gap": 10.0,
            "client_predicted_price_per_night": 145.0,
            "competitor_predicted_price_per_night": 125.0,
            "top_feature_contributions_log_points": [
                {"feature": "room_size_sqm", "contribution_log_points": 0.05}
            ],
        },
    }


class PricingWorkbookExportTests(unittest.TestCase):
    def test_workbook_contains_expected_sheets_and_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "pricing.xlsx"
            write_pricing_workbook(_payload(), out)

            with zipfile.ZipFile(out) as archive:
                names = set(archive.namelist())
                self.assertIn("xl/workbook.xml", names)
                self.assertIn("xl/styles.xml", names)
                self.assertIn("xl/worksheets/sheet1.xml", names)
                workbook_xml = archive.read("xl/workbook.xml")
                summary_xml = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
                adjusted_xml = archive.read("xl/worksheets/sheet5.xml").decode("utf-8")

            root = ElementTree.fromstring(workbook_xml)
            namespace = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            sheet_names = [sheet.attrib["name"] for sheet in root.findall("main:sheets/main:sheet", namespace)]
            self.assertEqual(
                sheet_names,
                [
                    "Summary",
                    "Benchmark Windows",
                    "Peer Set",
                    "Raw Peer Rows",
                    "Adjusted Peer Rows",
                    "Gap Decomposition",
                ],
            )
            self.assertIn("Subject Stay", summary_xml)
            self.assertIn("Feature-Adjusted Benchmark", summary_xml)
            self.assertIn("feature_adjusted_price_per_night", adjusted_xml)
            # Phase E: the ± conformal band and the chosen model surface on Summary.
            self.assertIn("Prediction Band", summary_xml)
            self.assertIn("80% conformal band", summary_xml)
            self.assertIn("Selected Model", summary_xml)
            self.assertIn("hist_gradient_boosting", summary_xml)


if __name__ == "__main__":
    unittest.main()
