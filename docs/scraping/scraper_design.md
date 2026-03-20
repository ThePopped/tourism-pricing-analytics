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
