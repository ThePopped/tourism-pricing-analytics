"""Fixture regression tests for Tier B room feature extraction.

Runs the full room-extractor registry through ``extract_room_features`` against
saved real property pages, asserting exact expected values per extractor. Mirrors
the Playwright ``set_content`` pattern used by the price-row fixture tests.
"""

import unittest
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from tourism_pricing_analytics.scraping.booking.features.extract import extract_room_features


FIXTURE_DIR = Path(__file__).resolve().parent.parent / "data" / "sample" / "raw_html"
ELIA_PALATINO_FIXTURE = FIXTURE_DIR / "elia_palatino_listing_page.html"
DISCOUNTED_FIXTURE = FIXTURE_DIR / "selected_suites_discounted_page.html"
CAPTURED_AT = "2026-06-20T00:00:00"


class _FixturePageTest(unittest.TestCase):
    """Base class wiring a headless Playwright page from a saved fixture."""

    fixture_path: Path

    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture_html = cls.fixture_path.read_text(encoding="utf-8")
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

    def tearDown(self) -> None:
        self.page.close()


class EliaPalatinoRoomFeatureTests(_FixturePageTest):
    fixture_path = ELIA_PALATINO_FIXTURE

    def _extract(self):
        return extract_room_features(
            self.page,
            property_name="Elia Palatino Hotel",
            property_url="https://www.booking.com/hotel/gr/elia-palatino.en-gb.html",
            captured_at=CAPTURED_AT,
        )

    def test_extracts_one_record_per_real_room(self) -> None:
        records = self._extract()
        # The "Room Assigned on Arrival" header row has a non-numeric block id
        # ("bbasic_0") and no data-room-id, so it yields no resolvable room_id and
        # is skipped, leaving the three real rooms.
        self.assertEqual([r.room_id for r in records], ["217097709", "217097702", "217097704"])
        for record in records:
            self.assertEqual(record.property_url, "https://www.booking.com/hotel/gr/elia-palatino.en-gb.html")
            self.assertEqual(record.captured_at, CAPTURED_AT)

    def test_classic_room_features(self) -> None:
        record = {r.room_id: r for r in self._extract()}["217097709"]
        self.assertEqual(record.room_size_sqm, 25.0)
        self.assertEqual(record.bed_types, ["1 extra-large double bed", "2 single beds"])
        self.assertEqual(record.bed_count, 3)
        self.assertEqual(record.max_persons, 1)
        self.assertEqual(record.room_class, "Classic")
        self.assertEqual(len(record.amenities), 37)
        # Amenities are captured raw, so the size token leads the list and known
        # amenities are present verbatim.
        self.assertTrue(record.amenities[0].startswith("25"))
        self.assertIn("Air conditioning", record.amenities)
        self.assertIn("Free WiFi", record.amenities)

    def test_superior_room_features(self) -> None:
        record = {r.room_id: r for r in self._extract()}["217097702"]
        self.assertEqual(record.room_size_sqm, 27.0)
        self.assertEqual(record.max_persons, 1)
        self.assertEqual(record.room_class, "Superior")
        self.assertEqual(len(record.amenities), 39)

    def test_deluxe_room_features_use_sleeps_range_for_occupancy(self) -> None:
        record = {r.room_id: r for r in self._extract()}["217097704"]
        self.assertEqual(record.room_size_sqm, 18.0)
        self.assertEqual(record.bed_types, ["1 large double bed", "2 single beds"])
        self.assertEqual(record.bed_count, 3)
        # Occupancy is given as "Sleeps: 1 - 2 guests"; the upper bound is used.
        self.assertEqual(record.max_persons, 2)
        self.assertEqual(record.room_class, "Deluxe")


class SelectedSuitesRoomFeatureTests(_FixturePageTest):
    fixture_path = DISCOUNTED_FIXTURE

    def test_suite_room_features_with_unstructured_beds(self) -> None:
        records = extract_room_features(
            self.page,
            property_name="Selected Suites",
            property_url="https://www.booking.com/hotel/gr/selected-suites.en-gb.html",
            captured_at=CAPTURED_AT,
        )
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.room_id, "1377003802")
        self.assertEqual(record.room_size_sqm, 32.0)
        self.assertEqual(record.max_persons, 2)
        self.assertEqual(record.room_class, "Suite")
        self.assertEqual(len(record.amenities), 36)
        # This room block has no structured .rt-bed-type elements, so the bed
        # fields are left at their defaults rather than guessed.
        self.assertEqual(record.bed_types, [])
        self.assertIsNone(record.bed_count)


if __name__ == "__main__":
    unittest.main()
