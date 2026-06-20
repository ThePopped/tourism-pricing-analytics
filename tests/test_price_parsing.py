import unittest

from tourism_pricing_analytics.scraping.booking.parsing import (
    compute_price_per_night,
    normalize_price_text,
)


class PriceParsingTests(unittest.TestCase):
    def test_normalize_price_text_parses_booking_thousands_separator(self) -> None:
        self.assertEqual(normalize_price_text("EUR 1,095"), 1095.0)

    def test_normalize_price_text_parses_plain_integer_price(self) -> None:
        self.assertEqual(normalize_price_text("EUR 919"), 919.0)

    def test_normalize_price_text_parses_comma_thousands_with_decimal(self) -> None:
        self.assertEqual(normalize_price_text("EUR 1,095.50"), 1095.5)

    def test_normalize_price_text_parses_european_decimal_format(self) -> None:
        self.assertEqual(normalize_price_text("EUR 1.095,50"), 1095.5)

    def test_normalize_price_text_parses_dot_thousands_separator(self) -> None:
        self.assertEqual(normalize_price_text("EUR 2.800"), 2800.0)

    def test_normalize_price_text_returns_none_for_missing_or_empty_values(self) -> None:
        self.assertIsNone(normalize_price_text(None))
        self.assertIsNone(normalize_price_text(""))
        self.assertIsNone(normalize_price_text("Price unavailable"))

    def test_compute_price_per_night_uses_total_price_and_stay_length(self) -> None:
        self.assertEqual(compute_price_per_night(1095.0, 4), 273.75)

    def test_compute_price_per_night_handles_missing_or_invalid_values(self) -> None:
        self.assertIsNone(compute_price_per_night(None, 4))
        self.assertIsNone(compute_price_per_night(1095.0, 0))


if __name__ == "__main__":
    unittest.main()
