import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from tourism_pricing_analytics.scraping.booking.failures import PageFailureClassification
from tourism_pricing_analytics.scraping.booking.models import (
    BrowserConfig,
    DefaultSearchConfig,
    PriceRowRecord,
    PropertyTarget,
    RetryConfig,
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

    def wait_for_timeout(self, _delay_ms: int) -> None:
        return None


def _scraper_config(target: PropertyTarget, *, retry: RetryConfig | None = None) -> ScraperConfig:
    return ScraperConfig(
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
        retry=retry or RetryConfig(
            max_attempts=3,
            base_backoff_ms=0,
            max_backoff_ms=0,
            jitter_ms=0,
        ),
    )


def _price_row(target: PropertyTarget) -> PriceRowRecord:
    return PriceRowRecord(
        property_name=target.name,
        property_url=target.url,
        checkin="2026-06-21",
        checkout="2026-06-25",
        lead_time_days=1,
        stay_length_days=4,
        room_id="12345601",
        room_name="Double Room",
        block_id="12345601_1_0_0",
        occupancy_text=None,
        conditions_text=None,
        scarcity_text=None,
        current_price_text="EUR 400",
        original_price_text=None,
        current_price_value=400.0,
        original_price_value=None,
        price_per_night=100.0,
        quantity_options=["0", "1"],
        captured_at="2026-06-22T12:00:00",
    )


class RunnerFailureRecordingTests(unittest.TestCase):
    def test_price_loop_records_extraction_exception_details(self) -> None:
        target = PropertyTarget(
            name="Example Hotel",
            url="https://www.booking.com/hotel/gr/example.en-gb.html",
        )
        scraper_config = _scraper_config(target)
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
            patch(
                "tourism_pricing_analytics.scraping.booking.runner.append_property_failures",
            ),
        ):
            with self.assertLogs(level="ERROR"):
                _ctx, _, price_rows, _room_features, failures = run_price_loop(
                    browser=object(),
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

    def test_price_loop_retries_transient_failure_and_records_success(self) -> None:
        target = PropertyTarget(
            name="Example Hotel",
            url="https://www.booking.com/hotel/gr/example.en-gb.html",
        )
        scraper_config = _scraper_config(
            target,
            retry=RetryConfig(
                max_attempts=2,
                base_backoff_ms=0,
                max_backoff_ms=0,
                jitter_ms=0,
            ),
        )
        page = FakePage()
        row = _price_row(target)

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
                side_effect=[RuntimeError("temporary navigation"), 200],
            ) as navigate,
            patch(
                "tourism_pricing_analytics.scraping.booking.runner.classify_current_page_failure",
                return_value=PageFailureClassification(
                    category="navigation_error",
                    reason="Synthetic navigation failure.",
                ),
            ),
            patch(
                "tourism_pricing_analytics.scraping.booking.runner.extract_price_rows",
                return_value=[row],
            ),
            patch(
                "tourism_pricing_analytics.scraping.booking.runner.extract_room_features",
                return_value=[],
            ),
            patch(
                "tourism_pricing_analytics.scraping.booking.runner.save_property_price_rows",
            ),
            patch(
                "tourism_pricing_analytics.scraping.booking.runner.append_property_failures",
            ) as append_failures,
            patch(
                "tourism_pricing_analytics.scraping.booking.runner.save_failure_snapshot",
            ) as save_snapshot,
        ):
            _ctx, _, price_rows, _room_features, failures = run_price_loop(
                browser=object(),
                context=object(),
                page=page,
                scraper_config=scraper_config,
                property_output_dirs={target.url: Path("saved_dom/example")},
            )

        self.assertEqual(navigate.call_count, 2)
        self.assertEqual(price_rows, [row])
        self.assertEqual(failures, [])
        append_failures.assert_not_called()
        save_snapshot.assert_not_called()

    def test_empty_availability_failure_does_not_save_snapshot(self) -> None:
        target = PropertyTarget(
            name="Example Hotel",
            url="https://www.booking.com/hotel/gr/example.en-gb.html",
        )
        scraper_config = _scraper_config(
            target,
            retry=RetryConfig(
                max_attempts=1,
                base_backoff_ms=0,
                max_backoff_ms=0,
                jitter_ms=0,
            ),
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
                return_value=200,
            ),
            patch(
                "tourism_pricing_analytics.scraping.booking.runner.extract_price_rows",
                return_value=[],
            ),
            patch(
                "tourism_pricing_analytics.scraping.booking.runner.classify_current_page_failure",
                return_value=PageFailureClassification(
                    category="empty_availability",
                    reason="Synthetic no availability.",
                ),
            ),
            patch(
                "tourism_pricing_analytics.scraping.booking.runner.save_failure_snapshot",
            ) as save_snapshot,
            patch(
                "tourism_pricing_analytics.scraping.booking.runner.append_property_failures",
            ),
        ):
            _ctx, _, price_rows, _room_features, failures = run_price_loop(
                browser=object(),
                context=object(),
                page=page,
                scraper_config=scraper_config,
                property_output_dirs={target.url: Path("saved_dom/example")},
            )

        self.assertEqual(price_rows, [])
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].category, "empty_availability")
        self.assertIsNone(failures[0].snapshot_filename)
        save_snapshot.assert_not_called()


if __name__ == "__main__":
    unittest.main()
