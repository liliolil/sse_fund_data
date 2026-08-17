from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.crawlers.etf_scale import fetch_etf_scale
from src.utils.jsonp import unwrap_jsonp


def test_unwrap_jsonp() -> None:
    assert unwrap_jsonp(' callback_1 ({"ok": true, "items": [1]}); ') == {
        "ok": True,
        "items": [1],
    }
    with pytest.raises(ValueError):
        unwrap_jsonp('wrong({"ok": true})', expected_callback="expected")
    with pytest.raises(ValueError):
        unwrap_jsonp('__import__("os")')


@pytest.fixture(scope="module")
def etf_scale_df() -> pd.DataFrame:
    # 模块级 fixture 只访问一次真实接口，避免每个测试重复请求。
    return fetch_etf_scale(request_interval=0.2)


def test_live_dataframe_is_nonempty(etf_scale_df: pd.DataFrame) -> None:
    assert not etf_scale_df.empty


def test_required_columns_exist(etf_scale_df: pd.DataFrame) -> None:
    assert {"date", "fund_code", "fund_name", "shares_10k"}.issubset(
        etf_scale_df.columns
    )


def test_fund_codes_remain_six_character_strings(etf_scale_df: pd.DataFrame) -> None:
    assert isinstance(etf_scale_df["fund_code"].dtype, pd.StringDtype)
    assert etf_scale_df["fund_code"].str.fullmatch(r"\d{6}").all()


def test_primary_key_is_unique(etf_scale_df: pd.DataFrame) -> None:
    assert not etf_scale_df.duplicated(["date", "fund_code"]).any()


def test_shares_are_numeric(etf_scale_df: pd.DataFrame) -> None:
    converted = pd.to_numeric(etf_scale_df["shares_10k"], errors="raise")
    assert converted.notna().all()
