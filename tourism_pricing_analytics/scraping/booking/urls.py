import re
from datetime import date, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from tourism_pricing_analytics.scraping.booking.models import DefaultSearchConfig


def build_property_url(base_url: str, params: dict[str, int | str | None] | None = None) -> str:
    split_url = urlsplit(base_url)
    query_params = dict(parse_qsl(split_url.query, keep_blank_values=True))

    if params:
        for key, value in params.items():
            if value is None:
                query_params.pop(key, None)
            else:
                query_params[key] = str(value)

    return urlunsplit(
        (
            split_url.scheme,
            split_url.netloc,
            split_url.path,
            urlencode(query_params),
            split_url.fragment,
        )
    )


def canonicalize_property_url(base_url: str) -> str:
    split_url = urlsplit(base_url)
    return urlunsplit(
        (
            split_url.scheme,
            split_url.netloc,
            split_url.path,
            "",
            "",
        )
    )


def build_room_inventory_url(base_url: str) -> str:
    return canonicalize_property_url(base_url)


def build_dated_url(
    base_url: str,
    checkin: date,
    checkout: date,
    default_search: DefaultSearchConfig,
) -> str:
    return build_property_url(
        canonicalize_property_url(base_url),
        params={
            "checkin": checkin.isoformat(),
            "checkout": checkout.isoformat(),
            "group_adults": default_search.group_adults,
            "group_children": default_search.group_children,
            "no_rooms": default_search.no_rooms,
        },
    )


def build_date_window(
    lead_time_days: int,
    stay_length_days: int,
    base_date: date | None = None,
) -> tuple[date, date]:
    search_date = base_date or date.today()
    checkin = search_date + timedelta(days=lead_time_days)
    checkout = checkin + timedelta(days=stay_length_days)
    return checkin, checkout


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
