"""Append one run's available price offers to the movement observation store."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tourism_pricing_analytics.analysis.movement import (
    OBSERVATION_DEDUPE_KEY,
    PRICE_OBSERVATION_COLUMNS,
    MovementHistoryError,
    normalize_price_observations,
)
from tourism_pricing_analytics.features.build_features import build_features_from_run

DEFAULT_RUNS_ROOT = REPO_ROOT / "saved_dom" / "runs"
DEFAULT_OBSERVATIONS_OUT = REPO_ROOT / "data" / "modelling" / "price_observations.parquet"


def find_latest_run_dir(runs_root: Path) -> Path:
    """Return the most recent timestamped run dir that has price rows."""

    candidates = [
        path
        for path in runs_root.iterdir()
        if path.is_dir() and (path / "price_rows.jsonl").exists()
    ]
    if not candidates:
        raise FileNotFoundError(f"No run directories with price_rows.jsonl under {runs_root}")
    return max(candidates, key=lambda path: path.name)


def _first_present(row: dict, names: tuple[str, ...], default: object) -> object:
    for name in names:
        value = row.get(name)
        if value is not None:
            return value
    return default


def _snapshot_date_for_row(row: dict, run_id: str) -> object:
    if row.get("snapshot_date") is not None:
        return row["snapshot_date"]
    if row.get("captured_at") is not None:
        return row["captured_at"]
    return run_id[:8]


def observation_rows_from_features(
    feature_rows: list[dict],
    *,
    run_id: str,
    adults: int = 2,
    children: int = 0,
    rooms: int = 1,
    currency: str = "EUR",
    market: str = "Chania",
) -> pd.DataFrame:
    """Normalize feature rows to the price-observation schema."""

    rows: list[dict[str, object]] = []
    for row in feature_rows:
        observation = {
            "snapshot_date": _snapshot_date_for_row(row, run_id),
            "captured_at": row.get("captured_at"),
            "run_id": row.get("run_id") or run_id,
            "property_url": row.get("property_url"),
            "property_name": row.get("property_name"),
            "room_id": row.get("room_id"),
            "room_name": row.get("room_name"),
            "block_id": row.get("block_id"),
            "checkin": row.get("checkin"),
            "checkout": row.get("checkout"),
            "lead_time_days": row.get("lead_time_days"),
            "stay_length_days": row.get("stay_length_days"),
            "adults": _first_present(row, ("adults", "group_adults"), adults),
            "children": _first_present(row, ("children", "group_children"), children),
            "rooms": _first_present(row, ("rooms", "no_rooms"), rooms),
            "currency": _first_present(row, ("currency", "current_price_currency"), currency),
            "market": row.get("market") or market,
            "price_per_night": row.get("price_per_night"),
            "current_price_value": row.get("current_price_value"),
            "property_type": row.get("property_type"),
            "latitude": row.get("latitude"),
            "longitude": row.get("longitude"),
        }
        rows.append(observation)

    if not rows:
        raise MovementHistoryError("No price rows found to append as observations")
    frame = pd.DataFrame(rows, columns=PRICE_OBSERVATION_COLUMNS)
    return normalize_price_observations(frame).loc[:, list(PRICE_OBSERVATION_COLUMNS)]


def build_price_observations_from_run(
    run_dir: Path,
    *,
    adults: int = 2,
    children: int = 0,
    rooms: int = 1,
    currency: str = "EUR",
    market: str = "Chania",
) -> pd.DataFrame:
    """Build price observations from an existing scrape run directory."""

    feature_rows = build_features_from_run(run_dir)
    return observation_rows_from_features(
        feature_rows,
        run_id=run_dir.name,
        adults=adults,
        children=children,
        rooms=rooms,
        currency=currency,
        market=market,
    )


def append_price_observations(
    new_observations: pd.DataFrame,
    out_path: Path,
) -> pd.DataFrame:
    """Append, dedupe by observation identity, and atomically write Parquet."""

    normalized_new = normalize_price_observations(new_observations)
    if out_path.exists():
        existing = normalize_price_observations(pd.read_parquet(out_path))
        combined = pd.concat([existing, normalized_new], ignore_index=True)
    else:
        combined = normalized_new

    deduped = (
        combined.drop_duplicates(subset=list(OBSERVATION_DEDUPE_KEY), keep="last")
        .sort_values(list(OBSERVATION_DEDUPE_KEY))
        .reset_index(drop=True)
    )
    deduped = normalize_price_observations(deduped).loc[:, list(PRICE_OBSERVATION_COLUMNS)]
    write_price_observations_atomic(deduped, out_path)
    return deduped


def write_price_observations_atomic(frame: pd.DataFrame, out_path: Path) -> None:
    """Write observations to Parquet via a same-directory temporary file."""

    out_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = out_path.with_name(f".{out_path.name}.tmp")
    try:
        frame.to_parquet(temp_path, engine="pyarrow", index=False)
        temp_path.replace(out_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def append_price_observations_from_run(
    run_dir: Path,
    out_path: Path,
    *,
    adults: int = 2,
    children: int = 0,
    rooms: int = 1,
    currency: str = "EUR",
    market: str = "Chania",
) -> pd.DataFrame:
    """Build and append observations for one run directory."""

    observations = build_price_observations_from_run(
        run_dir,
        adults=adults,
        children=children,
        rooms=rooms,
        currency=currency,
        market=market,
    )
    return append_price_observations(observations, out_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=None,
        help="Run directory to append (defaults to latest under saved_dom/runs/).",
    )
    parser.add_argument(
        "--observations-out",
        type=Path,
        default=DEFAULT_OBSERVATIONS_OUT,
        help=f"Output Parquet path (default: {DEFAULT_OBSERVATIONS_OUT}).",
    )
    parser.add_argument("--adults", type=int, default=2)
    parser.add_argument("--children", type=int, default=0)
    parser.add_argument("--rooms", type=int, default=1)
    parser.add_argument("--currency", default="EUR")
    parser.add_argument("--market", default="Chania")
    args = parser.parse_args()

    run_dir = args.run_dir or find_latest_run_dir(DEFAULT_RUNS_ROOT)
    frame = append_price_observations_from_run(
        run_dir,
        args.observations_out,
        adults=args.adults,
        children=args.children,
        rooms=args.rooms,
        currency=args.currency,
        market=args.market,
    )
    print(f"Source run dir : {run_dir}")
    print(f"Wrote          : {args.observations_out}")
    print(f"Rows x cols    : {frame.shape[0]} x {frame.shape[1]}")
    print(f"Dedupe key     : {', '.join(OBSERVATION_DEDUPE_KEY)}")


if __name__ == "__main__":
    main()
