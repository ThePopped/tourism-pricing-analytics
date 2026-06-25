# Comparable Competitor Benchmark

Source table: `C:\Users\gabri\Documents\Projects\tourism_pricing_analytics\data\modelling\modelling_table.parquet`

Price unit: EUR/night for a 2-guest Booking.com search. These are listed asking prices for available offers, not transacted demand.

## Client

- Property: Anna's House
- URL: https://www.booking.com/hotel/gr/anna-s-house.en-gb.html
- Type: Aparthotel
- Reference price: EUR 306.73

## Benchmark Windows

| Window | Criteria |
| ---: | --- |
| 1 | checkin=2026-06-30, crete_season=shoulder, lead_time_days=7, stay_length_days=4 |
| 2 | checkin=2026-06-30, crete_season=shoulder, lead_time_days=7, stay_length_days=7 |
| 3 | checkin=2026-07-23, crete_season=peak, lead_time_days=30, stay_length_days=4 |
| 4 | checkin=2026-07-23, crete_season=peak, lead_time_days=30, stay_length_days=7 |
| 5 | checkin=2026-08-22, crete_season=peak, lead_time_days=60, stay_length_days=4 |
| 6 | checkin=2026-08-22, crete_season=peak, lead_time_days=60, stay_length_days=7 |

## Peer Price Position

- Peer rows: 75
- Peer properties with prices: 9
- Peer range: EUR 122.00 to EUR 224.00 IQR; median EUR 159.00
- Subject median in these windows: EUR 306.73
- Subject percentile vs peers: 92.0%
- Gap to peer median: EUR 147.73 (92.9%)
- Flags: none

## Top Comparable Properties

| Rank | Property | Type | Distance km | Similarity | Median EUR/night |
| ---: | --- | --- | ---: | ---: | ---: |
| 1 | River Side | Aparthotel | 0.63 | 0.820 | 93.22 |
| 2 | Georgioupolis Plaza Suites | Aparthotel | 0.70 | 0.788 | 143.25 |
| 3 | Central | Aparthotel | 0.67 | 0.776 | 110.75 |
| 4 | Sunlight Beach Hotel | Aparthotel | 0.90 | 0.762 | 160.50 |
| 5 | Erasmia Beachside Suites | Apartment | 0.68 | 0.682 | 265.06 |
| 6 | Pinelopi Beach Suites | Apartment | 3.32 | 0.486 | 224.00 |
| 7 | Vryses Crete-Village Vibes | Apartment | 4.84 | 0.482 | 93.72 |
| 8 | Villa Fortuna with Private Pool | Villa | 6.11 | 0.343 | 409.02 |
| 9 | Traditional Tower | Villa | 5.04 | 0.278 | 215.00 |

