from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.crawlers.money_market_scale import SQL_ID, fetch_money_market_scale


class FakeResponse:
    def __init__(self, callback: str, payload: dict[str, Any], url: str) -> None:
        self.url = url
        self.text = f"{callback}({json.dumps(payload, ensure_ascii=False)});"

    def raise_for_status(self) -> None:
        return None


class FakeSession:
    def __init__(self, rows: list[dict[str, Any]], names: list[list[str]]) -> None:
        self.rows = rows
        self.names = names
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, *, params: dict[str, Any], timeout: object) -> FakeResponse:
        self.calls.append((url, params.copy()))
        callback = params["jsonCallBack"]
        if "queryExpandName" in url:
            payload = {"actionErrors": [], "result": self.names}
        else:
            payload = {
                "actionErrors": [],
                "pageHelp": {
                    "data": self.rows,
                    "pageNo": 1,
                    "pageCount": 1 if self.rows else 0,
                    "total": len(self.rows),
                },
            }
        return FakeResponse(callback, payload, url)


def _row() -> dict[str, str]:
    return {
        "STAT_DATE": "2026-08-13",
        "ETF_TYPE": "货币",
        "SEC_CODE": "511600",
        "NUM": "1",
        "SEC_NAME": "日日鑫ETF",
        "TOT_VOL": "1,082.82",
    }


def test_money_market_jsonp_date_parameter_and_name_lookup() -> None:
    session = FakeSession([_row()], [["511600", "华安日日鑫ETF"]])

    frame = fetch_money_market_scale(
        "2026-08-13", session=session, request_interval=0
    )

    main = next(params for url, params in session.calls if "commonQuery" in url)
    names = next(params for url, params in session.calls if "queryExpandName" in url)
    assert main["sqlId"] == SQL_ID
    assert main["STAT_DATE"] == "2026-08-13"
    assert "SEARCH_DATE" not in main
    assert names["secCodes"] == "511600"
    assert frame.loc[0, "fund_name"] == "华安日日鑫ETF"
    assert frame.loc[0, "fund_code"] == "511600"
    assert frame.loc[0, "date"] == pd.Timestamp("2026-08-13")
    assert frame.loc[0, "shares_10k"] == 1082.82
    assert frame.loc[0, "etf_type"] == "货币"
    assert json.loads(frame.loc[0, "raw_record_json"])["TOT_VOL"] == "1,082.82"


def test_money_market_latest_query_uses_empty_stat_date() -> None:
    session = FakeSession([_row()], [["511600", "华安日日鑫ETF"]])

    fetch_money_market_scale(session=session, request_interval=0)

    main = next(params for url, params in session.calls if "commonQuery" in url)
    assert main["STAT_DATE"] == ""


def test_money_market_empty_result_does_not_request_names() -> None:
    session = FakeSession([], [])

    frame = fetch_money_market_scale("2026-08-09", session=session, request_interval=0)

    assert frame.empty
    assert len(session.calls) == 1
    assert isinstance(frame["fund_code"].dtype, pd.StringDtype)
