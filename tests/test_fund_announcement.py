from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.crawlers.fund_announcement import (
    SQL_ID,
    build_announcement_key,
    fetch_fund_announcements,
    fetch_latest_fund_announcements,
    normalize_pdf_url,
    search_fund_announcements,
)


LATEST_ROW = {
    "discloseId": "2026081500508099GBUXFUND_BULLETI",
    "discloseDate": "2026-08-15",
    "bulletinTitle": "测试基金公告",
    "bulletinClassic": "FUND_BULLETIN",
    "bulletinUrl": "/disclosure/fund/announcement/c/new/2026-08-15/508099_test.pdf",
    "securityCode": "508099",
    "securityAbbr": "测试基金",
}


def historical_row(number: str, code: str = "508099") -> dict[str, str]:
    return {
        "SSEDATE": "2026-08-15",
        "ORG_BULLETIN_TYPE_DESC": "提示性公告",
        "BULLETIN_TYPE_DESC": "临时报告(基金)",
        "NUM": number,
        "TITLE": f"测试基金公告{number}",
        "FUND_EXPANSION_ABBR": "测试基金扩位简称",
        "SECURITY_CODE": code,
        "URL": f"/disclosure/fund/announcement/c/new/2026-08-15/{code}_{number}.pdf",
    }


class LatestResponse:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.encoding: str | None = None

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self.payload


class LatestSession:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.params: dict[str, Any] | None = None
        self.response: LatestResponse | None = None

    def get(self, url: str, *, params: dict[str, Any], timeout: object) -> LatestResponse:
        self.params = params.copy()
        self.response = LatestResponse(self.payload)
        return self.response


class JsonpResponse:
    def __init__(self, callback: str, payload: dict[str, Any]) -> None:
        self.text = f"{callback}({json.dumps(payload, ensure_ascii=False)});"

    def raise_for_status(self) -> None:
        return None


class HistorySession:
    def __init__(self, pages: list[list[dict[str, str]]]) -> None:
        self.pages = pages
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, *, params: dict[str, Any], timeout: object) -> JsonpResponse:
        self.calls.append(params.copy())
        page_no = int(params["pageHelp.pageNo"])
        rows = self.pages[page_no - 1]
        total = sum(len(page) for page in self.pages)
        payload = {
            "actionErrors": [],
            "pageHelp": {
                "data": rows,
                "pageNo": page_no,
                "pageCount": len(self.pages),
                "total": total,
            },
        }
        return JsonpResponse(params["jsonCallBack"], payload)


def test_latest_json_parsing_and_raw_record() -> None:
    session = LatestSession({"publishData": [LATEST_ROW]})

    frame = fetch_latest_fund_announcements(session=session)

    assert len(frame) == 1
    assert frame.loc[0, "announcement_date"] == pd.Timestamp("2026-08-15")
    assert frame.loc[0, "fund_code"] == "508099"
    assert frame.loc[0, "announcement_title"] == "测试基金公告"
    assert frame.loc[0, "source_announcement_id"] == LATEST_ROW["discloseId"]
    assert frame.loc[0, "source_route"] == "latest_json"
    assert json.loads(frame.loc[0, "raw_record_json"])["securityAbbr"] == "测试基金"
    assert session.response is not None and session.response.encoding == "utf-8"


def test_historical_jsonp_and_all_pagination_parameters_advance() -> None:
    session = HistorySession([[historical_row("1")], [historical_row("2")]])

    frame = search_fund_announcements(
        "2026-08-15",
        "2026-08-15",
        page_size=1,
        request_interval=0,
        session=session,
    )

    assert len(frame) == 2
    assert frame.attrs["api_total"] == 2
    assert frame.attrs["pages_requested"] == 2
    assert [call["pageHelp.pageNo"] for call in session.calls] == [1, 2]
    assert [call["pageHelp.beginPage"] for call in session.calls] == [1, 2]
    assert [call["pageHelp.endPage"] for call in session.calls] == [1, 2]
    assert all(call["sqlId"] == SQL_ID for call in session.calls)
    assert all(call["START_DATE"] == "2026-08-15" for call in session.calls)
    assert frame["source_announcement_id"].isna().all()
    assert (frame["source_route"] == "historical_search").all()


def test_announcement_key_rule_and_url_normalization() -> None:
    relative = "/disclosure/fund/announcement/c/new/2026-08-15/test.pdf#fragment"
    absolute = "https://www.sse.com.cn/disclosure/fund/announcement/c/new/2026-08-15/test.pdf"

    assert normalize_pdf_url(relative) == absolute
    assert build_announcement_key("DISCLOSE-1", relative) == (
        "sse:disclose_id:DISCLOSE-1"
    )
    assert build_announcement_key(pd.NA, relative) == f"sse:pdf_url:{absolute}"


def test_historical_empty_result_has_stable_columns() -> None:
    frame = search_fund_announcements(
        "2026-08-10",
        "2026-08-10",
        session=HistorySession([[]]),
        request_interval=0,
    )

    assert frame.empty
    assert frame.attrs["api_total"] == 0
    assert "raw_record_json" in frame.columns


def test_legacy_xbrl_match_output_remains_compatible() -> None:
    session = HistorySession([[historical_row("1", "510050")]])

    frame = fetch_fund_announcements(
        "510050",
        "2026-08-15",
        "2026-08-15",
        session=session,
        request_interval=0,
    )

    assert frame.loc[0, "securityCode"] == "510050"
    assert frame.loc[0, "announcementDate"] == "2026-08-15"
    assert frame.loc[0, "pdfUrl"].startswith("https://www.sse.com.cn/")
