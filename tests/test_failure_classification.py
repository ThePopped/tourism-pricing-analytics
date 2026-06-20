import unittest
from pathlib import Path

from tourism_pricing_analytics.scraping.booking.failures import classify_page_failure


REQUESTED_URL = "https://www.booking.com/hotel/gr/example.en-gb.html?checkin=2026-07-04"
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "data" / "sample" / "raw_html"


def padded_html(body_text: str) -> str:
    padding = " Booking.com availability room type guest reviews facilities" * 20
    return f"<html><body>{body_text}{padding}</body></html>"


class FailureClassificationTests(unittest.TestCase):
    def test_returns_none_when_expected_selector_is_present(self) -> None:
        classification = classify_page_failure(
            padded_html("rooms"),
            final_url=REQUESTED_URL,
            requested_url=REQUESTED_URL,
            expected_selector_count=3,
        )

        self.assertIsNone(classification)

    def test_classifies_empty_availability_text(self) -> None:
        classification = classify_page_failure(
            padded_html("No availability for your dates. Change your dates."),
            final_url=REQUESTED_URL,
            requested_url=REQUESTED_URL,
            expected_selector_count=0,
        )

        self.assertIsNotNone(classification)
        self.assertEqual(classification.category, "empty_availability")

    def test_empty_availability_takes_precedence_over_generic_error_text(self) -> None:
        classification = classify_page_failure(
            padded_html(
                "We have no availability on our site for this property. "
                "Something went wrong. Please try again later."
            ),
            final_url=REQUESTED_URL,
            requested_url=REQUESTED_URL,
            expected_selector_count=0,
            status_code=200,
        )

        self.assertIsNotNone(classification)
        self.assertEqual(classification.category, "empty_availability")

    def test_classifies_empty_availability_fixture(self) -> None:
        html = (FIXTURE_DIR / "elia_daliani_empty_availability.html").read_text(
            encoding="utf-8"
        )

        classification = classify_page_failure(
            html,
            final_url=REQUESTED_URL,
            requested_url=REQUESTED_URL,
            expected_selector_count=0,
            fallback_selector_count=2,
            status_code=200,
        )

        self.assertIsNotNone(classification)
        self.assertEqual(classification.category, "empty_availability")

    def test_ignores_temporary_error_text_inside_scripts(self) -> None:
        classification = classify_page_failure(
            padded_html(
                "<script>window.translations = {'error': 'server error'};</script>"
                "Property highlights. Room type."
            ),
            final_url=REQUESTED_URL,
            requested_url=REQUESTED_URL,
            expected_selector_count=0,
            fallback_selector_count=1,
            status_code=200,
        )

        self.assertIsNotNone(classification)
        self.assertEqual(classification.category, "selector_drift")

    def test_classifies_selector_drift_on_loaded_property_page(self) -> None:
        classification = classify_page_failure(
            padded_html("Property highlights. Room type. Select rooms."),
            final_url=REQUESTED_URL,
            requested_url=REQUESTED_URL,
            expected_selector_count=0,
            fallback_selector_count=2,
        )

        self.assertIsNotNone(classification)
        self.assertEqual(classification.category, "selector_drift")

    def test_classifies_redirect_when_property_path_changes(self) -> None:
        classification = classify_page_failure(
            padded_html("Booking.com"),
            final_url="https://www.booking.com/searchresults.en-gb.html",
            requested_url=REQUESTED_URL,
            expected_selector_count=0,
        )

        self.assertIsNotNone(classification)
        self.assertEqual(classification.category, "redirect")

    def test_classifies_blocked_challenge_page(self) -> None:
        classification = classify_page_failure(
            "<html><body>Please verify you're human before continuing.</body></html>",
            final_url=REQUESTED_URL,
            requested_url=REQUESTED_URL,
            expected_selector_count=0,
        )

        self.assertIsNotNone(classification)
        self.assertEqual(classification.category, "blocked_challenge")

    def test_classifies_partial_load_for_tiny_unknown_page(self) -> None:
        classification = classify_page_failure(
            "<html><body>Loading</body>",
            final_url=REQUESTED_URL,
            requested_url=REQUESTED_URL,
            expected_selector_count=0,
        )

        self.assertIsNotNone(classification)
        self.assertEqual(classification.category, "partial_load")

    def test_classifies_temporary_booking_error_from_status_code(self) -> None:
        classification = classify_page_failure(
            padded_html("Booking.com"),
            final_url=REQUESTED_URL,
            requested_url=REQUESTED_URL,
            expected_selector_count=0,
            status_code=503,
        )

        self.assertIsNotNone(classification)
        self.assertEqual(classification.category, "temporary_booking_error")


if __name__ == "__main__":
    unittest.main()
