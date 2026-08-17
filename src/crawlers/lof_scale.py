"""上海证券交易所 LOF 基金规模采集。"""

from __future__ import annotations

import json
import time
from datetime import date as date_type
from datetime import datetime
from typing import Any

import pandas as pd
import requests

from src.crawlers.scale_common import (
    fetch_expand_names,
    fetch_paginated_scale_rows,
    make_scale_session,
)


REFERER = "https://www.sse.com.cn/market/funddata/volumn/lofvolumn/"
SQL_ID = "COMMON_SSE_SJ_JJSJ_JJGM_LOFGMTJ_L"
PRODUCT_TYPE = "11,14,15"
OUTPUT_COLUMNS = [
    "date",
    "fund_code",
    "fund_name",
    "shares_10k",
    "product_type",
    "raw_record_json",
]


def _normalise_date(value: str | date_type | datetime | None) -> str:
    if value is None:
        return ""
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("date must be a valid date") from exc
    return timestamp.date().isoformat()


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.Series(dtype="datetime64[ns]"),
            "fund_code": pd.Series(dtype="string"),
            "fund_name": pd.Series(dtype="string"),
            "shares_10k": pd.Series(dtype="Float64"),
            "product_type": pd.Series(dtype="string"),
            "raw_record_json": pd.Series(dtype="string"),
        }
    )


def fetch_lof_scale(
    date: str | date_type | datetime | None = None,
    *,
    timeout: tuple[float, float] = (5.0, 30.0),
    request_interval: float = 0.2,
    page_size: int = 100,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """获取指定日期或最近可用日期的 LOF 规模。"""
    search_date = _normalise_date(date)
    client = session or make_scale_session(REFERER)
    records = fetch_paginated_scale_rows(
        client,
        {
            "sqlId": SQL_ID,
            "PRODUCT_TYPE": PRODUCT_TYPE,
            "SEARCH_DATE": search_date,
            "type": "inParams",
        },
        timeout=timeout,
        request_interval=request_interval,
        page_size=page_size,
    )
    if not records:
        return _empty_frame()

    raw = pd.DataFrame.from_records(records)
    required = {"TRADE_DATE", "FUND_CODE", "INTERNAL_VOL", "PRODUCT_TYPE"}
    missing = required.difference(raw.columns)
    if missing:
        raise ValueError(f"LOF scale response is missing fields: {sorted(missing)}")
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(raw["TRADE_DATE"], format="%Y%m%d", errors="raise"),
            "fund_code": raw["FUND_CODE"].astype("string").str.strip().str.zfill(6),
            "shares_10k": pd.to_numeric(
                raw["INTERNAL_VOL"].astype("string").str.replace(",", "", regex=False),
                errors="raise",
            ).astype("Float64"),
            "product_type": raw["PRODUCT_TYPE"].astype("string").str.strip(),
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
        raise ValueError("LOF scale response contains an invalid fund code")
    if frame.duplicated(["date", "fund_code"]).any():
        raise ValueError("LOF scale response contains duplicate date + fund_code keys")

    time.sleep(request_interval)
    names = fetch_expand_names(
        client,
        frame["fund_code"].tolist(),
        timeout=timeout,
        request_interval=request_interval,
    )
    frame["fund_name"] = frame["fund_code"].map(names).astype("string")
    return frame[OUTPUT_COLUMNS].reset_index(drop=True)
