import unittest
from datetime import date
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from tourism_pricing_analytics.scraping.booking.models import PropertyTarget
from tourism_pricing_analytics.scraping.booking.parsing import (
    extract_price_rows,
    extract_room_inventory,
)


FIXTURE_DIR = Path(__file__).resolve().parent.parent / "data" / "sample" / "raw_html"
ELIA_PALATINO_FIXTURE = FIXTURE_DIR / "elia_palatino_listing_page.html"
DISCOUNTED_FIXTURE = FIXTURE_DIR / "selected_suites_discounted_page.html"
CAPTURED_AT = "2026-06-20T00:00:00"
TARGET = PropertyTarget(
    name="Elia Palatino Hotel",
    url="https://www.booking.com/hotel/gr/elia-palatino.en-gb.html",
)
DISCOUNTED_TARGET = PropertyTarget(
    name="Selected Suites",
    url="https://www.booking.com/hotel/gr/selected-suites.en-gb.html",
)


class BookingParserFixtureTests(unittest.TestCase):
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

    def tearDown(self) -> None:
        self.page.close()

    def test_extract_room_inventory_from_saved_property_fixture(self) -> None:
        records = extract_room_inventory(
            self.page,
            target=TARGET,
            property_url=TARGET.url,
            captured_at=CAPTURED_AT,
        )

        self.assertEqual(len(records), 3)
        self.assertEqual(
            [record.room_id for record in records],
            ["217097709", "217097702", "217097704"],
        )
        self.assertEqual(
            [record.room_name for record in records],
            [
                "Classic Room",
                "Superior Room",
                "Deluxe room with sea view and balcony",
            ],
        )
        self.assertEqual(len({record.room_id for record in records}), len(records))

        for record in records:
            self.assertEqual(record.property_name, TARGET.name)
            self.assertEqual(record.property_url, TARGET.url)
            self.assertEqual(record.captured_at, CAPTURED_AT)

    def test_extract_price_rows_from_saved_dated_fixture(self) -> None:
        records = extract_price_rows(
            self.page,
            target=TARGET,
            checkin=date(2026, 7, 4),
            checkout=date(2026, 7, 11),
            lead_time_days=14,
            stay_length_days=7,
            captured_at=CAPTURED_AT,
        )

        self.assertEqual(len(records), 8)
        self.assertTrue(all(record.current_price_text for record in records))
        self.assertTrue(all(record.current_price_value is not None for record in records))
        self.assertTrue(all(record.current_price_value > 0 for record in records))
        self.assertTrue(all(record.price_per_night is not None for record in records))
        self.assertTrue(all(record.quantity_options for record in records))

        by_block_id = {record.block_id: record for record in records}
        classic_flexible_row = by_block_id["217097709_383286522_2_1_0"]
        self.assertEqual(classic_flexible_row.room_id, "217097709")
        self.assertEqual(classic_flexible_row.room_name, "Classic Room")
        self.assertEqual(classic_flexible_row.current_price_text, "\u20ac 122")
        self.assertEqual(classic_flexible_row.current_price_value, 122.0)
        self.assertEqual(classic_flexible_row.price_per_night, 17.43)
        self.assertIn("Free cancellation", classic_flexible_row.conditions_text)
        self.assertEqual(
            classic_flexible_row.quantity_options,
            ["0", "1 (\u20ac 122)", "2 (\u20ac 244)"],
        )

        deluxe_row = by_block_id["217097704_383286522_2_1_0"]
        self.assertEqual(deluxe_row.room_id, "217097704")
        self.assertEqual(deluxe_row.room_name, "Deluxe room with sea view and balcony")
        self.assertEqual(deluxe_row.scarcity_text, "We have 1 left")
        self.assertEqual(deluxe_row.current_price_value, 213.0)
        self.assertEqual(deluxe_row.price_per_night, 30.43)


class DiscountedRateFixtureTests(unittest.TestCase):
    """Regression coverage for a real Booking.com page that shows discounted rates.

    The fixture is a saved Selected Suites dated page whose rows carry a
    strikethrough ``.bui-price-display__original`` price alongside the reduced
    ``.bui-price-display__value`` price, exercising the parser's original-price
    handling that the normal-rate fixture does not.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture_html = DISCOUNTED_FIXTURE.read_text(encoding="utf-8")
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

    def test_extract_discounted_price_rows(self) -> None:
        records = extract_price_rows(
            self.page,
            target=DISCOUNTED_TARGET,
            checkin=date(2026, 6, 28),
            checkout=date(2026, 7, 2),
            lead_time_days=7,
            stay_length_days=4,
            captured_at=CAPTURED_AT,
        )

        self.assertEqual(len(records), 2)
        # Every row on this page is discounted: a reduced current price and a
        # higher strikethrough original price that must parse to a larger value.
        for record in records:
            self.assertEqual(record.room_id, "1377003802")
            self.assertEqual(record.room_name, "Suite with Private Steam Room & Pool View")
            self.assertIsNotNone(record.original_price_text)
            self.assertIsNotNone(record.original_price_value)
            self.assertIsNotNone(record.current_price_value)
            self.assertGreater(record.original_price_value, record.current_price_value)

        by_block_id = {record.block_id: record for record in records}

        breakfast_extra = by_block_id["1377003802_409828619_0_2_0"]
        self.assertEqual(breakfast_extra.current_price_text, "€ 698")
        self.assertEqual(breakfast_extra.current_price_value, 698.0)
        self.assertEqual(breakfast_extra.original_price_text, "€ 1,070")
        self.assertEqual(breakfast_extra.original_price_value, 1070.0)
        self.assertEqual(breakfast_extra.price_per_night, 174.5)

        breakfast_included = by_block_id["1377003802_409828619_0_1_0"]
        self.assertEqual(breakfast_included.current_price_text, "€ 802")
        self.assertEqual(breakfast_included.current_price_value, 802.0)
        self.assertEqual(breakfast_included.original_price_text, "€ 1,230")
        self.assertEqual(breakfast_included.original_price_value, 1230.0)
        self.assertEqual(breakfast_included.price_per_night, 200.5)


if __name__ == "__main__":
    unittest.main()
