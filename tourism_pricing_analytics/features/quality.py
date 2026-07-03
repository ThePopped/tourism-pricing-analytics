"""Curated high-value amenity / property-quality binaries for the hedonic model.

The generic amenity/facility multi-hot in :mod:`hedonic` is frequency-floored:
tokens rarer than ``min_token_frequency`` never become columns, so genuinely
valuable-but-uncommon signals (a private hot tub, beachfront position) get
dropped, while the pricing-relevant ones that *are* common sit diluted inside a
few hundred lookalike columns. This module adds a small, hand-curated set of
``hq__<feature>`` binaries that are evaluated **independently of the frequency
floor** -- a guest paying a premium cares whether there is a pool, sea view, or
kitchen far more than which of 300 tokens happen to clear a count threshold.

Matching is done with word boundaries against the already-normalized amenity and
facility tokens (see :func:`hedonic._tokens_from_value`), so ``kitchen`` matches
"kitchen"/"private kitchen" but not "kitchenware", and ``kitchenette`` is listed
explicitly. Each feature fires if *any* of its keyword patterns is present in the
row's combined amenity+facility token set.
"""

from __future__ import annotations

import re
from typing import Iterable, Mapping

# Curated feature name -> keyword phrases (matched as whole words / phrases). A
# feature is 1 when any phrase appears in the row's normalized token set. Keep
# the phrases lower-case; tokens are normalized to lower-case upstream.
CURATED_QUALITY_FEATURES: Mapping[str, tuple[str, ...]] = {
    "pool": ("pool",),
    "sea_view": ("sea view", "ocean view"),
    "beachfront": ("beachfront", "private beach"),
    "balcony_or_terrace": ("balcony", "terrace", "patio"),
    "parking": ("parking",),
    "kitchen": ("kitchen", "kitchenette"),
    "washing_machine": ("washing machine",),
    "private_entrance": ("private entrance",),
    "air_conditioning": ("air conditioning", "air conditioner"),
    "hot_tub": ("hot tub", "jacuzzi"),
    "garden": ("garden",),
}

# Design-matrix column names in a stable order.
QUALITY_FEATURE_COLUMNS: tuple[str, ...] = tuple(
    f"hq__{name}" for name in CURATED_QUALITY_FEATURES
)


def _compile(keywords: tuple[str, ...]) -> "re.Pattern[str]":
    return re.compile(r"|".join(rf"\b{re.escape(word)}\b" for word in keywords))


_COMPILED: dict[str, "re.Pattern[str]"] = {
    name: _compile(keywords) for name, keywords in CURATED_QUALITY_FEATURES.items()
}


def quality_flags(tokens: Iterable[str]) -> dict[str, int]:
    """Map one row's normalized amenity/facility tokens to ``hq__`` binaries.

    Tokens are joined with a non-word delimiter so word-boundary phrase matches
    stay contained within a single token (a "private" token beside an "entrance"
    token never spuriously matches the "private entrance" phrase).
    """

    joined = " | ".join(tokens)
    return {
        f"hq__{name}": int(bool(pattern.search(joined)))
        for name, pattern in _COMPILED.items()
    }
