from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.crawlers.fund_market_data import (
    ETF_URL,
    LOF_LIST_URL,
    LOF_SELF_URL,
    REITS_URL,
    fetch_etf_market_data,
    fetch_lof_market_data,
    fetch_reits_market_data,
)
from src.services.fund_market_data_service import PRIMARY_KEY, validate_fund_market_data


class FakeResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, Any]:
        return self.payload


class FakeSession:
    def __init__(self, handler) -> None:
        self.handler = handler
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, *, params: dict[str, Any], timeout: object) -> FakeResponse:
        self.calls.append((url, params.copy()))
        return FakeResponse(self.handler(url, params))


def _payload(rows: list[list[Any]], *, total: int | None = None, clock: int = 93001):
    return {
        "date": 20260817,
        "time": clock,
        "total": len(rows) if total is None else total,
        "begin": 0,
        "end": len(rows),
        "list": rows,
    }


def test_etf_json_pagination_mapping_and_numeric_coercion() -> None:
    rows = [
        ["510050", "50ETF", 2.7, 2.8, 2.6, 2.75, 2.72, 1.1, 100, 200, "上证50ETF华夏", "T111"],
        ["510300", "300ETF", "bad", 4.1, 3.9, 4.0, 3.95, 1.2, 300, 400, "沪深300ETF华泰柏瑞", "T111"],
    ]

    def handler(url, params):
        begin = int(params["begin"])
        selected = rows[begin : begin + 1]
        return _payload(selected, total=2, clock=93001 + begin)

    session = FakeSession(handler)
    frame = fetch_etf_market_data(session=session, page_size=1, request_interval=0)

    assert [call[0] for call in session.calls] == [ETF_URL, ETF_URL]
    assert frame["fund_code"].tolist() == ["510050", "510300"]
    assert set(frame["fund_type"]) == {"ETF"}
    assert set(frame["source_route"]) == {"etf"}
    assert frame.loc[0, "fund_name"] == "上证50ETF华夏"
    assert pd.isna(frame.loc[1, "open"])
    assert frame.loc[0, "trade_phase"] == "T111"
    assert frame["snapshot_time"].nunique() == 1


def test_reits_json_mapping_has_empty_trade_phase() -> None:
    row = ["508000", "华安张江产业园REIT", 2.0, 2.1, 1.9, 2.05, 2.0, 2.5, 100, 250]
    session = FakeSession(lambda url, params: _payload([row]))

    frame = fetch_reits_market_data(session=session, request_interval=0)

    assert session.calls[0][0] == REITS_URL
    assert frame.loc[0, "fund_type"] == "REIT"
    assert frame.loc[0, "source_route"] == "reits"
    assert frame.loc[0, "fund_name"] == "华安张江产业园REIT"
    assert pd.isna(frame.loc[0, "trade_phase"])


def test_lof_list_then_underscore_self_batches() -> None:
    codes = [["501018", "南方原油"], ["501019", "军工LOF"]]
    details = {
        "501018": ["501018", "南方原油", 1.1, 1.2, 1.0, 1.15, 1.1, 4.5, 20, 30],
        "501019": ["501019", "军工LOF", 0.9, 1.0, 0.8, 0.95, 0.9, 5.5, 40, 50],
    }

    def handler(url, params):
        if url == LOF_LIST_URL:
            return _payload(codes)
        assert url.startswith(LOF_SELF_URL + "/")
        requested = url.rsplit("/", 1)[1].split("_")
        return _payload([details[code] for code in requested])

    session = FakeSession(handler)
    frame = fetch_lof_market_data(
        session=session, request_interval=0, detail_batch_size=1
    )

    detail_urls = [url for url, _ in session.calls if url != LOF_LIST_URL]
    assert detail_urls == [f"{LOF_SELF_URL}/501018", f"{LOF_SELF_URL}/501019"]
    assert frame["fund_code"].tolist() == ["501018", "501019"]
    assert set(frame["fund_type"]) == {"LOF"}
    assert set(frame["source_route"]) == {"lof"}


def test_snapshot_business_key_is_unique_and_route_type_is_enforced() -> None:
    row = ["508000", "测试REIT", 2, 2, 2, 2, 2, 0, 1, 2]
    frame = fetch_reits_market_data(
        session=FakeSession(lambda url, params: _payload([row])), request_interval=0
    )
    checked = validate_fund_market_data(frame)
    assert not checked.duplicated(PRIMARY_KEY).any()

    wrong = frame.copy()
    wrong["fund_type"] = "ETF"
    with pytest.raises(ValueError, match="fund_type"):
        validate_fund_market_data(wrong)
