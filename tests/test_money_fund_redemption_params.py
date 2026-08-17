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

from src.crawlers.money_fund_redemption_params import (
    FUND_TYPE,
    NUMERIC_COLUMNS,
    SQL_ID,
    fetch_money_fund_redemption_params,
)
from src.services.money_fund_redemption_params_service import (
    PRIMARY_KEY,
    validate_money_fund_redemption_params,
)


class FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


class FakeSession:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.records = records
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, *, params: dict[str, Any], timeout: object) -> FakeResponse:
        self.calls.append((url, params.copy()))
        callback = params["jsonCallBack"]
        payload = {"actionErrors": [], "result": self.records}
        return FakeResponse(f"{callback}({json.dumps(payload, ensure_ascii=False)});")


def _row(code: str = "519800", buy_limit: str = "20,000,000.00") -> dict[str, str]:
    return {
        "FUND_CODE": code,
        "FUND_ABBREVIATION": "保证金A",
        "COMPANY_NAME": "测试基金管理有限公司",
        "FILE_DATE": "20260814",
        "TRADEDATE": "2026/08/14",
        "BUY_LIMIT": buy_limit,
        "BUY_LIMIT_SUM": "9,999,999,999.99",
        "SELL_LIMIT": "5,000,000.00",
        "SELL_LIMIT_SUM": "9,999,999,999.99",
        "ONEBUY_LIMIT": "10,000,000.00",
        "ONEBUY_LIMIT_SUM": "9,999,999,999.99",
        "ONESELL_LIMIT": "999,999,999.99",
        "ONESELL_LIMIT_SUM": "9,999,999,999.99",
        "OTHERS": "20,000.00",
        "NUM": "1",
    }


def test_jsonp_parameters_field_mapping_and_dates() -> None:
    session = FakeSession([_row()])

    frame = fetch_money_fund_redemption_params(session=session)

    params = session.calls[0][1]
    assert params["sqlId"] == SQL_ID
    assert params["FUND_TYPE"] == FUND_TYPE
    assert params["isPagination"] == "false"
    assert frame.loc[0, "market"] == "SSE"
    assert frame.loc[0, "fund_code"] == "519800"
    assert frame.loc[0, "fund_name"] == "保证金A"
    assert frame.loc[0, "file_date"] == pd.Timestamp("2026-08-14")
    assert frame.loc[0, "trade_date"] == pd.Timestamp("2026-08-14")
    assert frame.loc[0, "buy_limit"] == 20_000_000
    assert frame.loc[0, "single_sell_limit"] == 999_999_999.99
    assert frame.loc[0, "others"] == "20,000.00"
    assert frame.loc[0, "source_route"] == "money_fund_redemption_params"
    assert json.loads(frame.loc[0, "raw_record_json"])["BUY_LIMIT"] == "20,000,000.00"


def test_special_numeric_text_becomes_missing_not_zero_and_raw_is_preserved() -> None:
    frame = fetch_money_fund_redemption_params(
        session=FakeSession([_row(buy_limit="暂停申购")])
    )

    assert pd.isna(frame.loc[0, "buy_limit"])
    assert json.loads(frame.loc[0, "raw_record_json"])["BUY_LIMIT"] == "暂停申购"
    assert all(str(frame[column].dtype) == "Float64" for column in NUMERIC_COLUMNS)


def test_empty_response_has_stable_schema_and_duplicate_key_is_rejected() -> None:
    empty = fetch_money_fund_redemption_params(session=FakeSession([]))
    assert empty.empty and str(empty["buy_limit"].dtype) == "Float64"

    frame = fetch_money_fund_redemption_params(session=FakeSession([_row()]))
    with pytest.raises(ValueError, match="duplicate"):
        validate_money_fund_redemption_params(pd.concat([frame, frame]))
    assert not frame.duplicated(PRIMARY_KEY).any()


def test_num_is_optional_but_has_a_stable_source_column() -> None:
    row = _row()
    row.pop("NUM")
    frame = fetch_money_fund_redemption_params(session=FakeSession([row]))
    assert "source_num" in frame
    assert pd.isna(frame.loc[0, "source_num"])
