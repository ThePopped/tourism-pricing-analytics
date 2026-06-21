"""Tier A calendar features derived from a price row's check-in date.

Pure date arithmetic over the ``checkin`` string already present on every price
row, so no scraper change and no browser are needed. Seasonality is a top price
driver for Crete tourism: it is captured here as month / ISO week / day-of-week
plus a coarse peak/shoulder/off season flag. A missing or unparseable date
yields an all-null feature dict rather than raising, so one malformed row never
breaks the build.
"""

from datetime import date


# Crete tourism seasonality (Mediterranean beach season). July-August is the
# undisputed peak; the shoulder months bracket it on either side; the rest of
# the year is the off season.
_PEAK_MONTHS = frozenset({7, 8})
_SHOULDER_MONTHS = frozenset({5, 6, 9, 10})

_NULL_FEATURES = {
    "checkin_month": None,
    "checkin_iso_week": None,
    "checkin_day_of_week": None,
    "checkin_is_weekend": None,
    "crete_season": None,
}


def crete_season(month: int) -> str:
    """Map a month number (1-12) to a coarse Crete season bucket."""

    if month in _PEAK_MONTHS:
        return "peak"
    if month in _SHOULDER_MONTHS:
        return "shoulder"
    return "off"


def parse_checkin(checkin: str | None) -> date | None:
    """Parse an ISO ``YYYY-MM-DD`` check-in string, returning None on failure."""

    if not checkin:
        return None
    try:
        return date.fromisoformat(checkin)
    except (ValueError, TypeError):
        return None


def seasonality_features(checkin: str | None) -> dict:
    """Return calendar features for a check-in date string (``YYYY-MM-DD``)."""

    parsed = parse_checkin(checkin)
    if parsed is None:
        return dict(_NULL_FEATURES)

    _, iso_week, _ = parsed.isocalendar()
    day_of_week = parsed.weekday()  # Monday=0 .. Sunday=6
    return {
        "checkin_month": parsed.month,
        "checkin_iso_week": iso_week,
        "checkin_day_of_week": day_of_week,
        "checkin_is_weekend": day_of_week >= 5,
        "crete_season": crete_season(parsed.month),
    }
