# Hedonic Price Adjustment

Source table: `C:\Users\gabri\Documents\Projects\tourism_pricing_analytics\data\modelling\modelling_table.parquet`

Price unit: EUR/night for a 2-guest Booking.com search. The model explains listed asking prices for available offers, not transacted demand.

## Training Summary

- Rows: 1256
- Properties: 67
- Grouped CV folds: 5
- GBM mean log R2: -1.628
- GBM mean log MAE: 0.383
- GBM mean EUR/night MAE: EUR 83.31
- OLS R2: 0.867
- OLS condition number: 11247963270357698.0

## OLS Market Premia

| Feature | Coefficient | Robust SE | p-value |
| --- | ---: | ---: | ---: |
| subscore_staff_missing | 2.4220 | 0.4760 | 0.0000 |
| subscore_host_missing | 2.3030 | 0.3819 | 0.0000 |
| property_type__holiday_home | -0.7808 | 0.3741 | 0.0369 |
| review_score | -0.5630 | 0.1710 | 0.0010 |
| subscore_facilities | 0.4636 | 0.0955 | 0.0000 |
| review_count_missing | -0.4600 | 0.0600 | 0.0000 |
| subscore_cleanliness_missing | -0.4600 | 0.0600 | 0.0000 |
| subscore_location_missing | -0.4600 | 0.0600 | 0.0000 |
| subscore_facilities_missing | -0.4600 | 0.0600 | 0.0000 |
| subscore_value_for_money_missing | -0.4600 | 0.0600 | 0.0000 |
| subscore_comfort_missing | -0.4600 | 0.0600 | 0.0000 |
| review_score_missing | -0.4600 | 0.0600 | 0.0000 |

## Feature-Adjusted Comparable Benchmark

- Client: Stavros Villas & Apartments
- Raw peer median: EUR 119.00
- Feature-adjusted peer median: EUR 120.35
- Feature-adjusted IQR: EUR 114.14 to EUR 129.56
- Adjusted peer rows: 109

## Price Gap Decomposition

- Client observed price: EUR 117.86
- Competitor observed price: EUR 57.00
- Observed gap: EUR 60.86
- Feature-explained gap: EUR 59.98
- Residual gap: EUR 0.88

