"""House-rules / policy extractor (check-in & check-out times, cancellation).

The policies section renders check-in and check-out as ``From HH:MM to HH:MM``
windows plus a free-text cancellation/prepayment summary. Times are captured as
``HH:MM`` strings; the cancellation summary is captured into a best-effort
``house_rules`` map. A missing or restructured section yields no field rather
than a failure.
"""

import re

from tourism_pricing_analytics.scraping.booking.features.base import PropertyFeatureContext
from tourism_pricing_analytics.scraping.booking.parsing import get_locator_text


_CHECKIN_RE = re.compile(r"Check-in\s+From\s+(\d{1,2}:\d{2})\s+to\s+(\d{1,2}:\d{2})")
_CHECKOUT_RE = re.compile(r"Check-out\s+From\s+(\d{1,2}:\d{2})\s+to\s+(\d{1,2}:\d{2})")
# Cancellation summary runs until the next policy label begins.
_CANCEL_RE = re.compile(
    r"Cancellation/?\s*prepayment\s+(.*?)"
    r"(?:\s+(?:Children|Child|Pets|Cards|Age|Deposit|Smoking|Parties|Quiet|Internet|Parking)\b|$)"
)


class PoliciesExtractor:
    name = "policies"

    def extract(self, ctx: PropertyFeatureContext) -> dict:
        sections = ctx.page.locator('[data-testid="property-section--content"]')
        text: str | None = None
        for index in range(sections.count()):
            candidate = get_locator_text(sections.nth(index))
            if candidate and "Check-in" in candidate and "Check-out" in candidate:
                text = candidate
                break
        if not text:
            return {}

        out: dict = {}
        checkin = _CHECKIN_RE.search(text)
        if checkin:
            out["checkin_from"] = checkin.group(1)
            out["checkin_until"] = checkin.group(2)
        checkout = _CHECKOUT_RE.search(text)
        if checkout:
            out["checkout_from"] = checkout.group(1)
            out["checkout_until"] = checkout.group(2)

        cancellation = _CANCEL_RE.search(text)
        if cancellation and cancellation.group(1).strip():
            out["house_rules"] = {"cancellation": cancellation.group(1).strip()}

        return out
