"""上海证券交易所基金成交概况采集。"""

from __future__ import annotations

import json
import time
from datetime import date, datetime
from typing import Any, Literal

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.utils.jsonp import unwrap_jsonp


QUERY_URL = "https://query.sse.com.cn/commonQuery.do"
PRODUCT_CODES = "05,13,16,14,15,12"
FUND_TYPE = "47"

DAILY_CURRENT_SQL_ID = "COMMON_SSE_SJ_GPSJ_CJGK_MRGK_C"
DAILY_HISTORY_SQL_ID = "COMMON_SSE_SJ_GPSJ_CJGK_DAYCJGK_C"
WEEKLY_CURRENT_SQL_ID = "COMMON_SSE_SJ_GPSJ_CJGK_MZGK_C"
WEEKLY_HISTORY_SQL_ID = "COMMON_SSE_SJ_GPSJ_CJGK_WEEKCJGK_C"
MONTHLY_HISTORY_SQL_ID = "COMMON_SSE_SJ_GPSJ_CJGK_MONTHCJGK_C"
YEARLY_HISTORY_SQL_ID = "COMMON_SSE_SJ_GPSJ_CJGK_YEARCJGK_C"

Frequency = Literal["daily", "weekly", "monthly", "yearly"]
SourceRoute = Literal[
    "daily_current",
    "daily_history",
    "weekly_current",
    "weekly_history",
    "monthly_history",
    "yearly_history",
]

# verified 表示已验证近期非空数据；partially_verified 表示仅验证到部分旧期间。
ROUTE_SUPPORT: dict[SourceRoute, Literal["verified", "partially_verified"]] = {
    "daily_current": "verified",
    "daily_history": "verified",
    "weekly_current": "verified",
    "weekly_history": "partially_verified",
    "monthly_history": "partially_verified",
    "yearly_history": "partially_verified",
}

OUTPUT_COLUMNS = [
    "frequency",
    "period_key",
    "period_start",
    "period_end",
    "product_code",
    "list_count",
    "trade_volume_100m_shares",
    "trade_amount_100m_cny",
    "market_value_100m_cny",
    "negotiable_value_100m_cny",
    "trading_days",
    "high_trade_volume_100m_shares",
    "high_trade_volume_date",
    "low_trade_volume_100m_shares",
    "low_trade_volume_date",
    "high_trade_amount_100m_cny",
    "high_trade_amount_date",
    "low_trade_amount_100m_cny",
    "low_trade_amount_date",
    "source_route",
    "support_status",
    "raw_record_json",
]

_DATE_COLUMNS = [
    "period_key",
    "period_start",
    "period_end",
    "high_trade_volume_date",
    "low_trade_volume_date",
    "high_trade_amount_date",
    "low_trade_amount_date",
]
_FLOAT_COLUMNS = [
    "trade_volume_100m_shares",
    "trade_amount_100m_cny",
    "market_value_100m_cny",
    "negotiable_value_100m_cny",
    "high_trade_volume_100m_shares",
    "low_trade_volume_100m_shares",
    "high_trade_amount_100m_cny",
    "low_trade_amount_100m_cny",
]


def _make_session(referer: str) -> requests.Session:
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
            "Referer": referer,
        }
    )
    return session


def _normalise_date(value: str | date | datetime, name: str) -> str:
    try:
        return pd.Timestamp(value).date().isoformat()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a valid date") from exc


def _normalise_month(value: str | date | datetime) -> str:
    if isinstance(value, str) and len(value) == 7:
        try:
            return datetime.strptime(value, "%Y-%m").strftime("%Y-%m")
        except ValueError as exc:
            raise ValueError("month must use YYYY-MM format") from exc
    try:
        return pd.Timestamp(value).strftime("%Y-%m")
    except (TypeError, ValueError) as exc:
        raise ValueError("month must use YYYY-MM format") from exc


def _normalise_year(value: str | int | date | datetime) -> str:
    text = str(value) if isinstance(value, int) else None
    if text is None and isinstance(value, str):
        text = value
    if text is not None:
        if len(text) == 4 and text.isdigit() and 1900 <= int(text) <= 2100:
            return text
        raise ValueError("year must use YYYY format")
    return str(pd.Timestamp(value).year)


def _get_jsonp(
    session: requests.Session,
    params: dict[str, Any],
    timeout: tuple[float, float],
) -> tuple[list[dict[str, Any]], str]:
    callback = f"jsonpCallback{time.time_ns()}"
    request_params = {
        "jsonCallBack": callback,
        **params,
        "_": int(time.time() * 1000),
    }
    response = session.get(QUERY_URL, params=request_params, timeout=timeout)
    response.raise_for_status()
    payload = unwrap_jsonp(response.text, expected_callback=callback)
    if not isinstance(payload, dict):
        raise ValueError("SSE turnover JSONP response must contain an object")
    if payload.get("actionErrors"):
        raise RuntimeError(f"SSE API returned errors: {payload['actionErrors']}")
    rows = payload.get("result")
    if not isinstance(rows, list):
        raise ValueError("SSE turnover response has no result list")
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError("SSE turnover result must contain objects")
    return rows, response.url


def _empty_frame() -> pd.DataFrame:
    frame = pd.DataFrame(columns=OUTPUT_COLUMNS)
    for column in _DATE_COLUMNS:
        frame[column] = pd.Series(dtype="datetime64[ns]")
    for column in _FLOAT_COLUMNS:
        frame[column] = pd.Series(dtype="Float64")
    frame["list_count"] = pd.Series(dtype="Int64")
    frame["trading_days"] = pd.Series(dtype="Int64")
    for column in [
        "frequency",
        "product_code",
        "source_route",
        "support_status",
        "raw_record_json",
    ]:
        frame[column] = pd.Series(dtype="string")
    return frame


def _number(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    return float(value)


def _integer(value: Any) -> int | None:
    if value in (None, "", "-"):
        return None
    return int(float(value))


def _date_value(value: Any) -> pd.Timestamp | None:
    if value in (None, "", "-"):
        return None
    return pd.to_datetime(str(value), errors="raise").normalize()


def _common_record(
    raw: dict[str, Any],
    *,
    frequency: Frequency,
    route: SourceRoute,
    period_key: pd.Timestamp,
    period_start: pd.Timestamp,
    period_end: pd.Timestamp,
    product_field: str,
    list_field: str,
    volume_field: str,
    amount_field: str,
    market_value_field: str,
    negotiable_value_field: str,
    trading_days_field: str | None = None,
    high_volume_field: str | None = None,
    high_volume_date_field: str | None = None,
    low_volume_field: str | None = None,
    low_volume_date_field: str | None = None,
    high_amount_field: str | None = None,
    high_amount_date_field: str | None = None,
    low_amount_field: str | None = None,
    low_amount_date_field: str | None = None,
) -> dict[str, Any]:
    def raw_value(field: str | None) -> Any:
        return raw.get(field) if field else None

    return {
        "frequency": frequency,
        "period_key": period_key,
        "period_start": period_start,
        "period_end": period_end,
        "product_code": str(raw[product_field]).strip(),
        "list_count": _integer(raw_value(list_field)),
        "trade_volume_100m_shares": _number(raw_value(volume_field)),
        "trade_amount_100m_cny": _number(raw_value(amount_field)),
        "market_value_100m_cny": _number(raw_value(market_value_field)),
        "negotiable_value_100m_cny": _number(raw_value(negotiable_value_field)),
        "trading_days": _integer(raw_value(trading_days_field)),
        "high_trade_volume_100m_shares": _number(raw_value(high_volume_field)),
        "high_trade_volume_date": _date_value(raw_value(high_volume_date_field)),
        "low_trade_volume_100m_shares": _number(raw_value(low_volume_field)),
        "low_trade_volume_date": _date_value(raw_value(low_volume_date_field)),
        "high_trade_amount_100m_cny": _number(raw_value(high_amount_field)),
        "high_trade_amount_date": _date_value(raw_value(high_amount_date_field)),
        "low_trade_amount_100m_cny": _number(raw_value(low_amount_field)),
        "low_trade_amount_date": _date_value(raw_value(low_amount_date_field)),
        "source_route": route,
        "support_status": ROUTE_SUPPORT[route],
        "raw_record_json": json.dumps(
            raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ),
    }


def _records_to_frame(
    rows: list[dict[str, Any]],
    *,
    frequency: Frequency,
    route: SourceRoute,
    requested_start: str | None = None,
    requested_end: str | None = None,
) -> pd.DataFrame:
    if not rows:
        return _empty_frame()

    records: list[dict[str, Any]] = []
    for raw in rows:
        if route == "daily_current":
            actual = _date_value(raw.get("TRADE_DATE"))
            if actual is None:
                raise ValueError("Daily current row has no TRADE_DATE")
            record = _common_record(
                raw,
                frequency=frequency,
                route=route,
                period_key=actual,
                period_start=actual,
                period_end=actual,
                product_field="PRODUCT_CODE",
                list_field="LIST_NUM",
                volume_field="TRADE_VOL",
                amount_field="TRADE_AMT",
                market_value_field="TOTAL_VALUE",
                negotiable_value_field="NEGO_VALUE",
            )
        elif route == "daily_history":
            actual = _date_value(raw.get("CAL_DATE"))
            if actual is None:
                raise ValueError("Daily history row has no CAL_DATE")
            record = _common_record(
                raw,
                frequency=frequency,
                route=route,
                period_key=actual,
                period_start=actual,
                period_end=actual,
                product_field="PRODUCT_TYPE",
                list_field="TX_NUM",
                volume_field="TX_VOLUME_FULL",
                amount_field="TX_AMOUNT_FULL",
                market_value_field="MKT_VALUE_FULL",
                negotiable_value_field="NEGOTIABLE_VALUE_FULL",
            )
        elif route == "weekly_current":
            actual_end = _date_value(raw.get("END_DATE"))
            if actual_end is None:
                raise ValueError("Weekly current row has no END_DATE")
            start = (
                _date_value(requested_start)
                if requested_start
                else actual_end - pd.Timedelta(days=actual_end.weekday())
            )
            record = _common_record(
                raw,
                frequency=frequency,
                route=route,
                period_key=start,
                period_start=start,
                period_end=actual_end,
                product_field="PRODUCT_CODE",
                list_field="LIST_NUM",
                volume_field="TRADE_VOL",
                amount_field="TRADE_AMT",
                market_value_field="TOTAL_VALUE",
                negotiable_value_field="NEGO_VALUE",
                trading_days_field="WEEK_TRADE_DAYS",
                high_volume_field="HIGH_VOL",
                high_volume_date_field="HIGH_VOL_DATE",
                low_volume_field="LOW_VOL",
                low_volume_date_field="LOW_VOL_DATE",
                high_amount_field="HIGH_AMT",
                high_amount_date_field="HIGH_AMT_DATE",
                low_amount_field="LOW_AMT",
                low_amount_date_field="LOW_AMT_DATE",
            )
        elif route == "weekly_history":
            if requested_start is None or requested_end is None:
                raise ValueError("Weekly history parsing requires requested dates")
            start = _date_value(requested_start)
            end = _date_value(requested_end)
            assert start is not None and end is not None
            record = _common_record(
                raw,
                frequency=frequency,
                route=route,
                period_key=start,
                period_start=start,
                period_end=end,
                product_field="PRODUCT_TYPE",
                list_field="TX_NUM",
                volume_field="TX_VOLUME",
                amount_field="TX_AMOUNT",
                market_value_field="MKT_VALUE",
                negotiable_value_field="NEGOTIABLE_VALUE",
                trading_days_field="TX_DATES",
                high_volume_field="HGH_VOL",
                high_volume_date_field="HGH_VOLD",
                low_volume_field="LOW_VOL",
                low_volume_date_field="LOW_VOLD",
                high_amount_field="HGH_VAL",
                high_amount_date_field="HGH_VALD",
                low_amount_field="LOW_VAL",
                low_amount_date_field="LOW_VALD",
            )
        elif route == "monthly_history":
            month_text = str(raw.get("CAL_DATE_B") or requested_start or "")
            if not month_text:
                raise ValueError("Monthly history row has no CAL_DATE_B")
            start = pd.Timestamp(f"{month_text}-01")
            end = start + pd.offsets.MonthEnd(0)
            record = _common_record(
                raw,
                frequency=frequency,
                route=route,
                period_key=start,
                period_start=start,
                period_end=end,
                product_field="PRODUCT_TYPE",
                list_field="TX_NUM",
                volume_field="TX_VOLUME",
                amount_field="TX_AMOUNT",
                market_value_field="MKT_VALUE",
                negotiable_value_field="NEGOTIABLE_VALUE",
                trading_days_field="TOT_TRD_DATE",
                high_volume_field="MHGH_VOL",
                high_volume_date_field="MHGH_VOLD",
                low_volume_field="MLOW_VOL",
                low_volume_date_field="MLOW_VOLD",
                high_amount_field="MHGH_VAL",
                high_amount_date_field="MHGH_VALD",
                low_amount_field="MLOW_VAL",
                low_amount_date_field="MLOW_VALD",
            )
        else:
            actual_end = _date_value(raw.get("CAL_DATE"))
            if actual_end is None:
                # 年度接口的产品 36 占位行已真实验证为 CAL_DATE=null，
                # 该记录所属年度只能由本次明确的 inYear 请求参数确定。
                if requested_start is None:
                    raise ValueError("Yearly history row has no CAL_DATE or requested year")
                requested_year = _normalise_year(requested_start)
                actual_end = pd.Timestamp(f"{requested_year}-12-31")
            start = pd.Timestamp(year=actual_end.year, month=1, day=1)
            product_field = (
                "PRODUCT_TYPE"
                if raw.get("PRODUCT_TYPE") not in (None, "", "-")
                else "PRODUCT_TYPE_B"
            )
            record = _common_record(
                raw,
                frequency=frequency,
                route=route,
                period_key=start,
                period_start=start,
                period_end=actual_end,
                product_field=product_field,
                list_field="TX_NUM",
                volume_field="YTX_VOLUME",
                amount_field="YTX_AMOUNT",
                market_value_field="MKT_VALUE",
                negotiable_value_field="NEGOTIABLE_VALUE",
                trading_days_field="YTX_DATES",
                high_volume_field="YHGH_VOL",
                high_volume_date_field="YHGH_VOLD",
                low_volume_field="YLOW_VOL",
                low_volume_date_field="YLOW_VOLD",
                high_amount_field="YHGH_VAL",
                high_amount_date_field="YHGH_VALD",
                low_amount_field="YLOW_VAL",
                low_amount_date_field="YLOW_VALD",
            )
        records.append(record)

    frame = pd.DataFrame.from_records(records, columns=OUTPUT_COLUMNS)
    for column in _DATE_COLUMNS:
        frame[column] = pd.to_datetime(frame[column], errors="coerce").dt.normalize()
    for column in _FLOAT_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("Float64")
    frame["list_count"] = pd.to_numeric(frame["list_count"], errors="coerce").astype(
        "Int64"
    )
    frame["trading_days"] = pd.to_numeric(
        frame["trading_days"], errors="coerce"
    ).astype("Int64")
    for column in [
        "frequency",
        "product_code",
        "source_route",
        "support_status",
        "raw_record_json",
    ]:
        frame[column] = frame[column].astype("string")
    return frame


def _fetch(
    params: dict[str, Any],
    *,
    frequency: Frequency,
    route: SourceRoute,
    referer: str,
    requested_start: str | None = None,
    requested_end: str | None = None,
    timeout: tuple[float, float] = (5.0, 30.0),
    session: requests.Session | None = None,
) -> pd.DataFrame:
    client = session or _make_session(referer)
    rows, request_url = _get_jsonp(client, params, timeout)
    frame = _records_to_frame(
        rows,
        frequency=frequency,
        route=route,
        requested_start=requested_start,
        requested_end=requested_end,
    )
    frame.attrs.update(
        request_url=request_url,
        sql_id=params["sqlId"],
        source_route=route,
        support_status=ROUTE_SUPPORT[route],
    )
    return frame


def fetch_daily_turnover(
    query_date: str | date | datetime | None = None,
    *,
    timeout: tuple[float, float] = (5.0, 30.0),
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """查询最近可用日，或通过已验证的历史路由查询指定日期。"""
    if query_date is None:
        return _fetch(
            {
                "sqlId": DAILY_CURRENT_SQL_ID,
                "SEARCH_DATE": "",
                "PRODUCT_CODE": PRODUCT_CODES,
                "type": "inParams",
            },
            frequency="daily",
            route="daily_current",
            referer="https://www.sse.com.cn/market/funddata/overview/day/",
            timeout=timeout,
            session=session,
        )
    query = _normalise_date(query_date, "query_date")
    return _fetch(
        {
            "searchDate": query,
            "sqlId": DAILY_HISTORY_SQL_ID,
            "fundType": FUND_TYPE,
        },
        frequency="daily",
        route="daily_history",
        referer="https://www.sse.com.cn/market/funddata/overview/day/index_his.shtml",
        requested_start=query,
        requested_end=query,
        timeout=timeout,
        session=session,
    )


def fetch_weekly_turnover(
    start_date: str | date | datetime | None = None,
    end_date: str | date | datetime | None = None,
    *,
    source: Literal["current", "history"] | None = None,
    timeout: tuple[float, float] = (5.0, 30.0),
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """查询最近统计周，或通过明确指定的当前/历史路由查询区间。"""
    if (start_date is None) != (end_date is None):
        raise ValueError("start_date and end_date must be provided together")
    if start_date is None:
        if source == "history":
            raise ValueError("Weekly history query requires start_date and end_date")
        return _fetch(
            {
                "sqlId": WEEKLY_CURRENT_SQL_ID,
                "PRODUCT_CODE": PRODUCT_CODES,
                "START_DATE": "",
                "END_DATE": "",
                "type": "inParams",
            },
            frequency="weekly",
            route="weekly_current",
            referer="https://www.sse.com.cn/market/funddata/overview/weekly/",
            timeout=timeout,
            session=session,
        )

    start = _normalise_date(start_date, "start_date")
    end = _normalise_date(end_date, "end_date")
    if start > end:
        raise ValueError("start_date cannot be later than end_date")
    selected_source = source or "history"
    if selected_source == "current":
        return _fetch(
            {
                "sqlId": WEEKLY_CURRENT_SQL_ID,
                "PRODUCT_CODE": PRODUCT_CODES,
                "START_DATE": start,
                "END_DATE": end,
                "type": "inParams",
            },
            frequency="weekly",
            route="weekly_current",
            referer="https://www.sse.com.cn/market/funddata/overview/weekly/",
            requested_start=start,
            requested_end=end,
            timeout=timeout,
            session=session,
        )
    return _fetch(
        {
            "startDate": start,
            "endDate": end,
            "sqlId": WEEKLY_HISTORY_SQL_ID,
            "fundType": FUND_TYPE,
        },
        frequency="weekly",
        route="weekly_history",
        referer="https://www.sse.com.cn/market/funddata/overview/weekly/index_his.shtml",
        requested_start=start,
        requested_end=end,
        timeout=timeout,
        session=session,
    )


def fetch_monthly_turnover(
    month: str | date | datetime,
    *,
    timeout: tuple[float, float] = (5.0, 30.0),
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """查询月度历史接口；目前仅验证到部分旧月份有数据。"""
    month_text = _normalise_month(month)
    return _fetch(
        {"inYear": month_text, "sqlId": MONTHLY_HISTORY_SQL_ID, "fundType": FUND_TYPE},
        frequency="monthly",
        route="monthly_history",
        referer="https://www.sse.com.cn/market/funddata/overview/monthly/index_his.shtml",
        requested_start=month_text,
        timeout=timeout,
        session=session,
    )


def fetch_yearly_turnover(
    year: str | int | date | datetime,
    *,
    timeout: tuple[float, float] = (5.0, 30.0),
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """查询年度历史接口；目前仅验证到部分旧年份有数据。"""
    year_text = _normalise_year(year)
    return _fetch(
        {"inYear": year_text, "sqlId": YEARLY_HISTORY_SQL_ID, "fundType": FUND_TYPE},
        frequency="yearly",
        route="yearly_history",
        referer="https://www.sse.com.cn/market/funddata/overview/yearly/index_his.shtml",
        requested_start=year_text,
        timeout=timeout,
        session=session,
    )
