import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from config import CONFIG_DIR, ROOT
from tourism_pricing_analytics.scraping.booking.config import load_scraper_config
from tourism_pricing_analytics.scraping.booking.models import DefaultSearchConfig
from tourism_pricing_analytics.scraping.booking.urls import (
    build_date_window,
    build_dated_url,
    build_property_url,
    build_room_inventory_url,
    canonicalize_property_url,
)


class ScraperConfigAndUrlTests(unittest.TestCase):
    def test_load_scraper_config_resolves_relative_output_under_repo(self) -> None:
        scraper_config = load_scraper_config()

        self.assertTrue(scraper_config.properties)
        self.assertTrue(scraper_config.output_root.is_absolute())
        self.assertEqual(scraper_config.output_root, ROOT / "saved_dom")
        self.assertEqual(scraper_config.seed, 10001)

    def test_load_scraper_config_reads_expected_search_settings(self) -> None:
        scraper_config = load_scraper_config()

        self.assertEqual(scraper_config.default_search.group_adults, 2)
        self.assertEqual(scraper_config.default_search.group_children, 0)
        self.assertEqual(scraper_config.default_search.no_rooms, 1)
        self.assertEqual(scraper_config.lead_times, [1, 7, 14, 30, 60])
        self.assertEqual(scraper_config.stay_lengths, [4, 7, 14])

    def test_load_scraper_config_reads_post_nav_pause(self) -> None:
        scraper_config = load_scraper_config()

        self.assertEqual(scraper_config.pauses.post_nav_min_ms, 300)
        self.assertEqual(scraper_config.pauses.post_nav_max_ms, 800)
        self.assertLessEqual(
            scraper_config.pauses.post_nav_min_ms,
            scraper_config.pauses.post_nav_max_ms,
        )

    def test_load_scraper_config_reads_retry_policy(self) -> None:
        scraper_config = load_scraper_config()

        self.assertEqual(scraper_config.retry.max_attempts, 3)
        self.assertEqual(scraper_config.retry.base_backoff_ms, 1000)
        self.assertEqual(scraper_config.retry.max_backoff_ms, 10000)
        self.assertEqual(scraper_config.retry.jitter_ms, 500)

    def test_full_chania_config_uses_scale_up_matrix_and_speed_settings(self) -> None:
        scraper_config = load_scraper_config(
            CONFIG_DIR / "booking_scraper_config_chania_full.json"
        )

        self.assertGreaterEqual(len(scraper_config.properties), 438)
        self.assertEqual(scraper_config.lead_times, [7, 30, 60])
        self.assertEqual(scraper_config.stay_lengths, [4, 7])
        self.assertTrue(scraper_config.browser.headless)
        self.assertEqual(scraper_config.browser.slow_mo_ms, 0)
        self.assertEqual(scraper_config.retry.max_attempts, 3)
        self.assertEqual(scraper_config.seed, 10001)
        self.assertEqual(scraper_config.output_root, ROOT / "saved_dom")

        urls = [target.url for target in scraper_config.properties]
        self.assertIn(
            "https://www.booking.com/hotel/gr/stavros-villas-amp-apartments.en-gb.html",
            urls,
        )
        self.assertEqual(len(urls), len(set(urls)))
        for url in urls:
            self.assertNotIn("?", url)
            self.assertTrue(url.startswith("https://www.booking.com/hotel/"))

    def test_load_scraper_config_defaults_pause_when_section_absent(self) -> None:
        raw = json.loads(
            (CONFIG_DIR / "booking_scraper_config.json").read_text(encoding="utf-8")
        )
        raw.pop("pauses", None)
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "no_pauses.json"
            config_path.write_text(json.dumps(raw), encoding="utf-8")
            scraper_config = load_scraper_config(config_path)

        self.assertEqual(scraper_config.pauses.post_nav_min_ms, 300)
        self.assertEqual(scraper_config.pauses.post_nav_max_ms, 800)

    def test_load_scraper_config_defaults_retry_when_section_absent(self) -> None:
        raw = json.loads(
            (CONFIG_DIR / "booking_scraper_config.json").read_text(encoding="utf-8")
        )
        raw.pop("retry", None)
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "no_retry.json"
            config_path.write_text(json.dumps(raw), encoding="utf-8")
            scraper_config = load_scraper_config(config_path)

        self.assertEqual(scraper_config.retry.max_attempts, 3)
        self.assertEqual(scraper_config.retry.base_backoff_ms, 1000)
        self.assertEqual(scraper_config.retry.max_backoff_ms, 10000)
        self.assertEqual(scraper_config.retry.jitter_ms, 500)

    def test_build_date_window_uses_fixed_base_date_offsets(self) -> None:
        checkin, checkout = build_date_window(
            lead_time_days=14,
            stay_length_days=7,
            base_date=date(2026, 6, 20),
        )

        self.assertEqual(checkin, date(2026, 7, 4))
        self.assertEqual(checkout, date(2026, 7, 11))

    def test_canonicalize_property_url_removes_query_and_fragment(self) -> None:
        canonical_url = canonicalize_property_url(
            "https://www.booking.com/hotel/gr/example.en-gb.html?checkin=2026-07-04#availability"
        )

        self.assertEqual(
            canonical_url,
            "https://www.booking.com/hotel/gr/example.en-gb.html",
        )

    def test_build_room_inventory_url_uses_canonical_property_url(self) -> None:
        inventory_url = build_room_inventory_url(
            "https://www.booking.com/hotel/gr/example.en-gb.html?checkin=2026-07-04"
        )

        self.assertEqual(
            inventory_url,
            "https://www.booking.com/hotel/gr/example.en-gb.html",
        )

    def test_build_property_url_adds_updates_and_removes_query_params(self) -> None:
        property_url = build_property_url(
            "https://www.booking.com/hotel/gr/example.en-gb.html?checkin=old&keep=yes&remove=1",
            params={
                "checkin": "2026-07-04",
                "checkout": "2026-07-11",
                "remove": None,
            },
        )
        parsed_url = urlsplit(property_url)
        query_params = parse_qs(parsed_url.query)

        self.assertEqual(parsed_url.scheme, "https")
        self.assertEqual(parsed_url.netloc, "www.booking.com")
        self.assertEqual(parsed_url.path, "/hotel/gr/example.en-gb.html")
        self.assertEqual(query_params["checkin"], ["2026-07-04"])
        self.assertEqual(query_params["checkout"], ["2026-07-11"])
        self.assertEqual(query_params["keep"], ["yes"])
        self.assertNotIn("remove", query_params)

    def test_build_dated_url_sets_expected_search_params(self) -> None:
        dated_url = build_dated_url(
            "https://www.booking.com/hotel/gr/example.en-gb.html?old_param=ignored",
            checkin=date(2026, 7, 4),
            checkout=date(2026, 7, 11),
            default_search=DefaultSearchConfig(
                group_adults=2,
                group_children=0,
                no_rooms=1,
            ),
        )
        parsed_url = urlsplit(dated_url)
        query_params = parse_qs(parsed_url.query)

        self.assertEqual(
            f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}",
            "https://www.booking.com/hotel/gr/example.en-gb.html",
        )
        self.assertEqual(query_params["checkin"], ["2026-07-04"])
        self.assertEqual(query_params["checkout"], ["2026-07-11"])
        self.assertEqual(query_params["group_adults"], ["2"])
        self.assertEqual(query_params["group_children"], ["0"])
        self.assertEqual(query_params["no_rooms"], ["1"])
        self.assertNotIn("old_param", query_params)


if __name__ == "__main__":
    unittest.main()
