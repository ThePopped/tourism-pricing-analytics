"""Fixture regression tests for Tier C property feature extraction.

Runs the full property-extractor registry through ``extract_property_features``
against the saved Elia Palatino property page, asserting exact expected values
per extractor. The fixture is a fully-scrolled DOM, so the facilities, review
subscores, and surroundings sections are present and parsed here.
"""

import unittest
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from tourism_pricing_analytics.scraping.booking.features.extract_property import (
    extract_property_features,
)
from tourism_pricing_analytics.scraping.booking.features.property.prop_type import (
    _property_type_from_breadcrumb,
)


FIXTURE_DIR = Path(__file__).resolve().parent.parent / "data" / "sample" / "raw_html"
ELIA_PALATINO_FIXTURE = FIXTURE_DIR / "elia_palatino_listing_page.html"
PROPERTY_URL = "https://www.booking.com/hotel/gr/elia-palatino.en-gb.html"
CAPTURED_AT = "2026-06-20T00:00:00"


class PropertyTypeBreadcrumbTests(unittest.TestCase):
    def test_property_name_parentheses_do_not_become_property_type(self) -> None:
        text = "MYLOS (6) (Apartment) (Greece) deals"

        self.assertEqual(_property_type_from_breadcrumb(text), "Apartment")

    def test_adults_only_parentheses_do_not_become_property_type(self) -> None:
        text = "Giannoulis - Grand Bay Beach Resort (Exclusive Adults Only) (Resort) (Greece) deals"

        self.assertEqual(_property_type_from_breadcrumb(text), "Resort")

    def test_unknown_parentheticals_are_ignored(self) -> None:
        text = "Mystery Stay (6) (Greece) deals"

        self.assertIsNone(_property_type_from_breadcrumb(text))


class EliaPalatinoPropertyFeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture_html = ELIA_PALATINO_FIXTURE.read_text(encoding="utf-8")
        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch(headless=True)
        except PlaywrightError as exc:
            cls.playwright.stop()
            raise unittest.SkipTest(f"Playwright browser is unavailable: {exc}") from exc

    @classmethod
    def tearDownClass(cls) -> None:
        browser = getattr(cls, "browser", None)
        if browser is not None:
            browser.close()
        playwright = getattr(cls, "playwright", None)
        if playwright is not None:
            playwright.stop()

    def setUp(self) -> None:
        self.page = self.browser.new_page()
        self.page.set_content(self.fixture_html, wait_until="domcontentloaded")
        self.record = extract_property_features(
            self.page,
            property_name="Elia Palatino Hotel",
            property_url=PROPERTY_URL,
            captured_at=CAPTURED_AT,
        )

    def tearDown(self) -> None:
        self.page.close()

    def test_identity_fields(self) -> None:
        self.assertEqual(self.record.property_name, "Elia Palatino Hotel")
        self.assertEqual(self.record.property_url, PROPERTY_URL)
        self.assertEqual(self.record.captured_at, CAPTURED_AT)

    def test_geo_coordinates(self) -> None:
        self.assertAlmostEqual(self.record.latitude, 35.5165111588737)
        self.assertAlmostEqual(self.record.longitude, 24.0165669601189)

    def test_review_score_and_count(self) -> None:
        self.assertEqual(self.record.review_score, 9.1)
        self.assertEqual(self.record.review_count, 242)

    def test_review_subscores_map(self) -> None:
        self.assertEqual(
            self.record.review_subscores,
            {
                "Staff": 9.3,
                "Facilities": 9.0,
                "Cleanliness": 9.4,
                "Comfort": 9.4,
                "Value for money": 9.1,
                "Location": 9.7,
                "Free WiFi": 10.0,
            },
        )

    def test_property_type(self) -> None:
        self.assertEqual(self.record.property_type, "Hotel")

    def test_star_rating_absent_for_unrated_property(self) -> None:
        # This hotel displays no official class rating, so the field is null
        # rather than a guessed value.
        self.assertIsNone(self.record.star_rating)

    def test_property_facilities_raw_list(self) -> None:
        facilities = self.record.property_facilities
        self.assertEqual(len(facilities), 75)
        self.assertEqual(facilities[0], "Private bathroom")
        self.assertIn("Free WiFi", facilities)
        self.assertIn("Airport shuttle", facilities)
        # Languages are captured separately, not duplicated into facilities.
        self.assertNotIn("Greek", facilities)

    def test_nearby_poi_pairs(self) -> None:
        pois = self.record.nearby_poi
        self.assertEqual(len(pois), 19)
        self.assertEqual(
            pois[0],
            {
                "poi_name": "Etz Hayyim Synagogue",
                "distance": 150.0,
                "unit": "m",
                "category": "Top attractions",
            },
        )
        airports = [p for p in pois if p["category"] == "Closest airports"]
        self.assertEqual(
            airports,
            [
                {
                    "poi_name": "Chania International Airport",
                    "distance": 13.0,
                    "unit": "km",
                    "category": "Closest airports",
                }
            ],
        )

    def test_checkin_and_checkout_times(self) -> None:
        self.assertEqual(self.record.checkin_from, "15:00")
        self.assertEqual(self.record.checkin_until, "00:00")
        self.assertEqual(self.record.checkout_from, "07:00")
        self.assertEqual(self.record.checkout_until, "11:00")

    def test_house_rules_cancellation_summary(self) -> None:
        self.assertIsNotNone(self.record.house_rules)
        self.assertIn("cancellation", self.record.house_rules)
        self.assertTrue(
            self.record.house_rules["cancellation"].startswith(
                "Cancellation and prepayment policies vary"
            )
        )

    def test_languages_spoken(self) -> None:
        self.assertEqual(self.record.languages_spoken, ["Greek", "English"])

    def test_absent_best_effort_fields_are_null(self) -> None:
        self.assertIsNone(self.record.photo_count)
        self.assertIsNone(self.record.sustainability_level)


if __name__ == "__main__":
    unittest.main()
