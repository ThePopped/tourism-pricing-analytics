import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
MODELLING_DIR = REPO_ROOT / "data" / "modelling"


class MarkdownReportOutputTests(unittest.TestCase):
    def test_competitor_report_contains_client_and_peer_benchmark_contract(self) -> None:
        report = (MODELLING_DIR / "competitor_report.md").read_text(encoding="utf-8")

        required_fragments = [
            "# Comparable Competitor Benchmark",
            "## Client",
            "- Property: Stavros Villas & Apartments",
            "## Benchmark Windows",
            "## Peer Price Position",
            "- Peer rows:",
            "- Peer properties with prices:",
            "- Subject percentile vs peers:",
            "- Gap to peer median:",
            "## Top Comparable Properties",
        ]
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, report)

    def test_hedonic_report_contains_adjusted_benchmark_and_gap_contract(self) -> None:
        report = (MODELLING_DIR / "hedonic_report.md").read_text(encoding="utf-8")

        required_fragments = [
            "# Hedonic Price Adjustment",
            "## Training Summary",
            "## OLS Market Premia",
            "## Feature-Adjusted Comparable Benchmark",
            "- Client: Stavros Villas & Apartments",
            "- Raw peer median:",
            "- Feature-adjusted peer median:",
            "- Feature-adjusted IQR:",
            "## Price Gap Decomposition",
            "- Feature-explained gap:",
            "- Residual gap:",
        ]
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, report)


    def test_positioning_narrative_contains_client_facing_sections(self) -> None:
        report = (MODELLING_DIR / "positioning_narrative.md").read_text(encoding="utf-8")

        required_fragments = [
            "# Competitive Pricing Position: Stavros Villas & Apartments",
            "## Bottom line",
            "## Who you are compared against",
            "## Your price position today",
            "## Is the premium justified?",
            "## Recommendation",
            "## How to read these numbers",
            "Justified by stronger features:",
            "Unexplained premium",
        ]
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, report)


class ClientSpecExampleTests(unittest.TestCase):
    def test_client_spec_example_contains_supported_hand_entered_fields(self) -> None:
        spec_path = MODELLING_DIR / "client_spec_example.json"
        spec = json.loads(spec_path.read_text(encoding="utf-8"))

        self.assertEqual(spec["property_name"], "Example Chania Apartment")
        self.assertEqual(spec["property_type"], "Apartment")
        self.assertIsInstance(spec["amenities"], list)
        self.assertIsInstance(spec["property_facilities"], list)
        for required_key in [
            "latitude",
            "longitude",
            "room_size_sqm",
            "bed_count",
            "star_rating",
            "review_score",
            "price_per_night",
        ]:
            with self.subTest(required_key=required_key):
                self.assertIn(required_key, spec)


if __name__ == "__main__":
    unittest.main()
