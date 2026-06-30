# Hedonic Price Adjustment

Comparable source table: `C:\Users\gabri\Documents\Projects\tourism_pricing_analytics\data\modelling\modelling_table.parquet`
Hedonic training table: `data\modelling\hedonic_training_table.parquet`

Price unit: EUR/night for a 2-guest Booking.com search. The model explains listed asking prices for available offers, not transacted demand.

## Training Summary

- Rows: 1583
- Properties: 154
- Grouped CV folds: 5
- GBM mean log R2: 0.311
- GBM mean log MAE: 0.285
- GBM mean EUR/night MAE: EUR 53.32
- OLS R2: 0.625
- OLS condition number: 94480971881049424.0

## OLS Market Premia

| Feature | Coefficient | Robust SE | p-value |
| --- | ---: | ---: | ---: |
| subscore_value_for_money | -0.5163 | 0.0354 | 0.0000 |
| subscore_facilities | 0.2757 | 0.0699 | 0.0001 |
| property_type__villa | 0.1943 | 0.0626 | 0.0019 |
| subscore_staff | 0.1939 | 0.0359 | 0.0000 |
| subscore_host | 0.1673 | 0.0579 | 0.0038 |
| property_type__holiday_home | 0.1664 | 0.0503 | 0.0009 |
| meal_plan_ordinal | 0.1528 | 0.0214 | 0.0000 |
| star_rating | 0.1293 | 0.0280 | 0.0000 |
| star_rating_missing | -0.1179 | 0.0465 | 0.0112 |
| bed_count_missing | 0.1018 | 0.0330 | 0.0020 |
| subscore_comfort | 0.0936 | 0.0631 | 0.1377 |
| checkin_month | 0.0897 | 0.0930 | 0.3347 |

## Feature-Adjusted Comparable Benchmark

- Client: Stavros Villas & Apartments
- Raw peer median: EUR 119.00
- Feature-adjusted peer median: EUR 113.63
- Feature-adjusted IQR: EUR 99.19 to EUR 130.80
- Adjusted peer rows: 109

## Price Gap Decomposition

- Client observed price: EUR 117.86
- Competitor observed price: EUR 57.00
- Observed gap: EUR 60.86
- Feature-explained gap: EUR 35.80
- Residual gap: EUR 25.06

