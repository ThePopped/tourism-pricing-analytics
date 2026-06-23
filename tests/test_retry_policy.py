import random
import unittest

from tourism_pricing_analytics.scraping.booking.retry import (
    RETRYABLE_FAILURE_CATEGORIES,
    backoff_delay_ms,
    should_retry,
)


class RetryPolicyTests(unittest.TestCase):
    def test_retries_transient_categories_before_max_attempts(self) -> None:
        for category in RETRYABLE_FAILURE_CATEGORIES:
            with self.subTest(category=category):
                self.assertTrue(
                    should_retry(category, attempt=1, max_attempts=3)
                )

    def test_does_not_retry_transient_category_at_max_attempts(self) -> None:
        self.assertFalse(
            should_retry("navigation_error", attempt=3, max_attempts=3)
        )

    def test_does_not_retry_terminal_categories(self) -> None:
        for category in ["empty_availability", "selector_drift", "redirect"]:
            with self.subTest(category=category):
                self.assertFalse(
                    should_retry(category, attempt=1, max_attempts=3)
                )

    def test_backoff_is_exponential_with_seeded_jitter(self) -> None:
        rng = random.Random(10001)

        delay = backoff_delay_ms(
            2,
            base_backoff_ms=1000,
            max_backoff_ms=10000,
            jitter_ms=500,
            rng=rng,
        )

        self.assertGreaterEqual(delay, 2000)
        self.assertLessEqual(delay, 2500)

    def test_backoff_is_capped_after_jitter(self) -> None:
        delay = backoff_delay_ms(
            4,
            base_backoff_ms=1000,
            max_backoff_ms=5000,
            jitter_ms=500,
            rng=random.Random(10001),
        )

        self.assertEqual(delay, 5000)

    def test_invalid_attempt_raises(self) -> None:
        with self.assertRaises(ValueError):
            should_retry("navigation_error", attempt=0, max_attempts=3)

        with self.assertRaises(ValueError):
            backoff_delay_ms(
                0,
                base_backoff_ms=1000,
                max_backoff_ms=10000,
                jitter_ms=500,
            )


if __name__ == "__main__":
    unittest.main()
