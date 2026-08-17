from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.services.etf_scale_service import (
    backfill_etf_scale,
    generate_date_range,
    validate_etf_scale,
)
from src.storage.parquet_store import read_parquet, save_parquet


def _sample(data_date: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime([data_date, data_date]),
            "fund_code": pd.Series(["510050", "510010"], dtype="string"),
            "fund_name": pd.Series(["基金乙", "基金甲"], dtype="string"),
            "shares_10k": [20.0, 10.5],
        }
    )


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=["date", "fund_code", "fund_name", "shares_10k"])


def test_generate_date_range_is_inclusive() -> None:
    assert generate_date_range("2026-08-01", "2026-08-03") == (
        "2026-08-01",
        "2026-08-02",
        "2026-08-03",
    )
    with pytest.raises(ValueError):
        generate_date_range("2026-08-03", "2026-08-01")


def test_existing_date_is_not_requested(tmp_path: Path) -> None:
    path = tmp_path / "etf_scale.parquet"
    save_parquet(validate_etf_scale(_sample("2026-08-02")), path)
    calls: list[str] = []

    def fetcher(requested: str) -> pd.DataFrame:
        calls.append(requested)
        return _empty()

    result = backfill_etf_scale(
        "2026-08-01", "2026-08-03", path, fetcher=fetcher
    )

    assert calls == ["2026-08-01", "2026-08-03"]
    assert result.skipped_dates == ("2026-08-02",)
    assert result.non_trading_dates == ("2026-08-01", "2026-08-03")


def test_new_trading_dates_are_appended_sorted_and_unique(tmp_path: Path) -> None:
    path = tmp_path / "etf_scale.parquet"
    save_parquet(validate_etf_scale(_sample("2026-08-03")), path)
    responses = {
        "2026-08-01": _sample("2026-08-01"),
        "2026-08-02": _empty(),
    }

    result = backfill_etf_scale(
        "2026-08-01",
        "2026-08-03",
        path,
        fetcher=lambda requested: responses[requested],
    )
    restored = read_parquet(path)

    assert result.added_dates == ("2026-08-01",)
    assert result.non_trading_dates == ("2026-08-02",)
    assert not restored.duplicated(["date", "fund_code"]).any()
    expected = restored.sort_values(["date", "fund_code"]).reset_index(drop=True)
    pd.testing.assert_frame_equal(restored, expected)


def test_mismatched_actual_date_is_added_only_once(tmp_path: Path) -> None:
    path = tmp_path / "etf_scale.parquet"

    result = backfill_etf_scale(
        "2026-08-08",
        "2026-08-09",
        path,
        fetcher=lambda requested: _sample("2026-08-07"),
    )
    restored = read_parquet(path)

    assert result.date_mismatches == (
        ("2026-08-08", "2026-08-07"),
        ("2026-08-09", "2026-08-07"),
    )
    assert result.added_dates == ("2026-08-07",)
    assert result.skipped_dates == ("2026-08-09",)
    assert restored["date"].drop_duplicates().tolist() == [pd.Timestamp("2026-08-07")]
    assert not restored.duplicated(["date", "fund_code"]).any()
