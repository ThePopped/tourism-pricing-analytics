"""Extractor protocols, contexts, and the isolated extractor runner.

A feature extractor is a small object with a ``name`` and an ``extract(ctx)``
method returning a ``dict`` of field values to merge into the corresponding
record. Extractors are run through :func:`run_extractors`, which isolates each
one so a brittle selector becomes a per-feature miss rather than a row/run abort.

Hooking a new feature is: write one extractor here (or under ``room/`` /
``property/``), append it to the relevant list in ``registry.py``, and add a
fixture regression test. Nothing in the runner loop needs to change.
"""

import logging
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from playwright.sync_api import Locator, Page


@dataclass(frozen=True)
class RoomFeatureContext:
    """Inputs for a room-scope extractor: the room-type table cell plus identity."""

    room_cell: Locator
    property_url: str
    room_id: str | None


@dataclass(frozen=True)
class PropertyFeatureContext:
    """Inputs for a property-scope extractor: the loaded page plus identity."""

    page: Page
    property_url: str


@runtime_checkable
class FeatureExtractor(Protocol):
    """A named extractor that maps a context to a dict of record fields."""

    name: str

    def extract(self, ctx: object) -> dict: ...


def run_extractors(extractors: list[FeatureExtractor], ctx: object) -> dict:
    """Run every extractor against ``ctx`` and merge their outputs.

    Each extractor is isolated: an exception is logged and skipped so one failing
    extractor never aborts the others, the row, or the run. Extractors that return
    a falsy value contribute nothing. Later extractors override earlier keys.
    """

    merged: dict = {}
    for extractor in extractors:
        name = getattr(extractor, "name", repr(extractor))
        try:
            result = extractor.extract(ctx)
        except Exception:
            logging.exception("Feature extractor %r failed", name)
            continue
        if result:
            merged.update(result)
    return merged
