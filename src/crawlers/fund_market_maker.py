"""上交所基金做市商机构与产品做市关系采集。"""

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


FIRM_REFERER = "https://www.sse.com.cn/assortment/fund/jjzss/jjzsslb/"
RELATION_REFERER = "https://www.sse.com.cn/assortment/fund/jjzss/jjcpzsslb/"
FIRM_SQL_ID = "COMMON_SSE_CP_JJ_JJZSSLB_JJZSSLB"
RELATION_SQL_ID = "COMMON_SSE_CP_JJ_JJZSSLB_JJCPZSSLB"
FIRM_COLUMNS = [
    "firm_code",
    "firm_name",
    "firm_type",
    "product_type",
    "qualify_type",
    "raw_record_json",
]
RELATION_COLUMNS = [
    "market",
    "fund_code",
    "fund_name",
    "firm_name",
    "service_type",
    "source",
    "raw_record_json",
]


def _raw_json(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _text(value: object) -> str | None:
    text = str(value or "").strip()
    return None if text in {"", "-"} else text


def fetch_market_maker_firms(
    *,
    page_size: int = 500,
    timeout: tuple[float, float] = (5.0, 30.0),
    request_interval: float = 0.1,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    client = session or make_reference_session(FIRM_REFERER)
    rows, total, pages = fetch_paginated_result(
        client,
        QUERY_URL,
        {"sqlId": FIRM_SQL_ID},
        page_size=page_size,
        request_interval=request_interval,
        timeout=timeout,
    )
    frame = pd.DataFrame(
        {
            "firm_code": [_text(row.get("FIRM_CODE")) for row in rows],
            "firm_name": [_text(row.get("FIRM_NAME")) for row in rows],
            "firm_type": [_text(row.get("FIRM_TYPE")) for row in rows],
            "product_type": [_text(row.get("PRODUCT_TYPE")) for row in rows],
            "qualify_type": [_text(row.get("QUALIFY_TYPE")) for row in rows],
            "raw_record_json": [_raw_json(row) for row in rows],
        },
        columns=FIRM_COLUMNS,
    )
    for column in FIRM_COLUMNS:
        frame[column] = frame[column].astype("string")
    frame.attrs.update(api_total=total, pages_requested=pages)
    return frame


def fetch_fund_market_makers(
    *,
    security_code: str = "",
    firm_name: str = "",
    page_size: int = 500,
    timeout: tuple[float, float] = (5.0, 30.0),
    request_interval: float = 0.1,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """完整分页获取当前基金—做市商公开关系。"""
    code = str(security_code).strip()
    client = session or make_reference_session(RELATION_REFERER)
    rows, total, pages = fetch_paginated_result(
        client,
        QUERY_URL,
        {
            "sqlId": RELATION_SQL_ID,
            "securityCode": code,
            "firmName": str(firm_name).strip(),
        },
        page_size=page_size,
        request_interval=request_interval,
        timeout=timeout,
    )
    required = {"SECURITY_CODE", "FIRM_NAME", "SERVICE_TYPE"}
    for row in rows:
        missing = required.difference(row)
        if missing:
            raise ValueError(f"SSE market-maker relation row is missing: {sorted(missing)}")
    frame = pd.DataFrame(
        {
            "market": "SSE",
            "fund_code": [str(row.get("SECURITY_CODE", "")).strip() for row in rows],
            "fund_name": [_text(row.get("SEC_NAME_FULL")) for row in rows],
            "firm_name": [_text(row.get("FIRM_NAME")) for row in rows],
            "service_type": [_text(row.get("SERVICE_TYPE")) for row in rows],
            "source": "sse_fund_market_maker",
            "raw_record_json": [_raw_json(row) for row in rows],
        },
        columns=RELATION_COLUMNS,
    )
    for column in RELATION_COLUMNS:
        frame[column] = frame[column].astype("string")
    frame.attrs.update(api_total=total, pages_requested=pages)
    return frame.sort_values(
        ["fund_code", "firm_name", "service_type"]
    ).reset_index(drop=True)
