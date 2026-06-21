"""Cancellation-flexibility flags from a price row's free-text conditions.

Parses ``conditions_text`` into booleans plus a coarse ordinal: non-refundable
(0) is less flexible than free cancellation (1). An unrecognised text leaves
both flags False and the ordinal null, treating flexibility as unknown rather
than guessing. Matching is case-insensitive and tolerant of the hyphen variants
Booking uses across layouts.
"""


def cancellation_features(conditions_text: str | None) -> dict:
    """Return cancellation flexibility flags and ordinal for a conditions text."""

    text = (conditions_text or "").lower()
    free_cancellation = "free cancellation" in text
    non_refundable = "non-refundable" in text or "non refundable" in text

    if free_cancellation:
        ordinal: int | None = 1
    elif non_refundable:
        ordinal = 0
    else:
        ordinal = None

    return {
        "free_cancellation": free_cancellation,
        "non_refundable": non_refundable,
        "cancellation_flexibility_ordinal": ordinal,
    }
