from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.crawlers.lof_scale import PRODUCT_TYPE, SQL_ID, fetch_lof_scale


class FakeResponse:
    def __init__(self, callback: str, payload: dict[str, Any], url: str) -> None:
        self.url = url
        self.text = f"{callback}({json.dumps(payload, ensure_ascii=False)});"

    def raise_for_status(self) -> None:
        return None


class FakeSession:
    def __init__(self, pages: list[list[dict[str, Any]]], names: list[list[str]]) -> None:
        self.pages = pages
        self.names = names
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, *, params: dict[str, Any], timeout: object) -> FakeResponse:
        self.calls.append((url, params.copy()))
        callback = params["jsonCallBack"]
        if "queryExpandName" in url:
            return FakeResponse(callback, {"actionErrors": [], "result": self.names}, url)
        page_no = int(params["pageHelp.pageNo"])
        rows = self.pages[page_no - 1]
        total = sum(len(page) for page in self.pages)
        return FakeResponse(
            callback,
            {
                "actionErrors": [],
                "pageHelp": {
                    "data": rows,
                    "pageNo": page_no,
                    "pageCount": len(self.pages),
                    "total": total,
                },
            },
            url,
        )


def _row(code: str, shares: str = "582.32") -> dict[str, str]:
    return {
        "PRODUCT_TYPE": "11",
        "FUND_CODE": code,
        "NUM": "1",
        "FUND_ABBR": "原简称",
        "TRADE_DATE": "20260813",
        "SEC_NAME_FULL": "原全称",
        "INTERNAL_VOL": shares,
    }


def test_lof_jsonp_pagination_parameters_and_name_lookup() -> None:
    session = FakeSession(
        [[_row("501001")], [_row("501005", "3,253.01")]],
        [["501001", "财通精选混合LOF"], ["501005", "精准医疗LOF"]],
    )

    frame = fetch_lof_scale(
        "2026-08-13", session=session, page_size=1, request_interval=0
    )

    main_calls = [params for url, params in session.calls if "commonQuery" in url]
    name_calls = [params for url, params in session.calls if "queryExpandName" in url]
    assert [call["pageHelp.pageNo"] for call in main_calls] == [1, 2]
    assert main_calls[0]["sqlId"] == SQL_ID
    assert main_calls[0]["SEARCH_DATE"] == "2026-08-13"
    assert main_calls[0]["PRODUCT_TYPE"] == PRODUCT_TYPE
    assert main_calls[0]["type"] == "inParams"
    assert name_calls[0]["secCodes"] == "501001,501005"
    assert frame["fund_name"].tolist() == ["财通精选混合LOF", "精准医疗LOF"]
    assert frame["fund_code"].tolist() == ["501001", "501005"]
    assert frame["date"].drop_duplicates().tolist() == [pd.Timestamp("2026-08-13")]
    assert frame["shares_10k"].tolist() == [582.32, 3253.01]
    assert json.loads(frame.loc[0, "raw_record_json"])["INTERNAL_VOL"] == "582.32"


def test_lof_latest_query_uses_empty_search_date() -> None:
    session = FakeSession([[_row("501001")]], [["501001", "财通精选混合LOF"]])

    fetch_lof_scale(session=session, request_interval=0)

    main = next(params for url, params in session.calls if "commonQuery" in url)
    assert main["SEARCH_DATE"] == ""


def test_lof_empty_result_does_not_request_names() -> None:
    session = FakeSession([[]], [])

    frame = fetch_lof_scale("2026-08-09", session=session, request_interval=0)

    assert frame.empty
    assert len(session.calls) == 1
    assert isinstance(frame["fund_code"].dtype, pd.StringDtype)
