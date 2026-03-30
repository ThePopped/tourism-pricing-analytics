# Scraper Design Notes
## Core Tasks
- Scrapes daily
- Scrape each property type per property description page e.g. small bedroom and large bedroom
    - ~~This is possibly too complex since it'll require interacting with price calendar over multiple date ranges~~
    - Might be able to use URL parameters
- Scrape price data for 5 future points:
    immediate (for that day), short, medium and long term

## Observations
- Discount price is not displayed when viewing listing page without dates selected. Prices shown in price calendar dropdown do not apply discount. Only after selecting dates under availablity do discounted prices appear.
- **Price Calendar** on listing page shows:
    - Unreliable price
    - Fairly reliable availability, sometimes no prices but still available
- Will be extremely complex to scrape undiscounted price reliably as these only appear when a date range is selecte
- Price calendar shows 1 price only per day, cant differentiate between different room types
## Initial ideas
- Use price calendar to fetch high-demand/fully booked periods
- Use price calendar to get view of all room types available

## Scraper Script
property_page_scraper.py

- Retrieves cookies modal on the first run:
[opened_element_000.html](../../saved_dom/full_page_after_click_000.html)
    - Need to accept/reject cookies at startup, contained in:
        id="onetrust-banner-sdk"
- Room type container seems to have same class accross sessions and properties

- Check in and checkout dates with "&checkin=2026-04-02&checkout=2026-04-05" in url

## Scrape Flow
1) **First Loop: Fetch available properties**. The point of this is not to get prices, just to see the full range of available room types. This is because room types will variably be missing from the property listing, depending on whether its fully booked in the period.
    - For each property, scrape the property listing page with no dates selected.
    - No prices shown, but will show all room types.
    - This does not need to be daily, since room types are unlikely to change daily.
    - DB table 
2) **Second Loop: Fetch prices**. Now the aim is to get prices. This will require an inner loop over a list of timeframes. So, we will get for each room type and for each timeframe, a price. I will need to decide on the lead times of the time frame (how far in advance the prospective booking is) and the timeframe lengths.
    - For each (property, room type, timeframe), fetch the total price.
    - This should be daily
    - prices should be normalised based on timeframe length (price per night) to be comparable
    - number of iterations: e.g.
    
    ```python
    property_count = 100
    room_types = 3 # avg, depends on listings, not me
    lead_times = 5 # e.g. [1, 7, 14, 30, 60]
    timeframe_length_count = 3 # e.g. [4, 7, 14]
    assert property_count * room_types * lead_times * timeframe_length_count == 4500
    ```
    - Assuming 1 minute per page, 4500 mins for all pages, = 1hr15 if syncronous
    - Now that dates are selected, prices will be shown, in addition to discounts (if any)
    -

