"""上海证券交易所 ETF 规模数据采集。"""

from __future__ import annotations

import time
from datetime import date as date_type
from datetime import datetime
from itertools import islice
from typing import Any, Iterable, Iterator

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.utils.jsonp import unwrap_jsonp


QUERY_URL = "https://query.sse.com.cn/commonQuery.do"
EXPAND_NAME_URL = "https://query.sse.com.cn/security/stock/queryExpandName.do"
REFERER = "https://www.sse.com.cn/market/funddata/volumn/etfvolumn/"
SQL_ID = "COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L"
OUTPUT_COLUMNS = ["date", "fund_code", "fund_name", "shares_10k"]


def _make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127 Safari/537.36"
            ),
            "Referer": REFERER,
        }
    )
    return session


def _normalise_date(value: str | date_type | datetime | None) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date_type):
        return value.isoformat()
    if isinstance(value, str):
        try:
            return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
        except ValueError as exc:
            raise ValueError("date must use YYYY-MM-DD format") from exc
    raise TypeError("date must be None, YYYY-MM-DD text, date, or datetime")


def _callback(prefix: str) -> str:
    return f"{prefix}{time.time_ns()}"


def _get_jsonp(
    session: requests.Session,
    url: str,
    params: dict[str, Any],
    timeout: tuple[float, float],
) -> dict[str, Any]:
    callback = _callback("sseCallback")
    request_params = {"jsonCallBack": callback, **params, "_": int(time.time() * 1000)}
    response = session.get(url, params=request_params, timeout=timeout)
    response.raise_for_status()
    data = unwrap_jsonp(response.text, expected_callback=callback)
    if not isinstance(data, dict):
        raise ValueError("SSE JSONP response must contain a JSON object")
    errors = data.get("actionErrors")
    if errors:
        raise RuntimeError(f"SSE API returned errors: {errors}")
    return data


def _chunks(values: Iterable[str], size: int) -> Iterator[list[str]]:
    iterator = iter(values)
    while chunk := list(islice(iterator, size)):
        yield chunk


def _fetch_expand_names(
    session: requests.Session,
    codes: list[str],
    *,
    timeout: tuple[float, float],
    request_interval: float,
    batch_size: int = 100,
) -> dict[str, str]:
    names: dict[str, str] = {}
    for batch_number, batch in enumerate(_chunks(codes, batch_size)):
        if batch_number:
            time.sleep(request_interval)
        data = _get_jsonp(
            session,
            EXPAND_NAME_URL,
            {"secCodes": ",".join(batch)},
            timeout,
        )
        rows = data.get("result")
        if not isinstance(rows, list):
            raise ValueError("Expand-name response has no result list")
        for row in rows:
            if isinstance(row, list) and len(row) >= 2:
                names[str(row[0]).strip().zfill(6)] = str(row[1]).strip()
    return names


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.Series(dtype="datetime64[ns]"),
            "fund_code": pd.Series(dtype="string"),
            "fund_name": pd.Series(dtype="string"),
            "shares_10k": pd.Series(dtype="float64"),
        }
    )


def fetch_etf_scale(
    date: str | date_type | datetime | None = None,
    *,
    timeout: tuple[float, float] = (5.0, 30.0),
    request_interval: float = 0.2,
    page_size: int = 100,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """获取指定日期或最近可用日期的 ETF 规模，返回规范化 DataFrame。"""
    if page_size <= 0:
        raise ValueError("page_size must be positive")
    if request_interval < 0:
        raise ValueError("request_interval cannot be negative")

    stat_date = _normalise_date(date)
    client = session or _make_session()
    records: list[dict[str, Any]] = []
    page_no = 1

    while True:
        if page_no > 1:
            time.sleep(request_interval)
        data = _get_jsonp(
            client,
            QUERY_URL,
            {
                "isPagination": "true",
                "pageHelp.pageSize": page_size,
                "pageHelp.pageNo": page_no,
                "pageHelp.beginPage": page_no,
                "pageHelp.cacheSize": 1,
                "pageHelp.endPage": page_no,
                "sqlId": SQL_ID,
                "STAT_DATE": stat_date,
            },
            timeout,
        )
        page_help = data.get("pageHelp")
        if not isinstance(page_help, dict):
            raise ValueError("Scale response has no pageHelp object")
        rows = page_help.get("data")
        if not isinstance(rows, list):
            raise ValueError("Scale response pageHelp has no data list")
        records.extend(row for row in rows if isinstance(row, dict))

        current_page = int(page_help.get("pageNo") or page_no)
        page_count = int(page_help.get("pageCount") or 0)
        total = int(page_help.get("total") or 0)
        if not rows or current_page >= page_count or len(records) >= total:
            break
        if current_page < page_no:
            raise RuntimeError("SSE pagination did not advance")
        page_no = current_page + 1

    if not records:
        return _empty_frame()

    raw = pd.DataFrame.from_records(records)
    required_source_fields = {"STAT_DATE", "SEC_CODE", "TOT_VOL"}
    missing = required_source_fields.difference(raw.columns)
    if missing:
        raise ValueError(f"Scale response is missing fields: {sorted(missing)}")

    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(raw["STAT_DATE"], format="%Y-%m-%d", errors="raise"),
            "fund_code": raw["SEC_CODE"].astype("string").str.strip().str.zfill(6),
            "shares_10k": pd.to_numeric(raw["TOT_VOL"], errors="raise"),
        }
    )
    invalid_codes = ~frame["fund_code"].str.fullmatch(r"\d{6}", na=False)
    if invalid_codes.any():
        raise ValueError("Scale response contains an invalid fund code")
    if frame.duplicated(["date", "fund_code"]).any():
        raise ValueError("Scale response contains duplicate date + fund_code keys")

    time.sleep(request_interval)
    names = _fetch_expand_names(
        client,
        frame["fund_code"].tolist(),
        timeout=timeout,
        request_interval=request_interval,
    )
    frame["fund_name"] = frame["fund_code"].map(names).astype("string")
    return frame[OUTPUT_COLUMNS].reset_index(drop=True)
