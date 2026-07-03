# Hedonic Price Adjustment

Comparable source table: `C:\Users\gabri\Documents\Projects\tourism_pricing_analytics\data\modelling\modelling_table.parquet`
Hedonic training table: `C:\Users\gabri\Documents\Projects\tourism_pricing_analytics\data\modelling\hedonic_training_table.parquet`

Price unit: EUR/night for a 2-guest Booking.com search. The model explains listed asking prices for available offers, not transacted demand.

## Training Summary

- Rows: 1583
- Properties: 154
- Grouped CV folds: 5
- GBM mean log R2: 0.259
- GBM mean log MAE: 0.296
- GBM mean EUR/night MAE: EUR 54.62
- OLS R2: 0.728
- OLS condition number: 88983968738760272.0

## Selected Model

- Family: hist_gradient_boosting (grouped-CV bake-off winner)
- Params: l2_regularization=0.0, learning_rate=0.05, max_features=0.7, max_iter=300, max_leaf_nodes=15, min_samples_leaf=10
- Amenity token floor: 15
- Prediction band: 80% split-conformal interval from 1583 out-of-fold residuals

## OLS Market Premia

| Feature | Coefficient | Robust SE | p-value |
| --- | ---: | ---: | ---: |
| checkin_month | 0.7702 | 0.1070 | 0.0000 |
| subscore_value_for_money | -0.6775 | 0.0490 | 0.0000 |
| subscore_host | -0.3825 | 0.0694 | 0.0000 |
| review_score | 0.3782 | 0.0928 | 0.0000 |
| subscore_location | 0.2076 | 0.0334 | 0.0000 |
| hq__parking | 0.1706 | 0.0214 | 0.0000 |
| subscore_cleanliness | 0.1526 | 0.0378 | 0.0001 |
| property_type__villa | -0.1381 | 0.0664 | 0.0375 |
| hq__pool | 0.1320 | 0.0333 | 0.0001 |
| hq__hot_tub | 0.1258 | 0.0301 | 0.0000 |
| property_type__holiday_home | 0.1233 | 0.0674 | 0.0673 |
| hq__beachfront | 0.1054 | 0.0270 | 0.0001 |

## Feature-Adjusted Comparable Benchmark

- Client: Stavros Villas & Apartments
- Raw peer median: EUR 119.00
- Feature-adjusted peer median: EUR 108.86
- 80% conformal band: EUR 70.87 to EUR 190.24
- Feature-adjusted IQR: EUR 95.42 to EUR 129.09
- Adjusted peer rows: 109

## Price Gap Decomposition

- Client observed price: EUR 117.86
- Competitor observed price: EUR 57.00
- Observed gap: EUR 60.86
- Feature-explained gap: EUR 35.02
- Residual gap: EUR 25.84

