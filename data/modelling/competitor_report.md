# Comparable Competitor Benchmark

Source table: `C:\Users\gabri\Documents\Projects\tourism_pricing_analytics\data\modelling\modelling_table.parquet`

Price unit: EUR/night for a 2-guest Booking.com search. These are listed asking prices for available offers, not transacted demand.

## Client

- Property: Stavros Villas & Apartments
- URL: https://www.booking.com/hotel/gr/stavros-villas-amp-apartments.en-gb.html
- Type: Apartment
- Reference price: EUR 133.48

## Benchmark Windows

| Window | Criteria |
| ---: | --- |
| 1 | checkin=2026-07-13, crete_season=peak, lead_time_days=14, stay_length_days=4 |
| 2 | checkin=2026-07-13, crete_season=peak, lead_time_days=14, stay_length_days=7 |
| 3 | checkin=2026-07-29, crete_season=peak, lead_time_days=30, stay_length_days=4 |
| 4 | checkin=2026-07-29, crete_season=peak, lead_time_days=30, stay_length_days=7 |

## Peer Price Position

- Peer rows: 109
- Peer properties with prices: 19
- Peer range: EUR 95.25 to EUR 162.25 IQR; median EUR 119.00
- Subject median in these windows: EUR 133.48
- Subject percentile vs peers: 57.8%
- Gap to peer median: EUR 14.48 (12.2%)
- Flags: none

## Top Comparable Properties

| Rank | Property | Type | Distance km | Similarity | Median EUR/night |
| ---: | --- | --- | ---: | ---: | ---: |
| 1 | Andy's Gardens | Apartment | 0.28 | 0.846 | 98.00 |
| 2 | Studios Kydonia | Apartment | 0.25 | 0.829 | 96.19 |
| 3 | Aris Apartments | Apartment | 0.66 | 0.801 | 63.32 |
| 4 | Androulakis Apartments | Apartment | 0.76 | 0.784 | 108.00 |
| 5 | Elena Rooms & Apartments | Apartment | 0.62 | 0.771 | 104.50 |
| 6 | Mini Art Apartments | Apartment | 1.02 | 0.770 | 116.50 |
| 7 | Maleme Kefi | Apartment | 0.67 | 0.770 | 149.00 |
| 8 | Hippokratis Apartments | Aparthotel | 0.10 | 0.743 | 104.00 |
| 9 | Delta Beach | Apartment | 1.83 | 0.740 | 95.14 |
| 10 | Hotel Caretta Beach | Aparthotel | 0.37 | 0.729 | 171.29 |

