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

from src.crawlers import reits_scale
from src.crawlers.reits_scale import (
    FUND_TYPE,
    REFERER,
    SQL_ID,
    fetch_latest_reits_scale,
    fetch_reits_scale,
)


class FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


class FakeSession:
    def __init__(self, pages: list[list[dict[str, Any]]]) -> None:
        self.pages = pages
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, *, params: dict[str, Any], timeout: object) -> FakeResponse:
        self.calls.append((url, params.copy()))
        page_no = int(params["pageHelp.pageNo"])
        rows = self.pages[page_no - 1]
        total = sum(len(page) for page in self.pages)
        payload = {
            "actionErrors": [],
            "pageHelp": {
                "data": rows,
                "pageNo": page_no,
                "pageCount": len(self.pages) if total else 0,
                "total": total,
            },
        }
        callback = params["jsonCallBack"]
        return FakeResponse(f"{callback}({json.dumps(payload, ensure_ascii=False)});")


class ErrorPageSession:
    def get(self, url: str, *, params: dict[str, Any], timeout: object) -> FakeResponse:
        # SSE 缺少必要 Referer 时会出现类似 HTTP 200 系统错误正文，而非合法 JSONP。
        return FakeResponse('({"success":"false","error":"system error"})')


def _row(
    code: str = "508000", data_date: str = "20260814", total: str = "90,451.51"
) -> dict[str, str]:
    return {
        "TRADE_DATE": data_date,
        "FUND_CODE": code,
        "FUND_EXPAND_ABBR": f"测试REIT{code}",
        "TOTAL_VOL": total,
        "CURRENT_SHARE_DATE": data_date,
        "FUND_ABBR": "测试REIT",
    }


def _main_params(session: FakeSession) -> dict[str, Any]:
    return session.calls[0][1]


def test_reits_explicit_date_parameters_and_field_mapping() -> None:
    session = FakeSession([[_row()]])

    frame = fetch_reits_scale("2026-08-14", session=session, request_interval=0)

    params = _main_params(session)
    assert params["sqlId"] == SQL_ID
    assert params["FUND_TYPE"] == FUND_TYPE
    assert params["TRADE_DATE"] == "20260814"
    assert params["MAX_DATE"] == ""
    assert frame.loc[0, "date"] == pd.Timestamp("2026-08-14")
    assert frame.loc[0, "fund_code"] == "508000"
    assert frame.loc[0, "fund_name"] == "测试REIT508000"
    assert frame.loc[0, "shares_10k"] == 90451.51
    assert json.loads(frame.loc[0, "raw_record_json"])["TOTAL_VOL"] == "90,451.51"
    assert len(session.calls) == 1  # 主接口已经返回扩位简称，不查询 queryExpandName。


def test_reits_latest_uses_max_date() -> None:
    session = FakeSession([[_row()]])

    fetch_latest_reits_scale(session=session, request_interval=0)

    params = _main_params(session)
    assert params["TRADE_DATE"] == ""
    assert params["MAX_DATE"] == "1"


def test_reits_default_session_uses_official_referer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession([[_row()]])
    seen: list[str] = []

    def make_session(referer: str) -> FakeSession:
        seen.append(referer)
        return session

    monkeypatch.setattr(reits_scale, "make_scale_session", make_session)
    fetch_latest_reits_scale(request_interval=0)

    assert seen == [REFERER]


def test_reits_fetches_all_pages() -> None:
    session = FakeSession(
        [[_row("508000")], [_row("508001")], [_row("508002")]]
    )

    frame = fetch_reits_scale("2026-08-14", session=session, request_interval=0)

    assert frame["fund_code"].tolist() == ["508000", "508001", "508002"]
    assert [call[1]["pageHelp.pageNo"] for call in session.calls] == [1, 2, 3]


def test_reits_empty_result_has_stable_types() -> None:
    frame = fetch_reits_scale(
        "2026-08-09", session=FakeSession([[]]), request_interval=0
    )

    assert frame.empty
    assert isinstance(frame["fund_code"].dtype, pd.StringDtype)
    assert str(frame["shares_10k"].dtype) == "Float64"


def test_reits_invalid_jsonp_system_error_is_not_data() -> None:
    with pytest.raises(ValueError, match="JSONP"):
        fetch_latest_reits_scale(session=ErrorPageSession(), request_interval=0)


def test_reits_duplicate_source_key_is_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        fetch_reits_scale(
            "2026-08-14",
            session=FakeSession([[_row(), _row()]]),
            request_interval=0,
        )
