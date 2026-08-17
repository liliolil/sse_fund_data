"""上海证券交易所公募 REITs 场内规模采集。"""

from __future__ import annotations

import json
from datetime import date as date_type
from datetime import datetime

import pandas as pd
import requests

from src.crawlers.scale_common import fetch_paginated_scale_rows, make_scale_session


REFERER = "https://www.sse.com.cn/market/funddata/volumn/reits/"
SQL_ID = "COMMON_SSE_SJ_JJSJ_JJGM_REITSGM_L"
FUND_TYPE = "01"
OUTPUT_COLUMNS = [
    "date",
    "fund_code",
    "fund_name",
    "shares_10k",
    "raw_record_json",
]


def _normalise_trade_date(value: str | date_type | datetime | None) -> str:
    if value is None:
        return ""
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("date must be a valid date") from exc
    return timestamp.strftime("%Y%m%d")


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.Series(dtype="datetime64[ns]"),
            "fund_code": pd.Series(dtype="string"),
            "fund_name": pd.Series(dtype="string"),
            "shares_10k": pd.Series(dtype="Float64"),
            "raw_record_json": pd.Series(dtype="string"),
        }
    )


def fetch_reits_scale(
    date: str | date_type | datetime | None = None,
    *,
    timeout: tuple[float, float] = (5.0, 30.0),
    request_interval: float = 0.2,
    page_size: int = 100,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """获取指定交易日，或在 date=None 时获取最新公募 REITs 规模。"""
    trade_date = _normalise_trade_date(date)
    client = session or make_scale_session(REFERER)
    records = fetch_paginated_scale_rows(
        client,
        {
            "sqlId": SQL_ID,
            "FUND_TYPE": FUND_TYPE,
            "TRADE_DATE": trade_date,
            "MAX_DATE": "1" if date is None else "",
        },
        timeout=timeout,
        request_interval=request_interval,
        page_size=page_size,
    )
    if not records:
        return _empty_frame()

    raw = pd.DataFrame.from_records(records)
    required = {"TRADE_DATE", "FUND_CODE", "FUND_EXPAND_ABBR", "TOTAL_VOL"}
    missing = required.difference(raw.columns)
    if missing:
        raise ValueError(f"REITs scale response is missing fields: {sorted(missing)}")

    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(raw["TRADE_DATE"], format="%Y%m%d", errors="raise"),
            "fund_code": raw["FUND_CODE"].astype("string").str.strip().str.zfill(6),
            "fund_name": raw["FUND_EXPAND_ABBR"].astype("string").str.strip(),
            "shares_10k": pd.to_numeric(
                raw["TOTAL_VOL"].astype("string").str.replace(",", "", regex=False),
                errors="raise",
            ).astype("Float64"),
            "raw_record_json": pd.Series(
                [
                    json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                    for row in records
                ],
                dtype="string",
            ),
        }
    )
    if not frame["fund_code"].str.fullmatch(r"\d{6}", na=False).all():
        raise ValueError("REITs scale response contains an invalid fund code")
    if frame.duplicated(["date", "fund_code"]).any():
        raise ValueError("REITs scale response contains duplicate date + fund_code keys")
    return frame[OUTPUT_COLUMNS].reset_index(drop=True)


def fetch_latest_reits_scale(
    *,
    timeout: tuple[float, float] = (5.0, 30.0),
    request_interval: float = 0.2,
    page_size: int = 100,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """通过 TRADE_DATE=''、MAX_DATE=1 获取接口最新实际数据日期。"""
    return fetch_reits_scale(
        None,
        timeout=timeout,
        request_interval=request_interval,
        page_size=page_size,
        session=session,
    )
