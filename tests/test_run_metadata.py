import json
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from tourism_pricing_analytics.scraping.booking.io import (
    infer_run_search_base_date,
    load_run_metadata,
    resolve_run_search_base_date,
)


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(f"{json.dumps(record)}\n" for record in records),
        encoding="utf-8",
    )


class RunMetadataTests(unittest.TestCase):
    def test_resolve_run_search_base_date_uses_existing_metadata(self) -> None:
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "run_metadata.json").write_text(
                json.dumps({"search_base_date": "2026-06-23"}),
                encoding="utf-8",
            )

            self.assertEqual(
                resolve_run_search_base_date(run_dir, today=date(2026, 6, 24)),
                date(2026, 6, 23),
            )

    def test_resolve_run_search_base_date_infers_from_existing_artifact(self) -> None:
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_jsonl(
                run_dir / "001_example" / "price_rows.jsonl",
                [
                    {
                        "checkin": "2026-06-30",
                        "checkout": "2026-07-04",
                        "lead_time_days": 7,
                    }
                ],
            )

            search_base_date = resolve_run_search_base_date(
                run_dir,
                today=date(2026, 6, 24),
            )

            self.assertEqual(search_base_date, date(2026, 6, 23))
            self.assertEqual(
                load_run_metadata(run_dir)["search_base_date"],
                "2026-06-23",
            )

    def test_infer_run_search_base_date_returns_none_without_dated_artifacts(self) -> None:
        with TemporaryDirectory() as tmp:
            self.assertIsNone(infer_run_search_base_date(Path(tmp)))


if __name__ == "__main__":
    unittest.main()
