"""Unit tests for the memory-reduction helpers in the browser layer."""

import unittest
from unittest.mock import MagicMock

from tourism_pricing_analytics.scraping.booking.browser import (
    BLOCKED_RESOURCE_TYPES,
    CONTEXT_RECYCLE_EVERY_N_PROPERTIES,
    MEMORY_SAVING_BROWSER_ARGS,
    PRICE_CONTEXT_RECYCLE_EVERY_N_PROPERTIES,
    block_heavy_resources,
    new_scraper_context,
    recycle_context,
    should_block_resource,
    should_recycle_context,
)


class ShouldBlockResourceTests(unittest.TestCase):
    def test_blocks_heavy_resource_types(self):
        for resource_type in ("image", "media", "font"):
            self.assertTrue(should_block_resource(resource_type))

    def test_keeps_data_bearing_resource_types(self):
        # Prices, room/property text and layout must still load.
        for resource_type in ("document", "xhr", "fetch", "stylesheet", "script"):
            self.assertFalse(should_block_resource(resource_type))

    def test_blocked_set_excludes_stylesheets(self):
        # Visibility checks and scroll-into-view depend on CSS layout.
        self.assertNotIn("stylesheet", BLOCKED_RESOURCE_TYPES)


class BlockHeavyResourcesTests(unittest.TestCase):
    def _run_route(self, resource_type: str):
        context = MagicMock()
        block_heavy_resources(context)
        # The handler is registered against every URL on the context.
        args, _ = context.route.call_args
        self.assertEqual(args[0], "**/*")
        handler = args[1]

        route = MagicMock()
        route.request.resource_type = resource_type
        handler(route)
        return route

    def test_aborts_images(self):
        route = self._run_route("image")
        route.abort.assert_called_once()
        route.continue_.assert_not_called()

    def test_continues_documents(self):
        route = self._run_route("document")
        route.continue_.assert_called_once()
        route.abort.assert_not_called()


class MemorySavingArgsTests(unittest.TestCase):
    def test_includes_dev_shm_and_heap_caps(self):
        self.assertIn("--disable-dev-shm-usage", MEMORY_SAVING_BROWSER_ARGS)
        self.assertTrue(
            any(arg.startswith("--js-flags=") for arg in MEMORY_SAVING_BROWSER_ARGS)
        )


class ShouldRecycleContextTests(unittest.TestCase):
    def test_skips_first_property(self):
        # The caller supplies a fresh context for property 0.
        self.assertFalse(should_recycle_context(0, 10))

    def test_recycles_on_every_nth_boundary(self):
        self.assertTrue(should_recycle_context(10, 10))
        self.assertTrue(should_recycle_context(20, 10))

    def test_does_not_recycle_between_boundaries(self):
        for index in (1, 5, 9, 11, 19):
            self.assertFalse(should_recycle_context(index, 10))

    def test_disabled_when_recycle_every_non_positive(self):
        for recycle_every in (0, -1):
            self.assertFalse(should_recycle_context(10, recycle_every))

    def test_default_cadence_is_positive(self):
        self.assertGreater(CONTEXT_RECYCLE_EVERY_N_PROPERTIES, 0)

    def test_price_phase_recycles_at_least_as_often(self):
        # The price phase does ~15 navigations per property vs ~1 for room
        # inventory, so it must recycle at least as frequently to bound RSS.
        self.assertGreater(PRICE_CONTEXT_RECYCLE_EVERY_N_PROPERTIES, 0)
        self.assertLessEqual(
            PRICE_CONTEXT_RECYCLE_EVERY_N_PROPERTIES,
            CONTEXT_RECYCLE_EVERY_N_PROPERTIES,
        )


class NewScraperContextTests(unittest.TestCase):
    def _config(self):
        config = MagicMock()
        config.browser.user_agent = "ua"
        config.browser.viewport.width = 1280
        config.browser.viewport.height = 800
        return config

    def test_applies_resource_blocking_route(self):
        browser = MagicMock()
        context = browser.new_context.return_value

        result = new_scraper_context(browser, self._config())

        self.assertIs(result, context)
        # block_heavy_resources registers the abort route on the new context.
        args, _ = context.route.call_args
        self.assertEqual(args[0], "**/*")


class RecycleContextTests(unittest.TestCase):
    def _config(self):
        config = MagicMock()
        config.browser.user_agent = "ua"
        config.browser.viewport.width = 1280
        config.browser.viewport.height = 800
        return config

    def test_closes_old_context_and_returns_fresh_context_and_page(self):
        browser = MagicMock()
        new_context = browser.new_context.return_value
        old_context = MagicMock()

        result_context, result_page = recycle_context(browser, old_context, self._config())

        old_context.close.assert_called_once()
        self.assertIs(result_context, new_context)
        self.assertIs(result_page, new_context.new_page.return_value)

    def test_close_failure_is_swallowed(self):
        browser = MagicMock()
        old_context = MagicMock()
        old_context.close.side_effect = RuntimeError("already closed")

        # A teardown error must not abort the scrape; a fresh context is returned.
        result_context, _ = recycle_context(browser, old_context, self._config())
        self.assertIs(result_context, browser.new_context.return_value)


if __name__ == "__main__":
    unittest.main()
