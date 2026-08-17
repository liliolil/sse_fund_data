"""上交所统一基金产品列表、分类树、详情和旧列表补充采集。"""

from __future__ import annotations

import json
import time
from typing import Any, Callable

import pandas as pd
import requests

from src.crawlers.fund_reference_common import (
    QUERY_URL,
    SOA_QUERY_URL,
    fetch_paginated_result,
    make_reference_session,
    request_jsonp,
)


REFERER = "https://etf.sse.com.cn/fundlist/"
LEGACY_REFERER = "https://www.sse.com.cn/assortment/fund/list/"
PRODUCT_SQL_ID = "COMMON_JJZWZ_JJLB_L"
CATEGORY_SQL_ID = "COMMON_JJZWZ_JJLB_JJLX_C"
DETAIL_SQL_ID = "COMMON_JJZWZ_JJLB_JJXQ_JBXX_C"
LEGACY_SQL_ID = "FUND_LIST"

CATEGORY_COLUMNS = ["category_code", "parent_code", "category_name"]
PRODUCT_COLUMNS = [
    "fund_code",
    "fund_name",
    "fund_expand_name",
    "fund_type_code",
    "management_company_code",
    "management_company_name",
    "underlying_index_name",
    "list_date",
    "source",
    "raw_record_json",
]
LEGACY_COLUMNS = ["fund_code", "underlying_index_code", "custodian"]

LEGACY_ROUTES: tuple[dict[str, str], ...] = (
    {
        "fundType": "00",
        "subClass": "01,02,03,04,06,08,09,31,32,33,34,35,36,37,38",
    },
    {"fundType": "50", "subClass": ""},
    {"fundType": "00", "subClass": "05,07"},
    {"fundType": "10", "subClass": "11,14,15"},
    {"fundType": "30", "subClass": ""},
)


def _raw_json(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _string_value(value: object) -> str | None:
    text = str(value or "").strip()
    return None if text in {"", "-"} else text


def fetch_fund_categories(
    *,
    timeout: tuple[float, float] = (5.0, 30.0),
    request_interval: float = 0.1,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """从 F000 开始递归读取完整官方分类树。"""
    if request_interval < 0:
        raise ValueError("request_interval cannot be negative")
    client = session or make_reference_session(REFERER)
    pending = ["F000"]
    requested: set[str] = set()
    records: dict[str, dict[str, str]] = {}
    calls = 0
    while pending:
        parent = pending.pop(0)
        if parent in requested:
            continue
        if calls:
            time.sleep(request_interval)
        payload = request_jsonp(
            client,
            QUERY_URL,
            {"sqlId": CATEGORY_SQL_ID, "CATEGORY_PARENT_CODE": parent},
            timeout=timeout,
        )
        calls += 1
        rows = payload.get("result")
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ValueError("SSE fund category response has no result object list")
        requested.add(parent)
        for row in rows:
            required = {"CATEGORY_CODE", "CATEGORY_PARENT_CODE", "CATEGORY_NAME"}
            missing = required.difference(row)
            if missing:
                raise ValueError(f"SSE fund category row is missing: {sorted(missing)}")
            code = str(row["CATEGORY_CODE"]).strip()
            if not code:
                raise ValueError("SSE fund category contains an empty code")
            records[code] = {
                "category_code": code,
                "parent_code": str(row["CATEGORY_PARENT_CODE"]).strip(),
                "category_name": str(row["CATEGORY_NAME"]).strip(),
            }
            if code not in requested:
                pending.append(code)
    frame = pd.DataFrame.from_records(list(records.values()), columns=CATEGORY_COLUMNS)
    for column in CATEGORY_COLUMNS:
        frame[column] = frame[column].astype("string")
    frame.attrs["requests_made"] = calls
    return frame.sort_values("category_code").reset_index(drop=True)


def fetch_fund_products(
    *,
    page_size: int = 500,
    timeout: tuple[float, float] = (5.0, 30.0),
    request_interval: float = 0.1,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """完整分页获取 CATEGORY=F000 的当前基金产品快照。"""
    client = session or make_reference_session(REFERER)
    rows, total, pages = fetch_paginated_result(
        client,
        QUERY_URL,
        {
            "sqlId": PRODUCT_SQL_ID,
            "type": "inParams",
            "FUND_CODE": "",
            "COMPANY_NAME": "",
            "INDEX_NAME": "",
            "START_DATE": "",
            "END_DATE": "",
            "CATEGORY": "F000",
            "CATEGORY_ASC": 1,
            "SUBCLASS": "",
            "SWING_TRADE": "",
        },
        page_size=page_size,
        request_interval=request_interval,
        timeout=timeout,
    )
    if not rows:
        raise ValueError("SSE unified fund list is empty")
    required = {
        "FUND_CODE",
        "FUND_ABBR",
        "FUND_EXPANSION_ABBR",
        "CATEGORY",
        "COMPANY_CODE",
        "COMPANY_NAME",
        "INDEX_NAME",
        "LISTING_DATE",
    }
    for row in rows:
        missing = required.difference(row)
        if missing:
            raise ValueError(f"SSE unified fund row is missing: {sorted(missing)}")
    frame = pd.DataFrame(
        {
            "fund_code": [str(row["FUND_CODE"]).strip() for row in rows],
            "fund_name": [_string_value(row["FUND_ABBR"]) for row in rows],
            "fund_expand_name": [
                _string_value(row["FUND_EXPANSION_ABBR"]) for row in rows
            ],
            "fund_type_code": [str(row["CATEGORY"]).strip() for row in rows],
            "management_company_code": [
                _string_value(row["COMPANY_CODE"]) for row in rows
            ],
            "management_company_name": [
                _string_value(row["COMPANY_NAME"]) for row in rows
            ],
            "underlying_index_name": [_string_value(row["INDEX_NAME"]) for row in rows],
            "list_date": [
                pd.to_datetime(_string_value(row["LISTING_DATE"]), errors="raise")
                if _string_value(row["LISTING_DATE"])
                else pd.NaT
                for row in rows
            ],
            "source": "sse_unified_fund_list",
            "raw_record_json": [_raw_json(row) for row in rows],
        },
        columns=PRODUCT_COLUMNS,
    )
    for column in set(PRODUCT_COLUMNS) - {"list_date"}:
        frame[column] = frame[column].astype("string")
    frame["list_date"] = pd.to_datetime(frame["list_date"]).dt.normalize()
    if frame.duplicated("fund_code").any():
        raise ValueError("SSE unified fund list contains duplicate fund_code values")
    frame.attrs.update(api_total=total, pages_requested=pages)
    return frame.sort_values("fund_code").reset_index(drop=True)


def fetch_fund_detail(
    fund_code: str,
    *,
    timeout: tuple[float, float] = (5.0, 30.0),
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """查询单只基金详情；接口不支持空代码批量调用。"""
    code = str(fund_code).strip()
    if not code:
        raise ValueError("fund_code cannot be empty")
    client = session or make_reference_session(REFERER)
    payload = request_jsonp(
        client,
        QUERY_URL,
        {"sqlId": DETAIL_SQL_ID, "FUND_CODE": code},
        timeout=timeout,
    )
    rows = payload.get("result")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("SSE fund detail response has no result object list")
    if len(rows) != 1:
        raise ValueError(f"SSE fund detail for {code} returned {len(rows)} rows")
    row = rows[0]
    if str(row.get("FUND_CODE", "")).strip() != code:
        raise ValueError(f"SSE fund detail returned a different fund code for {code}")
    return {
        "fund_code": code,
        "fund_legal_name": _string_value(row.get("FUND_NAME")),
        "establish_date": _string_value(row.get("ESTABLISH_DATE")),
        "custodian": _string_value(row.get("TRUSTEE_NAME")),
        "fund_manager_person": _string_value(row.get("FUND_MANAGER")),
        "detail_raw_record_json": _raw_json(row),
    }


def fetch_legacy_fund_supplement(
    *,
    page_size: int = 500,
    timeout: tuple[float, float] = (5.0, 30.0),
    request_interval: float = 0.1,
    session_factory: Callable[[], requests.Session] | None = None,
) -> pd.DataFrame:
    """按官方已验证路由批量补充指数代码和托管人。"""
    make_client = session_factory or (lambda: make_reference_session(LEGACY_REFERER))
    all_rows: list[dict[str, Any]] = []
    total_requests = 0
    for route_index, route in enumerate(LEGACY_ROUTES):
        if route_index:
            time.sleep(request_interval)
        rows, _, pages = fetch_paginated_result(
            make_client(),
            SOA_QUERY_URL,
            {"sqlId": LEGACY_SQL_ID, **route},
            page_size=page_size,
            request_interval=request_interval,
            timeout=timeout,
        )
        total_requests += pages
        all_rows.extend(rows)
    mapped = pd.DataFrame(
        {
            "fund_code": [str(row.get("fundCode", "")).strip() for row in all_rows],
            "underlying_index_code": [
                _string_value(row.get("INDEX_CODE")) for row in all_rows
            ],
            "custodian": [_string_value(row.get("TRUSTEE_NAME")) for row in all_rows],
        },
        columns=LEGACY_COLUMNS,
    )
    for column in LEGACY_COLUMNS:
        mapped[column] = mapped[column].astype("string")
    mapped = mapped.drop_duplicates("fund_code", keep="last")
    mapped.attrs["requests_made"] = total_requests
    return mapped.sort_values("fund_code").reset_index(drop=True)
