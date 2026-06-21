import unittest
from pathlib import Path

from tourism_pricing_analytics.scraping.booking.listings import (
    ListingCandidate,
    normalize_listing_url,
    parse_listings,
)


FIXTURE_DIR = Path(__file__).resolve().parent.parent / "data" / "sample" / "raw_html"
LISTINGS_SAMPLE = FIXTURE_DIR / "listings_chania_sample.html"


class NormalizeListingUrlTests(unittest.TestCase):
    def test_strips_query_and_fragment(self) -> None:
        href = (
            "https://www.booking.com/hotel/gr/nearchou-boutique.en-gb.html"
            "?label=gen173bo-abc&checkin=2026-04-03&checkout=2026-04-04#room"
        )
        self.assertEqual(
            normalize_listing_url(href),
            "https://www.booking.com/hotel/gr/nearchou-boutique.en-gb.html",
        )

    def test_passes_through_canonical_url(self) -> None:
        url = "https://www.booking.com/hotel/gr/adriana-apartment.en-gb.html"
        self.assertEqual(normalize_listing_url(url), url)

    def test_rejects_non_hotel_url(self) -> None:
        self.assertIsNone(
            normalize_listing_url("https://www.booking.com/searchresults.html?dest_id=2006")
        )

    def test_rejects_empty_and_none(self) -> None:
        self.assertIsNone(normalize_listing_url(None))
        self.assertIsNone(normalize_listing_url(""))


class ParseListingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.candidates = parse_listings(LISTINGS_SAMPLE.read_text(encoding="utf-8"))
        cls.by_url = {c.url: c for c in cls.candidates}

    def test_extracts_unique_properties_in_order(self) -> None:
        names = [c.name for c in self.candidates]
        # Card 6 duplicates Adriana Apartment and must be collapsed.
        self.assertEqual(
            names,
            [
                "Nearchou Boutique Hotel",
                "Adriana Apartment",
                "Domes Zeen Chania",
                "Rooms 47",
                "Villa Avra Crete",
            ],
        )

    def test_urls_are_normalized(self) -> None:
        self.assertTrue(
            all(c.url.endswith(".en-gb.html") and "?" not in c.url for c in self.candidates)
        )
        self.assertIn(
            "https://www.booking.com/hotel/gr/nearchou-boutique.en-gb.html",
            self.by_url,
        )

    def test_captures_enrichment_fields(self) -> None:
        nearchou = self.by_url[
            "https://www.booking.com/hotel/gr/nearchou-boutique.en-gb.html"
        ]
        self.assertEqual(nearchou.price_text, "€ 116")
        self.assertEqual(
            nearchou.review_score_text, "Scored 9.8 9.8 Exceptional 191 reviews"
        )
        self.assertIn("Deluxe Double Room", nearchou.recommended_unit_text)

    def test_optional_fields_are_none_when_absent(self) -> None:
        rooms47 = self.by_url["https://www.booking.com/hotel/gr/rooms-47.en-gb.html"]
        self.assertEqual(rooms47.price_text, "€ 39")
        self.assertIsNone(rooms47.review_score_text)
        self.assertIsNone(rooms47.recommended_unit_text)

    def test_discounted_price_text_includes_both_values(self) -> None:
        domes = self.by_url["https://www.booking.com/hotel/gr/domes-zeen-chania.en-gb.html"]
        self.assertIn("380", domes.price_text)
        self.assertIn("304", domes.price_text)

    def test_falls_back_to_image_link_when_title_link_absent(self) -> None:
        self.assertIn(
            "https://www.booking.com/hotel/gr/villa-avra-crete.en-gb.html",
            self.by_url,
        )

    def test_duplicate_collapses_to_first_occurrence(self) -> None:
        adriana = self.by_url[
            "https://www.booking.com/hotel/gr/adriana-apartment.en-gb.html"
        ]
        # First occurrence priced 72, the duplicate (75) is discarded.
        self.assertEqual(adriana.price_text, "€ 72")

    def test_returns_listing_candidate_instances(self) -> None:
        self.assertTrue(all(isinstance(c, ListingCandidate) for c in self.candidates))

    def test_empty_html_yields_no_candidates(self) -> None:
        self.assertEqual(parse_listings("<html><body></body></html>"), [])


if __name__ == "__main__":
    unittest.main()
