import json
import unittest

import pandas as pd

from scripts.run_hedonic import build_report_payload, render_markdown_report
from tourism_pricing_analytics.analysis.hedonic import (
    GBR_FAMILY,
    HIST_FAMILY,
    build_design_matrix,
    explain_price_gap,
    feature_adjusted_peer_prices,
    fit_hedonic_models,
    group_kfold_splits,
    grouped_random_search,
    tune_hedonic_booster,
)
from tourism_pricing_analytics.analysis.segment import segment_self_catering


def _row(
    property_url: str,
    property_name: str,
    checkin: str,
    price_per_night: float,
    *,
    property_type: str = "Apartment",
    latitude: float = 35.5,
    longitude: float = 24.0,
    room_size_sqm: float | None = 50.0,
    bed_count: float | None = 2.0,
    review_score: float | None = 9.0,
    star_rating: float | None = 4.0,
) -> dict[str, object]:
    return {
        "property_name": property_name,
        "property_url": property_url,
        "checkin": pd.Timestamp(checkin),
        "checkout": pd.Timestamp(checkin) + pd.Timedelta(days=4),
        "lead_time_days": 7,
        "stay_length_days": 4,
        "room_id": f"{property_url}-room",
        "room_name": "Deluxe Apartment",
        "block_id": f"{property_url}-{checkin}",
        "occupancy_text": "2 adults",
        "conditions_text": "Free cancellation",
        "current_price_text": f"EUR {price_per_night * 4}",
        "original_price_text": None,
        "current_price_value": price_per_night * 4,
        "original_price_value": None,
        "price_per_night": price_per_night,
        "captured_at": pd.Timestamp("2026-06-23"),
        "checkin_month": pd.Timestamp(checkin).month,
        "checkin_is_weekend": pd.Timestamp(checkin).dayofweek >= 5,
        "crete_season": "Peak",
        "meal_plan_ordinal": 0,
        "cancellation_flexibility_ordinal": 2.0,
        "room_size_sqm": room_size_sqm,
        "bed_count": bed_count,
        "max_persons": 2.0,
        "amenities": ["Kitchen", "Balcony", "Sea view"],
        "star_rating": star_rating,
        "review_score": review_score,
        "review_count": 100.0,
        "property_type": property_type,
        "latitude": latitude,
        "longitude": longitude,
        "review_subscores": {"Cleanliness": 9.0, "Location": 8.8},
        "property_facilities": ["Free WiFi", "Parking"],
        "nearby_poi": [
            {"poi_name": "Beach", "distance": 0.8, "unit": "km"},
            {"poi_name": "Airport", "distance": 10.0, "unit": "km"},
        ],
        "house_rules": {},
        "quantity_options": [],
    }


def sample_hedonic_frame() -> pd.DataFrame:
    rows = []
    specs = [
        ("subject", "Subject Stay", 150.0, 35.500, 24.000, 52.0, 2.0, 9.2, 4.0),
        ("near", "Near Peer", 120.0, 35.501, 24.001, 48.0, 2.0, 8.8, 4.0),
        ("middle", "Middle Peer", 180.0, 35.520, 24.000, 70.0, 3.0, 9.0, 4.0),
        ("villa", "Villa Peer", 260.0, 35.530, 24.010, 110.0, 4.0, 9.5, 5.0),
        ("small", "Small Peer", 95.0, 35.490, 23.990, 32.0, 1.0, 8.3, 3.0),
        ("missing", "Missing Peer", 130.0, 35.505, 24.002, None, None, None, None),
    ]
    for url, name, base_price, lat, lon, size, beds, score, stars in specs:
        rows.append(
            _row(
                url,
                name,
                "2026-07-01",
                base_price,
                property_type="Villa" if url == "villa" else "Apartment",
                latitude=lat,
                longitude=lon,
                room_size_sqm=size,
                bed_count=beds,
                review_score=score,
                star_rating=stars,
            )
        )
        rows.append(
            _row(
                url,
                name,
                "2026-08-01",
                base_price + 15.0,
                property_type="Villa" if url == "villa" else "Apartment",
                latitude=lat,
                longitude=lon,
                room_size_sqm=size,
                bed_count=beds,
                review_score=score,
                star_rating=stars,
            )
        )
    rows.append(_row("hotel", "Hotel", "2026-07-01", 200.0, property_type="Hotel"))
    return pd.DataFrame(rows)


class HedonicDesignMatrixTests(unittest.TestCase):
    def test_design_matrix_has_log_target_and_no_leakage_columns(self) -> None:
        X, y, groups, meta = build_design_matrix(sample_hedonic_frame(), min_token_frequency=1)

        self.assertEqual(X.shape[0], sample_hedonic_frame().shape[0])
        self.assertAlmostEqual(y.iloc[0], 5.010635294096255)
        self.assertEqual(groups.iloc[0], "subject")
        self.assertIn("room_size_sqm", X.columns)
        self.assertIn("room_size_sqm_missing", X.columns)
        self.assertIn("bed_count_missing", X.columns)
        self.assertIn("subscore_cleanliness", X.columns)
        self.assertIn("nearby_poi_count", X.columns)
        self.assertIn("property_type__apartment", X.columns)
        self.assertIn("amenity__kitchen", X.columns)
        self.assertNotIn("max_persons", X.columns)
        self.assertNotIn("property_url", X.columns)
        self.assertNotIn("price_per_night", X.columns)
        self.assertNotIn("latitude", meta.ols_feature_columns)
        self.assertIn("latitude", meta.gbm_feature_columns)

    def test_room_size_tokens_do_not_leak_into_amenity_vocabulary(self) -> None:
        # Regression: Booking exposes room size ("35 m²") as a room facility row
        # that rides along in the raw amenity list. It is captured as
        # room_size_sqm and must not become a sparse amenity one-hot bucket that
        # the model reads as a price signal.
        frame = sample_hedonic_frame()
        frame["amenities"] = [
            ["Kitchen", "Balcony", "35 m²", "Sea view"] for _ in range(len(frame))
        ]
        X, _, _, meta = build_design_matrix(frame, min_token_frequency=1)

        self.assertNotIn("35 m²", meta.amenity_vocabulary)
        size_tokens = [tok for tok in meta.amenity_vocabulary if tok[0].isdigit()]
        self.assertEqual(size_tokens, [])
        size_columns = [
            col
            for col in X.columns
            if col.startswith("amenity__") and any(ch.isdigit() for ch in col)
        ]
        self.assertEqual(size_columns, [])
        # Real amenities alongside the size token are preserved.
        self.assertIn("amenity__kitchen", X.columns)

    def test_group_kfold_never_splits_one_property_across_train_and_test(self) -> None:
        _, _, groups, _ = build_design_matrix(sample_hedonic_frame(), min_token_frequency=1)
        for train_idx, test_idx in group_kfold_splits(groups, n_splits=3):
            train_groups = set(groups.iloc[train_idx])
            test_groups = set(groups.iloc[test_idx])
            self.assertFalse(train_groups & test_groups)


class HedonicModelTests(unittest.TestCase):
    def test_adjusted_peer_prices_and_gap_explanation_are_consistent(self) -> None:
        frame = sample_hedonic_frame()
        bundle = fit_hedonic_models(frame, min_token_frequency=1)
        peer_rows = frame.loc[frame["property_url"].isin(["near", "middle"])].copy()

        adjusted = feature_adjusted_peer_prices("subject", peer_rows, frame, bundle)
        self.assertEqual(adjusted.shape[0], peer_rows.shape[0])
        self.assertIn("feature_adjusted_price_per_night", adjusted.columns)
        self.assertTrue(adjusted["feature_adjusted_price_per_night"].notna().all())

        explanation = explain_price_gap(
            frame.loc[frame["property_url"] == "subject"].iloc[0],
            frame.loc[frame["property_url"] == "near"].iloc[0],
            frame,
            bundle,
        )
        self.assertAlmostEqual(
            explanation["observed_gap"],
            explanation["feature_explained_gap"] + explanation["residual_gap"],
        )
        json.dumps(explanation, sort_keys=True)

    def test_adjustment_ignores_sparse_tokens_and_clips_factor(self) -> None:
        # Regression: the feature-adjustment must not move a peer just because
        # the client owns a different bundle of incidental sparse amenity/
        # facility tokens. Only curated high-signal features may drive it.
        frame = sample_hedonic_frame()
        bundle = fit_hedonic_models(frame, min_token_frequency=1)
        peer_rows = frame.loc[frame["property_url"] == "near"].copy()

        # A client identical to the peer on every curated feature but carrying a
        # wildly different sparse-token bundle should adjust by ~1x.
        client = peer_rows.iloc[0].copy()
        client["property_url"] = "synthetic-client"
        client["amenities"] = ["Kitchen", "Balcony", "Hot tub", "Sauna", "Piano"]
        client["property_facilities"] = ["Free WiFi", "Parking", "Nightclub", "Casino"]

        adjusted = feature_adjusted_peer_prices(client, peer_rows, frame, bundle)
        factors = adjusted["feature_adjustment_factor"]
        for factor in factors:
            self.assertAlmostEqual(factor, 1.0, places=6)

        # The clip bounds the multiplier even for an extreme profile difference.
        extreme = peer_rows.iloc[0].copy()
        extreme["property_url"] = "extreme-client"
        extreme["room_size_sqm"] = 500.0
        extreme["star_rating"] = 5.0
        extreme["review_score"] = 9.9
        clipped = feature_adjusted_peer_prices(extreme, peer_rows, frame, bundle)
        self.assertLessEqual(clipped["feature_adjustment_factor"].max(), 2.0)
        self.assertGreaterEqual(clipped["feature_adjustment_factor"].min(), 0.5)

    def test_hedonic_report_renders(self) -> None:
        payload = build_report_payload(
            sample_hedonic_frame(),
            source_table="synthetic.parquet",
            client="subject",
            windows=[{"checkin": "2026-07-01", "lead_time_days": 7, "stay_length_days": 4}],
            max_peers=3,
            min_token_frequency=1,
        )
        report = render_markdown_report(payload)

        self.assertIn("adjusted_peer_price_rows", payload)
        self.assertGreater(len(payload["adjusted_peer_price_rows"]), 0)
        self.assertIn("feature_adjusted_price_per_night", payload["adjusted_peer_price_rows"][0])
        self.assertIn("# Hedonic Price Adjustment", report)
        self.assertIn("Feature-Adjusted Comparable Benchmark", report)
        self.assertIn("Price Gap Decomposition", report)

    def test_report_can_train_on_broader_frame_than_peer_benchmark(self) -> None:
        comparison_frame = sample_hedonic_frame()
        extra_training_rows = pd.DataFrame(
            [
                _row(
                    "trainer",
                    "Trainer Apartment",
                    "2026-07-01",
                    210.0,
                    latitude=35.7,
                    longitude=24.2,
                    room_size_sqm=85.0,
                    bed_count=4.0,
                    review_score=9.4,
                    star_rating=5.0,
                ),
                _row(
                    "trainer",
                    "Trainer Apartment",
                    "2026-08-01",
                    230.0,
                    latitude=35.7,
                    longitude=24.2,
                    room_size_sqm=85.0,
                    bed_count=4.0,
                    review_score=9.4,
                    star_rating=5.0,
                ),
            ]
        )
        training_frame = pd.concat([comparison_frame, extra_training_rows], ignore_index=True)

        payload = build_report_payload(
            comparison_frame,
            source_table="local.parquet",
            training_frame=training_frame,
            training_source_table="broad.parquet",
            client="subject",
            windows=[{"checkin": "2026-07-01", "lead_time_days": 7, "stay_length_days": 4}],
            max_peers=3,
            min_token_frequency=1,
        )
        report = render_markdown_report(payload)

        self.assertEqual(payload["source_table"], "local.parquet")
        self.assertEqual(payload["training_source_table"], "broad.parquet")
        self.assertEqual(payload["training_properties"], 7)
        self.assertEqual(payload["training_rows"], 14)
        self.assertEqual(payload["benchmark"]["coverage"]["peer_price_rows"], 3)
        self.assertIn("Comparable source table: `local.parquet`", report)
        self.assertIn("Hedonic training table: `broad.parquet`", report)


class HedonicTuningTests(unittest.TestCase):
    SMALL_GRID = [1, 2]
    SMALL_SPACES = {
        GBR_FAMILY: {
            "n_estimators": (60, 120),
            "learning_rate": (0.03, 0.05),
            "max_depth": (2, 3),
            "min_samples_leaf": (2, 3),
            "subsample": (0.8, 1.0),
            "max_features": (0.6, 1.0),
        },
        HIST_FAMILY: {
            "max_iter": (80, 150),
            "learning_rate": (0.05, 0.08),
            "max_leaf_nodes": (15, 31),
            "min_samples_leaf": (5, 10),
            "l2_regularization": (0.0, 1.0),
            "max_features": (0.7, 1.0),
        },
    }

    def _tune(self):
        return tune_hedonic_booster(
            segment_self_catering(sample_hedonic_frame()),
            token_frequency_grid=self.SMALL_GRID,
            search_spaces=self.SMALL_SPACES,
            n_iter=4,
            n_jobs=1,
        )

    def test_bakeoff_selects_a_valid_winner_with_leaderboard(self) -> None:
        winner = self._tune()
        self.assertIsNotNone(winner)
        self.assertIn(winner["family"], {GBR_FAMILY, HIST_FAMILY})
        self.assertIn(winner["min_token_frequency"], self.SMALL_GRID)
        self.assertLessEqual(
            set(winner["params"]), set(self.SMALL_SPACES[winner["family"]])
        )
        self.assertGreater(len(winner["leaderboard"]), 0)
        # Leaderboard is sorted best-first by EUR MAE and the winner leads it.
        maes = [entry["metrics"]["mae_eur_mean"] for entry in winner["leaderboard"]]
        self.assertEqual(maes, sorted(maes))
        self.assertAlmostEqual(maes[0], winner["metrics"]["mae_eur_mean"])

    def test_bakeoff_is_deterministic(self) -> None:
        first, second = self._tune(), self._tune()
        self.assertEqual(first["family"], second["family"])
        self.assertEqual(first["params"], second["params"])
        self.assertEqual(first["min_token_frequency"], second["min_token_frequency"])
        self.assertAlmostEqual(
            first["metrics"]["mae_eur_mean"], second["metrics"]["mae_eur_mean"]
        )

    def test_parallel_search_matches_serial(self) -> None:
        segment = segment_self_catering(sample_hedonic_frame())
        X, y, groups, meta = build_design_matrix(segment, min_token_frequency=1)
        feature_frame = X.loc[:, list(meta.gbm_feature_columns)]
        kwargs = dict(space=self.SMALL_SPACES[GBR_FAMILY], n_iter=4)
        serial = grouped_random_search(feature_frame, y, groups, GBR_FAMILY, n_jobs=1, **kwargs)
        parallel = grouped_random_search(feature_frame, y, groups, GBR_FAMILY, n_jobs=2, **kwargs)
        self.assertEqual(serial["params"], parallel["params"])
        self.assertAlmostEqual(
            serial["metrics"]["mae_eur_mean"], parallel["metrics"]["mae_eur_mean"]
        )

    def test_fit_records_tuning_metadata(self) -> None:
        bundle = fit_hedonic_models(
            sample_hedonic_frame(),
            tune=True,
            token_frequency_grid=self.SMALL_GRID,
            search_spaces=self.SMALL_SPACES,
            search_n_iter=4,
            search_n_jobs=1,
        )
        self.assertTrue(bundle.cv_metrics["tuned"])
        self.assertEqual(bundle.cv_metrics["model_family"], bundle.model_family)
        self.assertEqual(bundle.cv_metrics["min_token_frequency"], bundle.min_token_frequency)
        self.assertEqual(bundle.model_params, bundle.cv_metrics["model_params"])

    def test_explicit_token_frequency_takes_fast_fixed_path(self) -> None:
        bundle = fit_hedonic_models(sample_hedonic_frame(), min_token_frequency=1)
        self.assertFalse(bundle.cv_metrics["tuned"])
        self.assertEqual(bundle.model_family, GBR_FAMILY)
        self.assertEqual(bundle.min_token_frequency, 1)


if __name__ == "__main__":
    unittest.main()
