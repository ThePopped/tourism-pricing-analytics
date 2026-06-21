"""Per-page property feature collection.

Builds a single :class:`PropertyFeatureContext` from the loaded property page,
runs the registered property extractors in isolation, and assembles one
``PropertyFeatureRecord``. Property features are stable across dates and rooms,
so callers run this once per property (on the scrolled undated property page,
where the facilities / subscores / surroundings sections are present).
"""

import logging
from dataclasses import fields

from playwright.sync_api import Page

from tourism_pricing_analytics.scraping.booking.features.base import (
    PropertyFeatureContext,
    run_extractors,
)
from tourism_pricing_analytics.scraping.booking.features.registry import PROPERTY_EXTRACTORS
from tourism_pricing_analytics.scraping.booking.models import PropertyFeatureRecord


_PROPERTY_FEATURE_FIELDS = {field.name for field in fields(PropertyFeatureRecord)}


def extract_property_features(
    page: Page,
    *,
    property_name: str,
    property_url: str,
    captured_at: str,
    extractors=None,
) -> PropertyFeatureRecord:
    extractors = PROPERTY_EXTRACTORS if extractors is None else extractors

    ctx = PropertyFeatureContext(page=page, property_url=property_url)
    merged = run_extractors(extractors, ctx)

    # Drop any unexpected keys so a stray field never aborts record construction;
    # the per-extractor isolation in run_extractors is only useful if the
    # assembly step is equally defensive.
    feature_fields = {
        key: value for key, value in merged.items() if key in _PROPERTY_FEATURE_FIELDS
    }
    unexpected = set(merged) - _PROPERTY_FEATURE_FIELDS
    if unexpected:
        logging.warning("Ignoring unexpected property feature keys: %s", sorted(unexpected))

    return PropertyFeatureRecord(
        property_name=property_name,
        property_url=property_url,
        captured_at=captured_at,
        **feature_fields,
    )
