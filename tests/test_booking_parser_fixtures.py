import unittest
from datetime import date
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from tourism_pricing_analytics.scraping.booking.failures import classify_page_failure
from tourism_pricing_analytics.scraping.booking.models import PropertyTarget
from tourism_pricing_analytics.scraping.booking.parsing import (
    extract_price_rows,
    extract_room_inventory,
)
from tourism_pricing_analytics.scraping.booking.runner import (
    PRICE_ROW_FALLBACK_SELECTORS,
    PRICE_ROW_SELECTOR,
    ROOM_INVENTORY_FALLBACK_SELECTORS,
    ROOM_INVENTORY_SELECTOR,
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


class RoomIdRecoveryFixtureTests(unittest.TestCase):
    """A price row that lacks a usable room-type header must still be attributed
    to its room by recovering the room id from the ``data-block-id`` prefix,
    rather than emitting a null ``room_id`` (the carry-forward edge case seen in
    live runs). Uses a small synthetic table so no large fixture is required.
    """

    SYNTHETIC_HTML = """
    <html><body><table><tbody>
      <tr class="js-rt-block-row" data-block-id="555000111_222_0_1_0">
        <th class="hprt-table-cell-roomtype">
          <a class="hprt-roomtype-link">Studio Apartment</a>
        </th>
        <td class="hprt-table-cell-occupancy">2 adults</td>
        <td class="hprt-table-cell-conditions">Free cancellation</td>
        <td><div class="bui-price-display__value">&euro; 300</div></td>
      </tr>
      <tr class="js-rt-block-row" data-block-id="555000111_222_1_1_0">
        <td class="hprt-table-cell-occupancy">2 adults</td>
        <td class="hprt-table-cell-conditions">Non-refundable</td>
        <td><div class="bui-price-display__value">&euro; 260</div></td>
      </tr>
    </tbody></table></body></html>
    """

    TARGET = PropertyTarget(
        name="Synthetic Property",
        url="https://www.booking.com/hotel/gr/synthetic.en-gb.html",
    )

    @classmethod
    def setUpClass(cls) -> None:
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
        self.page.set_content(self.SYNTHETIC_HTML, wait_until="domcontentloaded")

    def tearDown(self) -> None:
        self.page.close()

    def test_room_id_recovered_from_block_id_when_header_missing(self) -> None:
        records = extract_price_rows(
            self.page,
            target=self.TARGET,
            checkin=date(2026, 7, 4),
            checkout=date(2026, 7, 11),
            lead_time_days=14,
            stay_length_days=7,
            captured_at=CAPTURED_AT,
        )

        self.assertEqual(len(records), 2)
        # Both the header row (whose link carries no data-room-id) and the
        # following headerless row resolve to the block-id room prefix.
        self.assertEqual([record.room_id for record in records], ["555000111", "555000111"])
        self.assertTrue(all(record.room_id is not None for record in records))


class GenericBlockRoomNameFixtureTests(unittest.TestCase):
    """Booking's generic "bbasic" block exposes a room name but no numeric room
    id, and its block id ("bbasic_0") has no numeric prefix to recover. Such a
    row must keep its room_name (null room_id), so it stays attributable by name
    and is reconciled to an id downstream rather than dropped.
    """

    SYNTHETIC_HTML = """
    <html><body><table><tbody>
      <tr class="js-rt-block-row" data-block-id="bbasic_0">
        <th class="hprt-table-cell-roomtype">
          <a class="hprt-roomtype-link">Deluxe Double Room</a>
        </th>
        <td class="hprt-table-cell-occupancy">2 adults</td>
        <td class="hprt-table-cell-conditions">Non-refundable</td>
        <td><div class="bui-price-display__value">&euro; 895</div></td>
      </tr>
    </tbody></table></body></html>
    """

    TARGET = PropertyTarget(
        name="Generic Block Property",
        url="https://www.booking.com/hotel/gr/generic-block.en-gb.html",
    )

    @classmethod
    def setUpClass(cls) -> None:
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
        self.page.set_content(self.SYNTHETIC_HTML, wait_until="domcontentloaded")

    def tearDown(self) -> None:
        self.page.close()

    def test_generic_block_keeps_room_name_with_null_room_id(self) -> None:
        records = extract_price_rows(
            self.page,
            target=self.TARGET,
            checkin=date(2026, 7, 4),
            checkout=date(2026, 7, 11),
            lead_time_days=14,
            stay_length_days=7,
            captured_at=CAPTURED_AT,
        )

        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertIsNone(record.room_id)
        self.assertEqual(record.room_name, "Deluxe Double Room")


class SelectorDriftFixtureTests(unittest.TestCase):
    """A fully-loaded Booking.com property page whose availability widget has
    drifted: the room-inventory anchors, the price-row table rows, and every
    fallback selector were renamed in a hypothetical redesign, so the parser
    yields zero records even though the page is intact.

    This must classify as ``selector_drift`` — distinct from
    ``empty_availability`` (sold-out text) and ``partial_load`` (a truncated
    page) — so a silent Booking.com DOM change is surfaced as drift rather than
    mistaken for a legitimately empty result. The page keeps recognizable
    property-page text (Property highlights, Guest reviews, Facilities, room
    type) so it is classified by content, not by a stray fallback selector.
    Synthetic so no large page is committed.
    """

    TARGET = PropertyTarget(
        name="Drifted Hotel",
        url="https://www.booking.com/hotel/gr/drifted.en-gb.html",
    )
    REQUESTED_URL = TARGET.url + "?checkin=2026-07-04&checkout=2026-07-11"

    DRIFTED_HTML = """
    <html><head><title>Drifted Hotel, Crete – Booking.com</title></head>
    <body>
      <header>Booking.com</header>
      <h1>Drifted Hotel</h1>
      <section><h2>Property highlights</h2>
        <p>Top location near the old town, moments from the beach, with free
           WiFi throughout the property and private parking on site.</p></section>
      <section><h2>Guest reviews</h2>
        <p>Rated wonderful by recent guests, who praised the cleanliness, the
           comfortable beds, and the friendly, helpful staff at reception.</p>
      </section>
      <section><h2>Facilities</h2>
        <ul><li>Outdoor swimming pool</li><li>Spa and wellness centre</li>
            <li>Airport shuttle service</li><li>Family rooms available</li>
            <li>Restaurant and bar on site</li></ul></section>
      <section id="rooms"><h2>Choose your room type</h2>
        <p>Pick a room type for your stay using the options below.</p>
        <!-- Availability widget after a hypothetical Booking redesign: every
             previously-stable class, id, and anchor scheme has been renamed,
             so neither the primary nor the fallback selectors match. -->
        <table class="roomstable-v3">
          <tbody>
            <tr class="room-offer-row">
              <th class="room-heading">
                <a class="room-name-link" href="#room-217097709">Classic Room</a>
              </th>
              <td class="guests">2 adults</td>
              <td class="rate-conditions">Free cancellation</td>
              <td><div class="rate-amount">&euro; 122</div></td>
            </tr>
            <tr class="room-offer-row">
              <th class="room-heading">
                <a class="room-name-link" href="#room-217097704">Deluxe Room</a>
              </th>
              <td class="guests">2 adults</td>
              <td class="rate-conditions">Non-refundable</td>
              <td><div class="rate-amount">&euro; 213</div></td>
            </tr>
          </tbody>
        </table>
      </section>
    </body></html>
    """

    @classmethod
    def setUpClass(cls) -> None:
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
        self.page.set_content(self.DRIFTED_HTML, wait_until="domcontentloaded")

    def tearDown(self) -> None:
        self.page.close()

    def test_drifted_page_yields_no_records(self) -> None:
        inventory = extract_room_inventory(
            self.page,
            target=self.TARGET,
            property_url=self.TARGET.url,
            captured_at=CAPTURED_AT,
        )
        self.assertEqual(inventory, [])

        price_rows = extract_price_rows(
            self.page,
            target=self.TARGET,
            checkin=date(2026, 7, 4),
            checkout=date(2026, 7, 11),
            lead_time_days=14,
            stay_length_days=7,
            captured_at=CAPTURED_AT,
        )
        self.assertEqual(price_rows, [])

    def _classify_drift(self, expected_selector: str, fallback_selectors: list[str]):
        """Classify the loaded page using selector counts taken from the live
        browser DOM (the same counting the runner does), with a non-redirected
        final URL so the drift signal is isolated from the redirect check."""
        expected_count = self.page.locator(expected_selector).count()
        fallback_count = sum(
            self.page.locator(selector).count() for selector in fallback_selectors
        )
        # The drift is concrete: neither the primary nor any fallback selector
        # matches this redesigned DOM, yet the page is fully loaded.
        self.assertEqual(expected_count, 0)
        self.assertEqual(fallback_count, 0)
        return classify_page_failure(
            self.page.content(),
            final_url=self.REQUESTED_URL,
            requested_url=self.REQUESTED_URL,
            expected_selector_count=expected_count,
            fallback_selector_count=fallback_count,
            status_code=200,
        )

    def test_room_inventory_failure_classifies_as_selector_drift(self) -> None:
        classification = self._classify_drift(
            ROOM_INVENTORY_SELECTOR, ROOM_INVENTORY_FALLBACK_SELECTORS
        )

        self.assertIsNotNone(classification)
        self.assertEqual(classification.category, "selector_drift")

    def test_price_row_failure_classifies_as_selector_drift(self) -> None:
        classification = self._classify_drift(
            PRICE_ROW_SELECTOR, PRICE_ROW_FALLBACK_SELECTORS
        )

        self.assertIsNotNone(classification)
        self.assertEqual(classification.category, "selector_drift")


if __name__ == "__main__":
    unittest.main()
