# Scraper Design Notes

## Goal

Build a Booking.com scraper that can:

1. Discover a stable room inventory for each property
2. Scrape date-specific prices for each room type
3. Repeat the price scrape across a configurable set of lead times and stay lengths

## Confirmed Live Findings

These observations were re-checked on 2026-06-03 using Playwright MCP against live Booking.com pages.

### Undated Property Page

- Property pages without `checkin` and `checkout` parameters expose room inventory but not usable prices.
- The room inventory is visible in the availability table even when prices are hidden.
- Room type anchors are exposed as `a[href^="#RD"]`.
- On `Solimar Aquamarine Resort`, the undated page exposed five room types:
  - `Superior Double Room with Private Pool`
  - `Superior Double or Twin Room`
  - `Junior Suite`
  - `Superior Suite with Private Pool`
  - `Junior Suite with Private Pool`
- Clicking `Show prices` on an undated page triggers a browser alert asking for check-in and check-out dates.

### Dated Property Page

- Adding URL parameters such as `?checkin=2026-07-03&checkout=2026-07-06&group_adults=2&no_rooms=1&group_children=0` changes the page into the usable pricing state.
- In that state, Booking.com renders a structured room/rate table rather than requiring calendar interaction.
- Each rate row can be scraped from the DOM.

### Cookies

- A cookie consent modal appears on first load and blocks interaction.
- The scraper should dismiss this at startup before any page parsing or clicking.

### Search Results Page

- Search result title links were still exposed with class `bd77474a8e` during the live check.
- This remains a viable starting point for property discovery.

## Confirmed DOM Patterns

### Search Results

- Property title link: `.bd77474a8e`
- The element itself is an anchor to the property page.

### Undated Property Page

- Room type links: `a[href^="#RD"]`
- The visible room inventory is present in the availability table even with no date selection.
- Clicking a `Show prices` button with no dates selected is not useful for scraping and should be avoided.

### Dated Property Page

- Rate rows: `tr.js-rt-block-row`
- Room cell on the first row of a room group:
  - `th.hprt-table-cell-roomtype`
  - room link: `.hprt-roomtype-link`
  - room id attribute: `data-room-id`
- Row-level metadata:
  - block id: `data-block-id`
  - rounded price: `data-hotel-rounded-price`
- Current price:
  - `.bui-price-display__value`
- Original price when discounted:
  - `.bui-price-display__original`
- Rate conditions:
  - `.hprt-table-cell-conditions`
- Quantity selector:
  - `select option`

## Scrape Strategy

### Loop 1: Room Inventory

Purpose:
- Capture the full set of room types per property

Approach:
- Visit the property page with no `checkin` and `checkout`
- Parse `a[href^="#RD"]` and the room inventory table
- Save:
  - property identifier
  - room name
  - room id
  - capture timestamp

Why this loop exists:
- Some room types disappear from dated pages when sold out
- The undated page gives a better room-type catalog
- This loop does not need to run daily unless property structure changes

### Loop 2: Price Collection

Purpose:
- Capture bookable prices for each property across target future stay windows

Approach:
- Build dated property URLs directly using query parameters
- Avoid calendar clicking
- For each `(property, lead_time, stay_length)` combination:
  - compute `checkin`
  - compute `checkout`
  - load the dated property page
  - parse the rate table
  - map each rate row back to a room id / room name

Recommended output fields:
- property url
- property name
- scrape timestamp
- checkin date
- checkout date
- stay length
- room id
- room name
- block id
- rate conditions text
- current total price
- original total price if present
- rounded price attribute
- price per night
- occupancy text if present
- scarcity text if present

## Data Interpretation Notes

- The dated page exposes total price for the stay, not just a nightly rate.
- Prices should be normalized to price per night for cross-window comparison.
- A room can have multiple rate rows:
  - non-refundable
  - free cancellation
  - breakfast included
  - other board / package variants
- The scraper should keep rate rows separate rather than collapsing them too early.

## Worked Examples From Live Checks

### Solimar Aquamarine Resort

URL pattern used:
- `checkin=2026-07-03`
- `checkout=2026-07-06`

Observed:
- Undated page exposed five room types
- Dated page exposed structured rows with:
  - `data-room-id`
  - `data-block-id`
  - current price
  - original price where discounted
  - rate conditions
  - quantity options

### Elia Daliani

URL pattern used:
- `checkin=2026-07-03`
- `checkout=2026-07-06`

Observed:
- Dated page used the same `tr.js-rt-block-row` pattern
- Conditions differed by breakfast inclusion and cancellation policy
- This is a good sign that the dated-page row parser can generalize

## Risks And Open Points

- Property URL normalization may need care. Some direct slugs can behave differently from search-result links, so the scraper should preserve canonical property URLs collected from Booking.com rather than guessing them.
- Search-result and property-page class names may change, so selectors should prefer semantic structure and data attributes where available.
- Rate rows represent commercial products, not only room types. One room id can map to several rate blocks.
- Some properties may require different occupancy handling, especially if max occupancy and default search occupancy differ.

## Scale Estimate

```python
property_count = 100
room_types = 3
lead_times = 5
stay_length_count = 3

assert property_count * room_types * lead_times * stay_length_count == 4500
```

The current scrape design should treat 4,500 as the rough order of magnitude for daily price collection, while keeping the room inventory loop on a slower cadence.
