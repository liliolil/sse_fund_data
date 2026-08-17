from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.services.etf_scale_service import update_etf_scale
from src.storage.parquet_store import parquet_exists, read_parquet


def _sample(data_date: str, shares: tuple[float, float] = (10.5, 20.0)) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime([data_date, data_date]),
            "fund_code": pd.Series(["510010", "510050"], dtype="string"),
            "fund_name": pd.Series(["基金甲", "基金乙"], dtype="string"),
            "shares_10k": list(shares),
        }
    )


@pytest.fixture
def parquet_path(tmp_path: Path) -> Path:
    return tmp_path / "processed" / "etf_scale.parquet"


def test_first_save_and_read_back(parquet_path: Path) -> None:
    result = update_etf_scale(parquet_path, fetcher=lambda: _sample("2026-08-12"))

    assert result.status == "initialized"
    assert parquet_exists(parquet_path)
    restored = read_parquet(parquet_path)
    assert list(restored.columns) == ["date", "fund_code", "fund_name", "shares_10k"]
    assert len(restored) == 2


def test_fund_code_stays_string_after_read(parquet_path: Path) -> None:
    update_etf_scale(parquet_path, fetcher=lambda: _sample("2026-08-12"))
    restored = read_parquet(parquet_path)

    assert pd.api.types.is_string_dtype(restored["fund_code"].dtype)
    assert restored["fund_code"].tolist() == ["510010", "510050"]


def test_same_date_is_not_appended(parquet_path: Path) -> None:
    update_etf_scale(parquet_path, fetcher=lambda: _sample("2026-08-12"))
    result = update_etf_scale(
        parquet_path,
        fetcher=lambda: _sample("2026-08-12", shares=(99.0, 99.0)),
    )

    assert result.status == "no_update"
    assert len(read_parquet(parquet_path)) == 2
    assert read_parquet(parquet_path)["shares_10k"].tolist() == [10.5, 20.0]


def test_new_date_is_appended_without_duplicate_key(parquet_path: Path) -> None:
    update_etf_scale(parquet_path, fetcher=lambda: _sample("2026-08-12"))
    result = update_etf_scale(parquet_path, fetcher=lambda: _sample("2026-08-13"))
    restored = read_parquet(parquet_path)

    assert result.status == "updated"
    assert len(restored) == 4
    assert restored["date"].min() == pd.Timestamp("2026-08-12")
    assert restored["date"].max() == pd.Timestamp("2026-08-13")
    assert not restored.duplicated(["date", "fund_code"]).any()
