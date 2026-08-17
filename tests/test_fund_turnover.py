from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.crawlers.fund_turnover import (
    DAILY_CURRENT_SQL_ID,
    DAILY_HISTORY_SQL_ID,
    MONTHLY_HISTORY_SQL_ID,
    WEEKLY_CURRENT_SQL_ID,
    YEARLY_HISTORY_SQL_ID,
    fetch_daily_turnover,
    fetch_monthly_turnover,
    fetch_weekly_turnover,
    fetch_yearly_turnover,
)


class FakeResponse:
    def __init__(self, callback: str, rows: list[dict[str, Any]], url: str) -> None:
        self.status_code = 200
        self.url = url
        self.text = f"{callback}({json.dumps({'actionErrors': [], 'result': rows})});"

    def raise_for_status(self) -> None:
        return None


class FakeSession:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.params: dict[str, Any] = {}

    def get(self, url: str, *, params: dict[str, Any], timeout: object) -> FakeResponse:
        self.params = params
        return FakeResponse(params["jsonCallBack"], self.rows, url)


def test_daily_current_jsonp_and_field_mapping() -> None:
    session = FakeSession(
        [
            {
                "TRADE_DATE": "20260814",
                "PRODUCT_CODE": "05",
                "LIST_NUM": "1097",
                "TRADE_VOL": "1073.34",
                "TRADE_AMT": "3293.45",
                "TOTAL_VALUE": "35063.28",
                "NEGO_VALUE": "34295.77",
                "UNMAPPED_SOURCE_FIELD": "kept",
            }
        ]
    )

    frame = fetch_daily_turnover(session=session)

    assert session.params["sqlId"] == DAILY_CURRENT_SQL_ID
    assert session.params["SEARCH_DATE"] == ""
    assert frame.loc[0, "period_key"] == pd.Timestamp("2026-08-14")
    assert frame.loc[0, "product_code"] == "05"
    assert frame.loc[0, "list_count"] == 1097
    assert frame.loc[0, "trade_volume_100m_shares"] == pytest.approx(1073.34)
    assert frame.loc[0, "trade_amount_100m_cny"] == pytest.approx(3293.45)
    assert json.loads(frame.loc[0, "raw_record_json"])["UNMAPPED_SOURCE_FIELD"] == "kept"


def test_daily_history_uses_distinct_sql_id_and_exact_source_fields() -> None:
    session = FakeSession(
        [
            {
                "CAL_DATE": "2022-02-25 00:00:00.0",
                "PRODUCT_TYPE": "18",
                "TX_NUM": "557",
                "TX_VOLUME_FULL": "292.0121644",
                "TX_AMOUNT_FULL": "770.90336177",
                "MKT_VALUE_FULL": "10822.9897599234",
                "NEGOTIABLE_VALUE_FULL": "10822.9897599234",
            }
        ]
    )

    frame = fetch_daily_turnover("2022-02-25", session=session)

    assert session.params["sqlId"] == DAILY_HISTORY_SQL_ID
    assert session.params["searchDate"] == "2022-02-25"
    assert "SEARCH_DATE" not in session.params
    assert frame.loc[0, "source_route"] == "daily_history"
    assert frame.loc[0, "trade_volume_100m_shares"] == pytest.approx(292.0121644)
    assert frame.loc[0, "trade_amount_100m_cny"] == pytest.approx(770.90336177)


def test_weekly_current_mapping() -> None:
    session = FakeSession(
        [
            {
                "END_DATE": "20260807",
                "PRODUCT_CODE": "05",
                "LIST_NUM": "1096",
                "TRADE_VOL": "7439.1088",
                "TRADE_AMT": "18264.5326",
                "TOTAL_VALUE": "35647.99",
                "NEGO_VALUE": "34870.98",
                "WEEK_TRADE_DAYS": "5",
                "HIGH_VOL": "1714.7784",
                "HIGH_VOL_DATE": "20260805",
                "LOW_VOL": "1367.9003",
                "LOW_VOL_DATE": "20260806",
                "HIGH_AMT": "4001.0319",
                "HIGH_AMT_DATE": "20260805",
                "LOW_AMT": "3347.6735",
                "LOW_AMT_DATE": "20260803",
            }
        ]
    )

    frame = fetch_weekly_turnover(session=session)

    assert session.params["sqlId"] == WEEKLY_CURRENT_SQL_ID
    assert frame.loc[0, "period_start"] == pd.Timestamp("2026-08-03")
    assert frame.loc[0, "period_end"] == pd.Timestamp("2026-08-07")
    assert frame.loc[0, "trading_days"] == 5
    assert frame.loc[0, "high_trade_amount_date"] == pd.Timestamp("2026-08-05")


def test_monthly_and_yearly_real_response_schemas_are_mapped() -> None:
    monthly = FakeSession(
        [
            {
                "CAL_DATE_B": "2021-12",
                "PRODUCT_TYPE": "18",
                "TX_NUM": "538",
                "TX_VOLUME": "5906.3987",
                "TX_AMOUNT": "18128.329",
                "MKT_VALUE": "11301.49",
                "NEGOTIABLE_VALUE": "11301.49",
                "TOT_TRD_DATE": "23",
            }
        ]
    )
    yearly = FakeSession(
        [
            {
                "CAL_DATE": "2021-12-31 00:00:00.0",
                "PRODUCT_TYPE": "18",
                "TX_NUM": "538",
                "YTX_VOLUME": "47173.69",
                "YTX_AMOUNT": "153404.9948",
                "MKT_VALUE": "11301.49",
                "NEGOTIABLE_VALUE": "11301.49",
                "YTX_DATES": "243",
            }
        ]
    )

    month_frame = fetch_monthly_turnover("2021-12", session=monthly)
    year_frame = fetch_yearly_turnover("2021", session=yearly)

    assert monthly.params["sqlId"] == MONTHLY_HISTORY_SQL_ID
    assert month_frame.loc[0, "period_end"] == pd.Timestamp("2021-12-31")
    assert month_frame.loc[0, "support_status"] == "partially_verified"
    assert yearly.params["sqlId"] == YEARLY_HISTORY_SQL_ID
    assert year_frame.loc[0, "trade_amount_100m_cny"] == pytest.approx(153404.9948)
    assert year_frame.loc[0, "trading_days"] == 243


def test_yearly_placeholder_row_uses_requested_year_and_product_type_b() -> None:
    session = FakeSession(
        [
            {
                "CAL_DATE": None,
                "PRODUCT_TYPE": "-",
                "PRODUCT_TYPE_B": "36",
                "TX_NUM": "-",
                "YTX_VOLUME": "-",
                "YTX_AMOUNT": "-",
                "MKT_VALUE": "-",
                "NEGOTIABLE_VALUE": "-",
                "YTX_DATES": "-",
            }
        ]
    )

    frame = fetch_yearly_turnover("2021", session=session)

    assert frame.loc[0, "period_key"] == pd.Timestamp("2021-01-01")
    assert frame.loc[0, "period_end"] == pd.Timestamp("2021-12-31")
    assert frame.loc[0, "product_code"] == "36"
    assert pd.isna(frame.loc[0, "trade_amount_100m_cny"])


def test_empty_result_returns_typed_empty_frame() -> None:
    frame = fetch_monthly_turnover("2024-11", session=FakeSession([]))

    assert frame.empty
    assert pd.api.types.is_datetime64_dtype(frame["period_key"].dtype)
    assert isinstance(frame["product_code"].dtype, pd.StringDtype)


def test_weekly_requires_both_dates() -> None:
    with pytest.raises(ValueError, match="provided together"):
        fetch_weekly_turnover("2021-12-20")
