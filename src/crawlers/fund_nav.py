"""上海证券交易所 LOF 日净值与公募 REITs 评估净值采集。"""

from __future__ import annotations

import json
import time
from datetime import date as date_type
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import requests

from src.crawlers.scale_common import get_jsonp, make_scale_session


COMMON_QUERY_URL = "https://query.sse.com.cn/commonQuery.do"
COMMON_SOA_QUERY_URL = "https://query.sse.com.cn/commonSoaQuery.do"
LOF_REFERER = "https://www.sse.com.cn/assortment/fund/lof/netvalue/"
REITS_REFERER = "https://www.sse.com.cn/assortment/fund/reits/netvalue/"
LOF_SQL_ID = "COMMON_SSE_CP_JJ_LOF_SSKFSJJJZ_L"
REITS_SQL_ID = "REITS_JZ"
LOF_PRODUCT_TYPES = "11,14"

OUTPUT_COLUMNS = [
    "market",
    "fund_code",
    "fund_name",
    "fund_full_name",
    "nav_date",
    "nav",
    "nav_type",
    "product_type",
    "source",
    "source_route",
    "observed_at",
    "raw_record_json",
]


def _normalise_date(value: str | date_type | datetime | None, fmt: str) -> str:
    if value is None:
        return ""
    try:
        return pd.Timestamp(value).strftime(fmt)
    except (TypeError, ValueError) as exc:
        raise ValueError("date must be a valid date") from exc


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "market": pd.Series(dtype="string"),
            "fund_code": pd.Series(dtype="string"),
            "fund_name": pd.Series(dtype="string"),
            "fund_full_name": pd.Series(dtype="string"),
            "nav_date": pd.Series(dtype="datetime64[ns]"),
            "nav": pd.Series(dtype="Float64"),
            "nav_type": pd.Series(dtype="string"),
            "product_type": pd.Series(dtype="string"),
            "source": pd.Series(dtype="string"),
            "source_route": pd.Series(dtype="string"),
            "observed_at": pd.Series(dtype="datetime64[ns, UTC]"),
            "raw_record_json": pd.Series(dtype="string"),
        }
    )


def _fetch_pages(
    session: requests.Session,
    url: str,
    business_params: dict[str, Any],
    *,
    timeout: tuple[float, float],
    request_interval: float,
    page_size: int,
) -> list[dict[str, Any]]:
    if page_size <= 0:
        raise ValueError("page_size must be positive")
    if request_interval < 0:
        raise ValueError("request_interval cannot be negative")

    records: list[dict[str, Any]] = []
    page_no = 1
    expected_total: int | None = None
    while True:
        if page_no > 1:
            time.sleep(request_interval)
        payload = get_jsonp(
            session,
            url,
            {
                "isPagination": "true",
                **business_params,
                "pageHelp.pageSize": page_size,
                "pageHelp.pageNo": page_no,
                "pageHelp.beginPage": page_no,
                "pageHelp.cacheSize": 1,
                "pageHelp.endPage": page_no,
            },
            timeout,
        )
        page_help = payload.get("pageHelp")
        if not isinstance(page_help, dict):
            raise ValueError("Fund NAV response has no pageHelp object")
        rows = payload.get("result")
        if rows is None:
            rows = page_help.get("data")
        if rows is None and int(page_help.get("total") or 0) == 0:
            rows = []
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ValueError("Fund NAV response has no valid data list")
        records.extend(rows)

        total = int(page_help.get("total") or 0)
        expected_total = total if expected_total is None else expected_total
        page_count = int(page_help.get("pageCount") or 0)
        current_page = int(page_help.get("pageNo") or page_no)
        if not rows or current_page >= page_count or len(records) >= total:
            break
        if current_page < page_no:
            raise RuntimeError("SSE fund NAV pagination did not advance")
        page_no = current_page + 1

    if expected_total is not None and len(records) != expected_total:
        raise ValueError(
            f"Fund NAV pagination returned {len(records)} rows, expected {expected_total}"
        )
    return records


def _raw_json(records: list[dict[str, Any]]) -> pd.Series:
    return pd.Series(
        [
            json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            for row in records
        ],
        dtype="string",
    )


def fetch_lof_nav(
    date: str | date_type | datetime | None = None,
    *,
    product_type: str = LOF_PRODUCT_TYPES,
    timeout: tuple[float, float] = (5.0, 30.0),
    request_interval: float = 0.2,
    page_size: int = 100,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """获取指定日期或接口最新 LOF 日净值；空日期不会触发日期回退。"""
    client = session or make_scale_session(LOF_REFERER)
    records = _fetch_pages(
        client,
        COMMON_QUERY_URL,
        {
            "sqlId": LOF_SQL_ID,
            "PRODUCT_TYPE": str(product_type).strip(),
            "SEARCH_DATE": _normalise_date(date, "%Y-%m-%d"),
            "type": "inParams",
        },
        timeout=timeout,
        request_interval=request_interval,
        page_size=page_size,
    )
    if not records:
        return _empty_frame()
    raw = pd.DataFrame.from_records(records)
    required = {
        "PRODUCT_TYPE",
        "NAV",
        "FUND_CODE",
        "FUND_ABBR",
        "ASSESS_DATE",
        "SEC_NAME_FULL",
    }
    missing = required.difference(raw.columns)
    if missing:
        raise ValueError(f"LOF NAV response is missing fields: {sorted(missing)}")
    observed_at = pd.Timestamp(datetime.now(timezone.utc))
    frame = pd.DataFrame(
        {
            "market": pd.Series(["SSE"] * len(raw), dtype="string"),
            "fund_code": raw["FUND_CODE"].astype("string").str.strip().str.zfill(6),
            "fund_name": raw["FUND_ABBR"].astype("string").str.strip(),
            "fund_full_name": raw["SEC_NAME_FULL"].astype("string").str.strip(),
            "nav_date": pd.to_datetime(raw["ASSESS_DATE"], errors="raise").dt.normalize(),
            "nav": pd.to_numeric(
                raw["NAV"].astype("string").str.replace(",", "", regex=False),
                errors="raise",
            ).astype("Float64"),
            "nav_type": pd.Series(["daily_nav"] * len(raw), dtype="string"),
            "product_type": raw["PRODUCT_TYPE"].astype("string").str.strip(),
            "source": pd.Series(["sse"] * len(raw), dtype="string"),
            "source_route": pd.Series(["lof"] * len(raw), dtype="string"),
            "observed_at": pd.Series([observed_at] * len(raw), dtype="datetime64[ns, UTC]"),
            "raw_record_json": _raw_json(records),
        }
    )
    return frame[OUTPUT_COLUMNS].reset_index(drop=True)


def fetch_latest_lof_nav(**kwargs: Any) -> pd.DataFrame:
    return fetch_lof_nav(None, **kwargs)


def fetch_reits_nav(
    appraise_date: str | date_type | datetime | None = None,
    *,
    latest: bool = False,
    timeout: tuple[float, float] = (5.0, 30.0),
    request_interval: float = 0.2,
    page_size: int = 100,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """获取明确评估时点或最新公募 REITs 评估净值。"""
    if latest and appraise_date is not None:
        raise ValueError("appraise_date and latest=True cannot be used together")
    client = session or make_scale_session(REITS_REFERER)
    records = _fetch_pages(
        client,
        COMMON_SOA_QUERY_URL,
        {
            "sqlId": REITS_SQL_ID,
            "appraiseDate": _normalise_date(appraise_date, "%Y%m%d"),
            "maxDate": "1" if latest else "",
        },
        timeout=timeout,
        request_interval=request_interval,
        page_size=page_size,
    )
    if not records:
        return _empty_frame()
    raw = pd.DataFrame.from_records(records)
    required = {
        "fundCode",
        "secNameCn",
        "secNameFull",
        "appraiseDate",
        "fundUnitnetWorth",
    }
    missing = required.difference(raw.columns)
    if missing:
        raise ValueError(f"REITs NAV response is missing fields: {sorted(missing)}")
    observed_at = pd.Timestamp(datetime.now(timezone.utc))
    frame = pd.DataFrame(
        {
            "market": pd.Series(["SSE"] * len(raw), dtype="string"),
            "fund_code": raw["fundCode"].astype("string").str.strip().str.zfill(6),
            "fund_name": raw["secNameCn"].astype("string").str.strip(),
            "fund_full_name": raw["secNameFull"].astype("string").str.strip(),
            # 请求参数使用 YYYYMMDD；真实返回目前使用 YYYY-MM-DD。
            "nav_date": pd.to_datetime(raw["appraiseDate"], errors="raise").dt.normalize(),
            "nav": pd.to_numeric(
                raw["fundUnitnetWorth"].astype("string").str.replace(",", "", regex=False),
                errors="raise",
            ).astype("Float64"),
            "nav_type": pd.Series(["appraisal_nav"] * len(raw), dtype="string"),
            # REITS_JZ 没有返回产品类型字段，保持缺失而不编造。
            "product_type": pd.Series([pd.NA] * len(raw), dtype="string"),
            "source": pd.Series(["sse"] * len(raw), dtype="string"),
            "source_route": pd.Series(["reits"] * len(raw), dtype="string"),
            "observed_at": pd.Series([observed_at] * len(raw), dtype="datetime64[ns, UTC]"),
            "raw_record_json": _raw_json(records),
        }
    )
    return frame[OUTPUT_COLUMNS].reset_index(drop=True)


def fetch_latest_reits_nav(**kwargs: Any) -> pd.DataFrame:
    return fetch_reits_nav(None, latest=True, **kwargs)
