import unittest

from tourism_pricing_analytics.scraping.booking.memory_probe import (
    MemoryThresholds,
    is_memory_low,
)


GIB = 1024**3

THRESHOLDS = MemoryThresholds(
    available_floor_bytes=2 * GIB,
    nonpaged_delta_bytes=1 * GIB,
)


class IsMemoryLowTests(unittest.TestCase):
    def test_healthy_memory_is_not_low(self) -> None:
        self.assertFalse(
            is_memory_low(
                available_bytes=6 * GIB,
                nonpaged_bytes=1 * GIB,
                baseline_nonpaged=1 * GIB,
                thresholds=THRESHOLDS,
            )
        )

    def test_available_below_floor_is_low(self) -> None:
        self.assertTrue(
            is_memory_low(
                available_bytes=2 * GIB - 1,
                nonpaged_bytes=1 * GIB,
                baseline_nonpaged=1 * GIB,
                thresholds=THRESHOLDS,
            )
        )

    def test_available_exactly_at_floor_is_not_low(self) -> None:
        self.assertFalse(
            is_memory_low(
                available_bytes=2 * GIB,
                nonpaged_bytes=1 * GIB,
                baseline_nonpaged=1 * GIB,
                thresholds=THRESHOLDS,
            )
        )

    def test_nonpaged_growth_over_delta_is_low(self) -> None:
        self.assertTrue(
            is_memory_low(
                available_bytes=6 * GIB,
                nonpaged_bytes=2 * GIB + 1,
                baseline_nonpaged=1 * GIB,
                thresholds=THRESHOLDS,
            )
        )

    def test_nonpaged_growth_exactly_at_delta_is_not_low(self) -> None:
        self.assertFalse(
            is_memory_low(
                available_bytes=6 * GIB,
                nonpaged_bytes=2 * GIB,
                baseline_nonpaged=1 * GIB,
                thresholds=THRESHOLDS,
            )
        )

    def test_nonpaged_shrink_below_baseline_is_not_low(self) -> None:
        self.assertFalse(
            is_memory_low(
                available_bytes=6 * GIB,
                nonpaged_bytes=GIB // 2,
                baseline_nonpaged=1 * GIB,
                thresholds=THRESHOLDS,
            )
        )

    def test_default_thresholds_reflect_scrape_host_limits(self) -> None:
        defaults = MemoryThresholds()

        self.assertEqual(defaults.available_floor_bytes, 2 * GIB)
        self.assertEqual(defaults.nonpaged_delta_bytes, int(1.25 * GIB))


if __name__ == "__main__":
    unittest.main()
