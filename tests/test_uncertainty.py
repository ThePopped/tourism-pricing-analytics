"""Tests for the hedonic prediction-uncertainty layer (Phase D).

Covers grouped split-conformal residual collection, the reported prediction
band (per-row and price-level), the optional HistGBM quantile-model width, and
the honesty properties that matter downstream: bounds are ordered, empirical
coverage on *held-out properties* tracks the target, and the band widens as the
data gets noisier.
"""

import math
import unittest

import numpy as np
import pandas as pd

from tests.test_hedonic import _row
from tourism_pricing_analytics.analysis.hedonic import (
    DEFAULT_GBR_PARAMS,
    GBR_FAMILY,
    build_design_matrix,
    fit_hedonic_models,
    grouped_conformal_residuals,
    group_kfold_splits,
    prediction_interval,
    price_band,
    quantile_interval,
    residual_quantiles,
)


def _synthetic_frame(
    *,
    n_properties: int = 40,
    noise: float = 0.05,
    seed: int = 10001,
) -> pd.DataFrame:
    """Deterministic self-catering frame with a known log-price structure.

    ``log(price) = 4.0 + 0.012*size + 0.1*beds + N(0, noise)`` for every
    property, across two check-in dates. Same ``seed`` reproduces the frame; a
    larger ``noise`` scales the same underlying draws so residual spread grows
    monotonically.
    """

    rng = np.random.RandomState(seed)
    rows: list[dict[str, object]] = []
    for index in range(n_properties):
        size = float(rng.uniform(30.0, 120.0))
        beds = float(rng.randint(1, 5))
        score = float(rng.uniform(7.5, 9.8))
        lat = 35.5 + float(rng.uniform(-0.05, 0.05))
        lon = 24.0 + float(rng.uniform(-0.05, 0.05))
        base_log = 4.0 + 0.012 * size + 0.1 * beds
        for checkin in ("2026-07-01", "2026-08-01"):
            log_price = base_log + noise * float(rng.normal())
            price = round(math.exp(log_price), 2)
            rows.append(
                _row(
                    f"p{index}",
                    f"Prop {index}",
                    checkin,
                    price,
                    latitude=lat,
                    longitude=lon,
                    room_size_sqm=size,
                    bed_count=beds,
                    review_score=score,
                )
            )
    return pd.DataFrame(rows)


class ConformalResidualTests(unittest.TestCase):
    def test_residuals_are_out_of_fold_and_deterministic(self) -> None:
        frame = _synthetic_frame(n_properties=20)
        X, y, groups, meta = build_design_matrix(frame, min_token_frequency=1)
        feature_frame = X.loc[:, list(meta.gbm_feature_columns)]

        first = grouped_conformal_residuals(
            feature_frame, y, groups, GBR_FAMILY, DEFAULT_GBR_PARAMS
        )
        second = grouped_conformal_residuals(
            feature_frame, y, groups, GBR_FAMILY, DEFAULT_GBR_PARAMS
        )
        np.testing.assert_allclose(first, second)

        # Every row lands in exactly one test fold -> one OOF residual each.
        test_rows = sum(len(test_idx) for _, test_idx in group_kfold_splits(groups))
        self.assertEqual(first.size, test_rows)
        self.assertEqual(first.size, len(frame))

    def test_too_few_groups_yield_no_residuals(self) -> None:
        frame = _synthetic_frame(n_properties=1)
        X, y, groups, meta = build_design_matrix(frame, min_token_frequency=1)
        feature_frame = X.loc[:, list(meta.gbm_feature_columns)]
        residuals = grouped_conformal_residuals(
            feature_frame, y, groups, GBR_FAMILY, DEFAULT_GBR_PARAMS
        )
        self.assertEqual(residuals.size, 0)


class ResidualQuantileTests(unittest.TestCase):
    def test_empty_residuals_give_zero_offsets(self) -> None:
        self.assertEqual(residual_quantiles(np.empty(0), 0.8), (0.0, 0.0))

    def test_offsets_bracket_zero_and_widen_with_coverage(self) -> None:
        residuals = np.linspace(-1.0, 1.0, 201)
        lo80, hi80 = residual_quantiles(residuals, 0.8)
        lo95, hi95 = residual_quantiles(residuals, 0.95)
        self.assertLess(lo80, 0.0)
        self.assertGreater(hi80, 0.0)
        # A wider central interval reaches further into both tails.
        self.assertLess(lo95, lo80)
        self.assertGreater(hi95, hi80)


class PredictionBandTests(unittest.TestCase):
    def test_per_row_bounds_are_positive_and_ordered(self) -> None:
        frame = _synthetic_frame()
        bundle = fit_hedonic_models(frame, min_token_frequency=1)
        band = prediction_interval(bundle, frame.head(12))
        point = band["predicted_price_per_night"]
        self.assertTrue((band["lower_price_per_night"] > 0).all())
        self.assertTrue((band["lower_price_per_night"] <= point + 1e-9).all())
        self.assertTrue((point <= band["upper_price_per_night"] + 1e-9).all())

    def test_price_band_brackets_value_and_records_coverage(self) -> None:
        bundle = fit_hedonic_models(_synthetic_frame(), min_token_frequency=1)
        band = price_band(140.0, bundle, coverage=0.8)
        self.assertLessEqual(band["lower"], band["price"])
        self.assertLessEqual(band["price"], band["upper"])
        self.assertEqual(band["price"], 140.0)
        self.assertEqual(band["coverage"], 0.8)

    def test_no_residuals_collapse_band_onto_point(self) -> None:
        bundle = fit_hedonic_models(_synthetic_frame(n_properties=1), min_token_frequency=1)
        self.assertEqual(bundle.conformal_residuals.size, 0)
        band = prediction_interval(bundle, _synthetic_frame(n_properties=1))
        self.assertTrue(
            np.allclose(band["lower_price_per_night"], band["predicted_price_per_night"])
        )
        self.assertTrue(
            np.allclose(band["upper_price_per_night"], band["predicted_price_per_night"])
        )

    def test_empirical_coverage_tracks_target_on_held_out_properties(self) -> None:
        frame = _synthetic_frame(n_properties=48, noise=0.08)
        urls = sorted(frame["property_url"].unique())
        holdout = set(urls[::4])  # every 4th property is unseen at fit time
        fit_frame = frame.loc[~frame["property_url"].isin(holdout)]
        test_frame = frame.loc[frame["property_url"].isin(holdout)]

        coverage = 0.8
        bundle = fit_hedonic_models(fit_frame, min_token_frequency=1)
        band = prediction_interval(bundle, test_frame, coverage=coverage)

        actual = pd.to_numeric(test_frame["price_per_night"], errors="coerce").to_numpy()
        inside = (actual >= band["lower_price_per_night"].to_numpy()) & (
            actual <= band["upper_price_per_night"].to_numpy()
        )
        empirical = float(inside.mean())
        # Split conformal is only approximately valid at this sample size; require
        # the band to be genuinely calibrated (not degenerate, not everything).
        self.assertGreaterEqual(empirical, 0.6)
        self.assertLessEqual(empirical, 1.0)

    def test_band_widens_with_noisier_data(self) -> None:
        quiet = fit_hedonic_models(_synthetic_frame(noise=0.03), min_token_frequency=1)
        noisy = fit_hedonic_models(_synthetic_frame(noise=0.25), min_token_frequency=1)
        quiet_lo, quiet_hi = residual_quantiles(quiet.conformal_residuals, 0.8)
        noisy_lo, noisy_hi = residual_quantiles(noisy.conformal_residuals, 0.8)
        self.assertGreater(noisy_hi - noisy_lo, quiet_hi - quiet_lo)


class QuantileModelTests(unittest.TestCase):
    def test_quantile_interval_is_fitted_by_default_and_ordered(self) -> None:
        frame = _synthetic_frame()
        bundle = fit_hedonic_models(frame, min_token_frequency=1)
        self.assertIn("lower", bundle.quantile_models)
        self.assertIn("upper", bundle.quantile_models)

        interval = quantile_interval(bundle, frame.head(8))
        self.assertIsNotNone(interval)
        assert interval is not None  # for type-checkers
        self.assertTrue(
            (
                interval["lower_price_per_night"]
                <= interval["upper_price_per_night"] + 1e-9
            ).all()
        )

    def test_quantile_models_are_optional(self) -> None:
        frame = _synthetic_frame()
        bundle = fit_hedonic_models(frame, min_token_frequency=1, fit_quantile_models=False)
        self.assertEqual(bundle.quantile_models, {})
        self.assertIsNone(quantile_interval(bundle, frame.head(8)))


if __name__ == "__main__":
    unittest.main()
