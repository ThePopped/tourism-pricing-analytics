# Hedonic Price Adjustment

Comparable source table: `data\modelling\modelling_table.parquet`
Hedonic training table: `data\modelling\hedonic_training_table.parquet`

Price unit: EUR/night for a 2-guest Booking.com search. The model explains listed asking prices for available offers, not transacted demand.

## Training Summary

- Rows: 2668
- Properties: 306
- Grouped CV folds: 5
- GBM mean log R2: 0.533
- GBM mean log MAE: 0.265
- GBM mean EUR/night MAE: EUR 53.36
- OLS R2: 0.702
- OLS condition number: 102142529888187984.0

## Selected Model

- Family: hist_gradient_boosting (grouped-CV bake-off winner)
- Params: l2_regularization=0.0, learning_rate=0.05, max_features=0.7, max_iter=300, max_leaf_nodes=15, min_samples_leaf=10
- Amenity token floor: 15
- Prediction band: 80% split-conformal interval from 2668 out-of-fold residuals

## OLS Market Premia

| Feature | Coefficient | Robust SE | p-value |
| --- | ---: | ---: | ---: |
| hq__air_conditioning | -0.5020 | 0.1719 | 0.0035 |
| subscore_facilities | 0.4994 | 0.0525 | 0.0000 |
| subscore_value_for_money | -0.4975 | 0.0323 | 0.0000 |
| checkin_month | 0.4868 | 0.0653 | 0.0000 |
| nearest_poi_km_missing | -0.2071 | 0.0882 | 0.0188 |
| subscore_comfort | 0.1943 | 0.0563 | 0.0006 |
| property_type__holiday_home | -0.1629 | 0.0419 | 0.0001 |
| hq__washing_machine | -0.1604 | 0.0293 | 0.0000 |
| review_score | -0.1497 | 0.0618 | 0.0154 |
| bed_count_missing | 0.1471 | 0.0179 | 0.0000 |
| property_type__villa | 0.1383 | 0.0599 | 0.0211 |
| star_rating | 0.1360 | 0.0143 | 0.0000 |

## Feature-Adjusted Comparable Benchmark

- Client: Stavros Villas & Apartments
- Raw peer median: EUR 105.57
- Feature-adjusted peer median: EUR 110.38
- 80% conformal band: EUR 77.43 to EUR 185.57
- Feature-adjusted IQR: EUR 99.43 to EUR 126.94
- Adjusted peer rows: 185

## Price Gap Decomposition

- Client observed price: EUR 128.75
- Competitor observed price: EUR 84.75
- Observed gap: EUR 44.00
- Feature-explained gap: EUR 52.35
- Residual gap: EUR -8.35

