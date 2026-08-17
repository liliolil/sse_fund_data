"""上交所交易型货币市场基金每日申购/赎回限额参数采集。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import requests

from src.crawlers.scale_common import get_jsonp, make_scale_session


QUERY_URL = "https://query.sse.com.cn/commonQuery.do"
REFERER = "https://www.sse.com.cn/assortment/fund/currencyfund/basicinfo/"
SQL_ID = "COMMON_SSE_ZQPZ_JJLB_SSSSHBJJLB_CPJBXX_L"
FUND_TYPE = "30"
NUMERIC_COLUMNS = [
    "buy_limit",
    "buy_limit_sum",
    "sell_limit",
    "sell_limit_sum",
    "single_buy_limit",
    "single_buy_limit_sum",
    "single_sell_limit",
    "single_sell_limit_sum",
]
OUTPUT_COLUMNS = [
    "market",
    "fund_code",
    "fund_name",
    "company_name",
    "file_date",
    "trade_date",
    *NUMERIC_COLUMNS,
    "others",
    "source_num",
    "source",
    "source_route",
    "observed_at",
    "raw_record_json",
]
RAW_TO_STANDARD = {
    "BUY_LIMIT": "buy_limit",
    "BUY_LIMIT_SUM": "buy_limit_sum",
    "SELL_LIMIT": "sell_limit",
    "SELL_LIMIT_SUM": "sell_limit_sum",
    "ONEBUY_LIMIT": "single_buy_limit",
    "ONEBUY_LIMIT_SUM": "single_buy_limit_sum",
    "ONESELL_LIMIT": "single_sell_limit",
    "ONESELL_LIMIT_SUM": "single_sell_limit_sum",
}


def _empty_frame() -> pd.DataFrame:
    data: dict[str, pd.Series] = {
        "market": pd.Series(dtype="string"),
        "fund_code": pd.Series(dtype="string"),
        "fund_name": pd.Series(dtype="string"),
        "company_name": pd.Series(dtype="string"),
        "file_date": pd.Series(dtype="datetime64[ns]"),
        "trade_date": pd.Series(dtype="datetime64[ns]"),
        "others": pd.Series(dtype="string"),
        "source_num": pd.Series(dtype="string"),
        "source": pd.Series(dtype="string"),
        "source_route": pd.Series(dtype="string"),
        "observed_at": pd.Series(dtype="datetime64[ns, UTC]"),
        "raw_record_json": pd.Series(dtype="string"),
    }
    for column in NUMERIC_COLUMNS:
        data[column] = pd.Series(dtype="Float64")
    return pd.DataFrame(data)[OUTPUT_COLUMNS]


def _numeric_series(series: pd.Series) -> pd.Series:
    cleaned = series.astype("string").str.strip().str.replace(",", "", regex=False)
    cleaned = cleaned.mask(cleaned.isin(["", "-", "--", "N/A", "n/a"]))
    # 特殊文字保留在 raw_record_json 中；标准数值列保持缺失，绝不转为 0。
    return pd.to_numeric(cleaned, errors="coerce").astype("Float64")


def fetch_money_fund_redemption_params(
    *,
    timeout: tuple[float, float] = (5.0, 30.0),
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """获取接口当前公布的每日申购/赎回限额参数快照。"""
    client = session or make_scale_session(REFERER)
    payload = get_jsonp(
        client,
        QUERY_URL,
        {
            "isPagination": "false",
            "sqlId": SQL_ID,
            "FUND_TYPE": FUND_TYPE,
        },
        timeout,
    )
    records = payload.get("result")
    if not isinstance(records, list):
        raise ValueError("Money fund redemption response has no result list")
    if not records:
        return _empty_frame()
    if not all(isinstance(record, dict) for record in records):
        raise ValueError("Money fund redemption result must contain objects")
    raw = pd.DataFrame.from_records(records)
    required = {
        "FUND_CODE",
        "FUND_ABBREVIATION",
        "COMPANY_NAME",
        "FILE_DATE",
        "TRADEDATE",
        "OTHERS",
        *RAW_TO_STANDARD,
    }
    missing = required.difference(raw.columns)
    if missing:
        raise ValueError(
            f"Money fund redemption response is missing fields: {sorted(missing)}"
        )
    observed_at = pd.Timestamp(datetime.now(timezone.utc))
    frame = pd.DataFrame(
        {
            "market": pd.Series(["SSE"] * len(raw), dtype="string"),
            "fund_code": raw["FUND_CODE"].astype("string").str.strip(),
            "fund_name": raw["FUND_ABBREVIATION"].astype("string").str.strip(),
            "company_name": raw["COMPANY_NAME"].astype("string").str.strip(),
            "file_date": pd.to_datetime(
                raw["FILE_DATE"], format="%Y%m%d", errors="raise"
            ),
            "trade_date": pd.to_datetime(raw["TRADEDATE"], errors="raise").dt.normalize(),
            "others": raw["OTHERS"].astype("string").str.strip(),
            # NUM 在部分响应中存在，2026-08-17 的真实响应未返回该键。
            "source_num": (
                raw["NUM"].astype("string").str.strip()
                if "NUM" in raw
                else pd.Series([pd.NA] * len(raw), dtype="string")
            ),
            "source": pd.Series(["sse"] * len(raw), dtype="string"),
            "source_route": pd.Series(
                ["money_fund_redemption_params"] * len(raw), dtype="string"
            ),
            "observed_at": pd.Series(
                [observed_at] * len(raw), dtype="datetime64[ns, UTC]"
            ),
            "raw_record_json": pd.Series(
                [
                    json.dumps(
                        record,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    for record in records
                ],
                dtype="string",
            ),
        }
    )
    for raw_name, standard_name in RAW_TO_STANDARD.items():
        frame[standard_name] = _numeric_series(raw[raw_name])
    return frame[OUTPUT_COLUMNS].reset_index(drop=True)
