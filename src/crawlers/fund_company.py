"""上交所基金管理公司列表采集。"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
import requests

from src.crawlers.fund_reference_common import (
    QUERY_URL,
    fetch_paginated_result,
    make_reference_session,
)


REFERER = "https://www.sse.com.cn/assortment/fund/fundcompany/list/"
SQL_ID = "COMMON_SSE_SJ_HYTJSJ_HYLB_HYXX_L"
OUTPUT_COLUMNS = [
    "company_code",
    "company_name",
    "company_name_en",
    "president_name",
    "register_capital",
    "address",
    "zip_code",
    "telephone",
    "fax",
    "homepage",
    "contact_name",
    "contact_phone",
    "raw_record_json",
]


def _raw_json(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _text(value: object, *, preserve_dash: bool = False) -> str | None:
    text = str(value or "").strip()
    if not text or (text == "-" and not preserve_dash):
        return None
    return text


def fetch_fund_companies(
    *,
    page_size: int = 500,
    timeout: tuple[float, float] = (5.0, 30.0),
    request_interval: float = 0.1,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """完整分页获取上交所挂牌基金涉及的管理公司。"""
    client = session or make_reference_session(REFERER)
    rows, total, pages = fetch_paginated_result(
        client,
        QUERY_URL,
        {
            "sqlId": SQL_ID,
            "FULL_NAME": "",
            "CMP_TYPE": "2",
            "FULL_NAME_ASC": "1",
        },
        page_size=page_size,
        request_interval=request_interval,
        timeout=timeout,
    )
    if not rows:
        raise ValueError("SSE fund company list is empty")
    required = {"COMPANY_CODE", "FULL_NAME"}
    for row in rows:
        missing = required.difference(row)
        if missing:
            raise ValueError(f"SSE fund company row is missing: {sorted(missing)}")
    frame = pd.DataFrame(
        {
            "company_code": [
                _text(row.get("COMPANY_CODE"), preserve_dash=True) for row in rows
            ],
            "company_name": [_text(row.get("FULL_NAME")) for row in rows],
            "company_name_en": [_text(row.get("FULL_NAME_EN")) for row in rows],
            "president_name": [_text(row.get("PRESIDENT_NAME")) for row in rows],
            "register_capital": [_text(row.get("REGISTER_CAPITAL")) for row in rows],
            "address": [_text(row.get("ADDRESS")) for row in rows],
            "zip_code": [_text(row.get("ZIP_CODE")) for row in rows],
            "telephone": [_text(row.get("COMP_TEL")) for row in rows],
            "fax": [_text(row.get("COMP_FAX")) for row in rows],
            "homepage": [_text(row.get("HOMEPAGE")) for row in rows],
            "contact_name": [_text(row.get("LINKMAN_NAME")) for row in rows],
            "contact_phone": [_text(row.get("LINKMAN_TEL")) for row in rows],
            "raw_record_json": [_raw_json(row) for row in rows],
        },
        columns=OUTPUT_COLUMNS,
    )
    for column in OUTPUT_COLUMNS:
        frame[column] = frame[column].astype("string")
    frame.attrs.update(api_total=total, pages_requested=pages)
    return frame.reset_index(drop=True)
