import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from tourism_pricing_analytics.scraping.booking.failures import PageFailureClassification
from tourism_pricing_analytics.scraping.booking.models import (
    BrowserConfig,
    DefaultSearchConfig,
    PropertyTarget,
    ScraperConfig,
    ScrollConfig,
    TimeoutConfig,
    ViewportConfig,
)
from tourism_pricing_analytics.scraping.booking.runner import run_price_loop


class FakePage:
    url = "https://www.booking.com/hotel/gr/example.en-gb.html"

    def is_closed(self) -> bool:
        return False


class RunnerFailureRecordingTests(unittest.TestCase):
    def test_price_loop_records_extraction_exception_details(self) -> None:
        target = PropertyTarget(
            name="Example Hotel",
            url="https://www.booking.com/hotel/gr/example.en-gb.html",
        )
        scraper_config = ScraperConfig(
            seed=10001,
            output_root=Path("saved_dom"),
            lead_times=[1],
            stay_lengths=[4],
            browser=BrowserConfig(
                headless=True,
                slow_mo_ms=0,
                user_agent="test",
                viewport=ViewportConfig(width=1280, height=900),
            ),
            default_search=DefaultSearchConfig(
                group_adults=2,
                group_children=0,
                no_rooms=1,
            ),
            timeouts=TimeoutConfig(
                opened_scan_wait_ms=0,
                final_wait_ms=0,
            ),
            scroll=ScrollConfig(
                rounds=0,
                min_delta=0,
                max_delta=0,
            ),
            common_opened_selectors=[],
            properties=[target],
        )
        page = FakePage()

        with (
            patch(
                "tourism_pricing_analytics.scraping.booking.runner.build_date_window",
                return_value=(date(2026, 6, 21), date(2026, 6, 25)),
            ),
            patch(
                "tourism_pricing_analytics.scraping.booking.runner.ensure_page",
                return_value=page,
            ),
            patch(
                "tourism_pricing_analytics.scraping.booking.runner.navigate_to_page",
                side_effect=RuntimeError("synthetic extraction failure"),
            ),
            patch(
                "tourism_pricing_analytics.scraping.booking.runner.classify_current_page_failure",
                return_value=PageFailureClassification(
                    category="navigation_error",
                    reason="Synthetic navigation failure.",
                ),
            ),
            patch(
                "tourism_pricing_analytics.scraping.booking.runner.save_failure_snapshot",
                return_value="price_rows_navigation_error_lead_001_stay_004.html",
            ),
        ):
            with self.assertLogs(level="ERROR"):
                _, price_rows, _room_features, failures = run_price_loop(
                    context=object(),
                    page=page,
                    scraper_config=scraper_config,
                    property_output_dirs={target.url: Path("saved_dom/example")},
                )

        self.assertEqual(price_rows, [])
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].category, "navigation_error")
        self.assertEqual(failures[0].exception_type, "RuntimeError")
        self.assertEqual(
            failures[0].exception_message,
            "synthetic extraction failure",
        )


if __name__ == "__main__":
    unittest.main()
