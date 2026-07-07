"""Browser-free encoders for the modelling table.

Encoding lives here, not in the scraper, so the amenity vocabulary is fit across
the *entire* persisted dataset: scraping a new property can grow the vocabulary
without changing any raw scrape artifact. Unseen values at transform time are
ignored rather than erroring, keeping the encoders robust to amenity drift and
localization.
"""

import re
from collections.abc import Iterable


# A room-size measurement such as "25 m²" (U+00B2) or the "25 m2" fallback form.
# Booking exposes room size only as one of the room's facility rows, so it lands
# in the raw amenity list alongside real amenities. It is extracted separately
# into ``room_size_sqm`` and must not leak into the amenity vocabulary, where it
# would become a sparse, high-cardinality one-hot bucket redundant with the
# numeric size feature.
_ROOM_SIZE_TOKEN_RE = re.compile(r"^\d+(?:[.,]\d+)?\s*m(?:²|2)$", re.IGNORECASE)


def normalize_amenity(value: str) -> str:
    """Lower-case and collapse internal whitespace so variants align in the vocab."""

    return " ".join(value.split()).lower()


def is_room_size_token(value: str) -> bool:
    """True if ``value`` is purely a room-size measurement (e.g. ``25 m²``).

    Only matches tokens that are *entirely* a size measurement, so real
    amenities that merely mention a distance (``Extra long beds (> 2 metres)``)
    are preserved.
    """

    return bool(_ROOM_SIZE_TOKEN_RE.match(normalize_amenity(value)))


def build_amenity_vocabulary(amenity_lists: Iterable[Iterable[str]]) -> list[str]:
    """Return the sorted unique set of normalized amenities across all rooms."""

    vocab: set[str] = set()
    for amenities in amenity_lists:
        for amenity in amenities or ():
            normalized = normalize_amenity(amenity)
            if normalized and not is_room_size_token(amenity):
                vocab.add(normalized)
    return sorted(vocab)


def multi_hot(values: Iterable[str], vocabulary: list[str]) -> list[int]:
    """Encode ``values`` as a 0/1 vector aligned to ``vocabulary``.

    Values absent from the vocabulary are ignored (no error, no extra dimension),
    so a transform never fails on drift between fit and transform sets.
    """

    present = {
        normalize_amenity(value)
        for value in (values or ())
        if value and not is_room_size_token(value)
    }
    return [1 if term in present else 0 for term in vocabulary]


def ordinal_encode(value, mapping: dict, *, default=None):
    """Map ``value`` through ``mapping``; unknown or null values fall to ``default``."""

    if value is None:
        return default
    return mapping.get(value, default)


def add_amenity_multi_hot(rows: list[dict], *, prefix: str = "amenity__") -> list[str]:
    """Fit an amenity vocabulary across ``rows`` and add multi-hot columns in place.

    Mutates each row, adding one ``{prefix}{term}`` 0/1 column per vocabulary
    term, and returns the fitted vocabulary so callers can record/inspect it.
    Fitting across the whole row set is the point: the vocabulary reflects the
    full dataset, not a single property.
    """

    vocabulary = build_amenity_vocabulary(row.get("amenities") or [] for row in rows)
    for row in rows:
        encoded = multi_hot(row.get("amenities") or [], vocabulary)
        for term, value in zip(vocabulary, encoded):
            row[f"{prefix}{term}"] = value
    return vocabulary
