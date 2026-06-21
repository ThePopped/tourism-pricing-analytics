"""Browser-free encoders for the modelling table.

Encoding lives here, not in the scraper, so the amenity vocabulary is fit across
the *entire* persisted dataset: scraping a new property can grow the vocabulary
without changing any raw scrape artifact. Unseen values at transform time are
ignored rather than erroring, keeping the encoders robust to amenity drift and
localization.
"""

from collections.abc import Iterable


def normalize_amenity(value: str) -> str:
    """Lower-case and collapse internal whitespace so variants align in the vocab."""

    return " ".join(value.split()).lower()


def build_amenity_vocabulary(amenity_lists: Iterable[Iterable[str]]) -> list[str]:
    """Return the sorted unique set of normalized amenities across all rooms."""

    vocab: set[str] = set()
    for amenities in amenity_lists:
        for amenity in amenities or ():
            normalized = normalize_amenity(amenity)
            if normalized:
                vocab.add(normalized)
    return sorted(vocab)


def multi_hot(values: Iterable[str], vocabulary: list[str]) -> list[int]:
    """Encode ``values`` as a 0/1 vector aligned to ``vocabulary``.

    Values absent from the vocabulary are ignored (no error, no extra dimension),
    so a transform never fails on drift between fit and transform sets.
    """

    present = {normalize_amenity(value) for value in (values or ()) if value}
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
