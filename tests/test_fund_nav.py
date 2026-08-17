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

from src.crawlers import fund_nav
from src.crawlers.fund_nav import (
    LOF_PRODUCT_TYPES,
    LOF_REFERER,
    LOF_SQL_ID,
    REITS_REFERER,
    REITS_SQL_ID,
    fetch_latest_reits_nav,
    fetch_lof_nav,
    fetch_reits_nav,
)
from src.services.fund_nav_service import validate_fund_nav


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
            "result": rows,
            "pageHelp": {
                "pageNo": page_no,
                "pageCount": len(self.pages) if total else 0,
                "total": total,
            },
        }
        callback = params["jsonCallBack"]
        return FakeResponse(f"{callback}({json.dumps(payload, ensure_ascii=False)});")


def _lof_row(code: str = "501018", value: str = "1.2345") -> dict[str, str]:
    return {
        "PRODUCT_TYPE": "11",
        "NAV": value,
        "FUND_CODE": code,
        "FUND_ABBR": "测试LOF",
        "ASSESS_DATE": "2020-01-02",
        "SEC_NAME_FULL": "测试上市开放式基金",
        "NUM": "1",
    }


def _reits_row(code: str = "508000", value: str = "4.1234") -> dict[str, str]:
    return {
        "fundCode": code,
        "secNameCn": "测试REIT",
        "secNameFull": "测试基础设施证券投资基金",
        "appraiseDate": "2025-12-31",
        "fundUnitnetWorth": value,
    }


def test_lof_jsonp_parameters_history_and_field_mapping() -> None:
    session = FakeSession([[_lof_row()]])

    frame = fetch_lof_nav("2020-01-02", session=session, request_interval=0)

    params = session.calls[0][1]
    assert params["sqlId"] == LOF_SQL_ID
    assert params["PRODUCT_TYPE"] == LOF_PRODUCT_TYPES
    assert params["SEARCH_DATE"] == "2020-01-02"
    assert params["type"] == "inParams"
    assert frame.loc[0, "fund_code"] == "501018"
    assert frame.loc[0, "nav_date"] == pd.Timestamp("2020-01-02")
    assert frame.loc[0, "nav"] == 1.2345
    assert frame.loc[0, "nav_type"] == "daily_nav"
    assert frame.loc[0, "source_route"] == "lof"
    assert json.loads(frame.loc[0, "raw_record_json"])["NAV"] == "1.2345"


def test_lof_empty_date_and_pagination() -> None:
    empty = fetch_lof_nav(
        "2026-08-14", session=FakeSession([[]]), request_interval=0
    )
    session = FakeSession([[_lof_row("501018")], [_lof_row("501019")]])
    frame = fetch_lof_nav("2020-01-02", session=session, request_interval=0)

    assert empty.empty and str(empty["nav"].dtype) == "Float64"
    assert frame["fund_code"].tolist() == ["501018", "501019"]
    assert [call[1]["pageHelp.pageNo"] for call in session.calls] == [1, 2]


def test_reits_latest_parameters_and_appraisal_semantics() -> None:
    session = FakeSession([[_reits_row()]])

    frame = fetch_latest_reits_nav(session=session, request_interval=0)

    params = session.calls[0][1]
    assert params["sqlId"] == REITS_SQL_ID
    assert params["appraiseDate"] == ""
    assert params["maxDate"] == "1"
    assert frame.loc[0, "nav_date"] == pd.Timestamp("2025-12-31")
    assert frame.loc[0, "nav_type"] == "appraisal_nav"
    assert frame.loc[0, "source_route"] == "reits"
    assert pd.isna(frame.loc[0, "product_type"])


def test_reits_explicit_appraise_date_and_invalid_latest_combination() -> None:
    session = FakeSession([[_reits_row()]])
    fetch_reits_nav("2025-12-31", session=session, request_interval=0)

    assert session.calls[0][1]["appraiseDate"] == "20251231"
    assert session.calls[0][1]["maxDate"] == ""
    with pytest.raises(ValueError, match="cannot"):
        fetch_reits_nav("2025-12-31", latest=True, session=session)


def test_default_sessions_use_source_specific_referers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []
    sessions = [FakeSession([[_lof_row()]]), FakeSession([[_reits_row()]])]

    def make_session(referer: str) -> FakeSession:
        seen.append(referer)
        return sessions.pop(0)

    monkeypatch.setattr(fund_nav, "make_scale_session", make_session)
    fetch_lof_nav("2020-01-02", request_interval=0)
    fetch_reits_nav("2025-12-31", request_interval=0)

    assert seen == [LOF_REFERER, REITS_REFERER]


def test_unified_key_and_reits_semantics_are_validated() -> None:
    lof = fetch_lof_nav(
        "2020-01-02", session=FakeSession([[_lof_row()]]), request_interval=0
    )
    reits = fetch_reits_nav(
        "2025-12-31", session=FakeSession([[_reits_row()]]), request_interval=0
    )
    combined = validate_fund_nav(pd.concat([lof, reits], ignore_index=True))
    assert not combined.duplicated(
        ["market", "fund_code", "nav_date", "nav_type"]
    ).any()

    wrong = reits.copy()
    wrong["nav_type"] = "daily_nav"
    with pytest.raises(ValueError, match="appraisal_nav"):
        validate_fund_nav(wrong)
