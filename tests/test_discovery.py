import unittest
from urllib.parse import parse_qs, urlsplit

from scripts.merge_candidates_into_config import (
    build_merged_config,
    merge_candidate_rows,
)
from scripts.generate_full_config import build_config as build_full_config
from tourism_pricing_analytics.scraping.booking.discovery import (
    SELF_CATERING_HT_IDS,
    build_search_url,
    detect_blocked_page,
    merge_candidates,
    should_stop_pagination,
)
from tourism_pricing_analytics.scraping.booking.listings import ListingCandidate
from tourism_pricing_analytics.scraping.booking.models import DefaultSearchConfig


def candidate(name: str, url: str) -> ListingCandidate:
    return ListingCandidate(
        name=name,
        url=url,
        price_text=None,
        review_score_text=None,
        recommended_unit_text=None,
    )


class DiscoveryUrlTests(unittest.TestCase):
    def test_build_search_url_sets_destination_filters_and_occupancy(self) -> None:
        url = build_search_url(
            "Gerani, Chania, Crete, Greece",
            default_search=DefaultSearchConfig(
                group_adults=2,
                group_children=0,
                no_rooms=1,
            ),
        )
        parsed = urlsplit(url)
        params = parse_qs(parsed.query)

        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, "www.booking.com")
        self.assertEqual(parsed.path, "/searchresults.en-gb.html")
        self.assertEqual(params["ss"], ["Gerani, Chania, Crete, Greece"])
        self.assertEqual(params["group_adults"], ["2"])
        self.assertEqual(params["group_children"], ["0"])
        self.assertEqual(params["no_rooms"], ["1"])
        self.assertEqual(
            params["nflt"],
            [";".join(f"ht_id={code}" for code in SELF_CATERING_HT_IDS)],
        )
        self.assertNotIn("offset", params)

    def test_build_search_url_includes_positive_offset_only(self) -> None:
        default_search = DefaultSearchConfig(group_adults=2, group_children=0, no_rooms=1)

        zero_offset = parse_qs(
            urlsplit(
                build_search_url(
                    "Gerani, Chania, Crete, Greece",
                    default_search=default_search,
                    offset=0,
                )
            ).query
        )
        positive_offset = parse_qs(
            urlsplit(
                build_search_url(
                    "Gerani, Chania, Crete, Greece",
                    default_search=default_search,
                    offset=25,
                )
            ).query
        )

        self.assertNotIn("offset", zero_offset)
        self.assertEqual(positive_offset["offset"], ["25"])


class DiscoveryPaginationTests(unittest.TestCase):
    def test_should_stop_when_max_pages_hit(self) -> None:
        self.assertTrue(
            should_stop_pagination(
                new_candidate_count=25,
                page_card_count=25,
                pages_fetched=8,
                max_pages=8,
                page_size=25,
            )
        )

    def test_should_stop_on_short_final_page(self) -> None:
        self.assertTrue(
            should_stop_pagination(
                new_candidate_count=12,
                page_card_count=12,
                pages_fetched=2,
                max_pages=8,
                page_size=25,
            )
        )

    def test_should_stop_on_zero_new_candidates(self) -> None:
        self.assertTrue(
            should_stop_pagination(
                new_candidate_count=0,
                page_card_count=25,
                pages_fetched=2,
                max_pages=8,
                page_size=25,
            )
        )

    def test_should_continue_when_page_is_full_new_and_under_cap(self) -> None:
        self.assertFalse(
            should_stop_pagination(
                new_candidate_count=25,
                page_card_count=25,
                pages_fetched=2,
                max_pages=8,
                page_size=25,
            )
        )


class DiscoveryBlockedPageTests(unittest.TestCase):
    def test_detects_blocked_page_markers(self) -> None:
        self.assertTrue(detect_blocked_page(title="Are you human?", html="<html></html>"))
        self.assertTrue(detect_blocked_page(title="Booking", html="<div>px-captcha</div>"))
        self.assertTrue(detect_blocked_page(title="Booking", html="Access denied"))

    def test_normal_results_are_not_blocked(self) -> None:
        self.assertFalse(
            detect_blocked_page(
                title="Booking.com: Gerani self catering",
                html='<div data-testid="property-card">Normal results</div>',
            )
        )


class DiscoveryMergeTests(unittest.TestCase):
    def test_merge_candidates_deduplicates_excludes_and_preserves_order(self) -> None:
        rows = [
            candidate("First", "https://www.booking.com/hotel/gr/first.en-gb.html?x=1"),
            candidate("Excluded", "https://www.booking.com/hotel/gr/excluded.en-gb.html"),
            candidate("Duplicate", "https://www.booking.com/hotel/gr/first.en-gb.html#room"),
            candidate("Second", "https://www.booking.com/hotel/gr/second.en-gb.html"),
            candidate("Third", "https://www.booking.com/hotel/gr/third.en-gb.html"),
        ]

        merged = merge_candidates(
            rows,
            exclude_urls=("https://www.booking.com/hotel/gr/excluded.en-gb.html?old=1",),
            max_total=2,
        )

        self.assertEqual([row.name for row in merged], ["First", "Second"])

    def test_merge_candidate_rows_keeps_existing_first_and_appends_new(self) -> None:
        existing = [
            {
                "name": "Subject",
                "url": "https://www.booking.com/hotel/gr/subject.en-gb.html?checkin=old",
            },
            {
                "name": "Existing Duplicate",
                "url": "https://www.booking.com/hotel/gr/subject.en-gb.html#details",
            },
        ]
        candidates = [
            {
                "name": "Subject From CSV",
                "url": "https://www.booking.com/hotel/gr/subject.en-gb.html",
            },
            {
                "name": "Gerani Villa",
                "url": "https://www.booking.com/hotel/gr/gerani-villa.en-gb.html?label=abc",
            },
            {"name": "", "url": "https://www.booking.com/hotel/gr/missing-name.en-gb.html"},
            {"name": "Missing URL", "url": ""},
            {
                "name": "Gerani Villa Duplicate",
                "url": "https://www.booking.com/hotel/gr/gerani-villa.en-gb.html#map",
            },
        ]

        merged, added_count = merge_candidate_rows(existing, candidates)

        self.assertEqual(added_count, 1)
        self.assertEqual(
            merged,
            [
                {
                    "name": "Subject",
                    "url": "https://www.booking.com/hotel/gr/subject.en-gb.html",
                },
                {
                    "name": "Gerani Villa",
                    "url": "https://www.booking.com/hotel/gr/gerani-villa.en-gb.html",
                },
            ],
        )

    def test_build_merged_config_preserves_non_property_settings(self) -> None:
        baseline = {
            "seed": 10001,
            "lead_times": [1, 7, 14, 30, 60],
            "browser": {"headless": False, "slow_mo_ms": 75},
            "properties": [
                {
                    "name": "Subject",
                    "url": "https://www.booking.com/hotel/gr/subject.en-gb.html",
                }
            ],
        }

        merged_config, added_count = build_merged_config(
            baseline,
            [
                {
                    "name": "New Property",
                    "url": "https://www.booking.com/hotel/gr/new-property.en-gb.html?x=1",
                }
            ],
        )

        self.assertEqual(added_count, 1)
        self.assertEqual(merged_config["seed"], 10001)
        self.assertEqual(merged_config["lead_times"], [1, 7, 14, 30, 60])
        self.assertEqual(merged_config["browser"], {"headless": False, "slow_mo_ms": 75})
        self.assertEqual(
            merged_config["properties"][-1],
            {
                "name": "New Property",
                "url": "https://www.booking.com/hotel/gr/new-property.en-gb.html",
            },
        )

    def test_full_config_generation_preserves_baseline_targets(self) -> None:
        baseline = {
            "seed": 10001,
            "lead_times": [1, 7, 14, 30, 60],
            "stay_lengths": [4, 7, 14],
            "browser": {"headless": False, "slow_mo_ms": 75},
            "properties": [
                {
                    "name": "Client Subject",
                    "url": "https://www.booking.com/hotel/gr/client.en-gb.html?old=1",
                }
            ],
        }
        candidates = [
            {
                "name": "Client From Discovery",
                "url": "https://www.booking.com/hotel/gr/client.en-gb.html#rooms",
            },
            {
                "name": "New Chania Property",
                "url": "https://www.booking.com/hotel/gr/new-chania.en-gb.html?label=abc",
            },
        ]

        full_config = build_full_config(baseline, candidates)

        self.assertEqual(full_config["lead_times"], [7, 30, 60])
        self.assertEqual(full_config["stay_lengths"], [4, 7])
        self.assertEqual(full_config["browser"], {"headless": True, "slow_mo_ms": 0})
        self.assertEqual(
            full_config["properties"],
            [
                {
                    "name": "Client Subject",
                    "url": "https://www.booking.com/hotel/gr/client.en-gb.html",
                },
                {
                    "name": "New Chania Property",
                    "url": "https://www.booking.com/hotel/gr/new-chania.en-gb.html",
                },
            ],
        )


if __name__ == "__main__":
    unittest.main()
