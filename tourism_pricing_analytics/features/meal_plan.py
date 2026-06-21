"""Meal-plan derivation from a price row's free-text conditions.

Maps the raw ``conditions_text`` of a rate row to a coarse, ordered meal-plan
label. The ordinal encodes inclusiveness (room only < breakfast < half board <
full board < all inclusive) so it can feed a regression directly. Matching is
case-insensitive and most-inclusive-first; an unrecognised text falls back to
the ``room_only`` baseline (ordinal 0), never a failure.
"""


# Ordered most inclusive first so "all inclusive" wins over a contained
# "breakfast" mention, and "full board" / "half board" win over plain breakfast.
_MEAL_PLANS = (
    ("all_inclusive", ("all inclusive", "all-inclusive")),
    ("full_board", ("full board",)),
    ("half_board", ("half board",)),
    ("breakfast", ("breakfast",)),
)

MEAL_PLAN_ORDINALS = {
    "room_only": 0,
    "breakfast": 1,
    "half_board": 2,
    "full_board": 3,
    "all_inclusive": 4,
}


def meal_plan_features(conditions_text: str | None) -> dict:
    """Return ``meal_plan`` label and ``meal_plan_ordinal`` for a conditions text."""

    text = (conditions_text or "").lower()
    for label, needles in _MEAL_PLANS:
        if any(needle in text for needle in needles):
            return {"meal_plan": label, "meal_plan_ordinal": MEAL_PLAN_ORDINALS[label]}
    return {"meal_plan": "room_only", "meal_plan_ordinal": MEAL_PLAN_ORDINALS["room_only"]}
