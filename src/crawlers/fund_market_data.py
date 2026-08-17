"""上交所 ETF、LOF 和公募 REITs 当前行情快照采集。"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


HQ_BASE_URL = "https://yunhq.sse.com.cn:32042/v1/sh1/list"
ETF_URL = f"{HQ_BASE_URL}/exchange/ebs"
LOF_LIST_URL = f"{HQ_BASE_URL}/exchange/lof"
LOF_SELF_URL = f"{HQ_BASE_URL}/self"
REITS_URL = f"{HQ_BASE_URL}/exchange/reits"

REFERERS = {
    "etf": "https://www.sse.com.cn/assortment/fund/etf/market/",
    "lof": "https://www.sse.com.cn/assortment/fund/lof/market/",
    "reits": "https://www.sse.com.cn/assortment/fund/reits/market/",
}
SOURCE_CONFIG = {
    "etf": {
        "url": ETF_URL,
        "fund_type": "ETF",
        "select": (
            "code,name,open,high,low,last,prev_close,chg_rate,volume,amount,"
            "cpxxextendname,tradephase"
        ),
        "fields": (
            "code",
            "name",
            "open",
            "high",
            "low",
            "last",
            "prev_close",
            "chg_rate",
            "volume",
            "amount",
            "cpxxextendname",
            "tradephase",
        ),
    },
    "reits": {
        "url": REITS_URL,
        "fund_type": "REIT",
        "select": (
            "code,cpxxextendname,open,high,low,last,prev_close,chg_rate,volume,amount"
        ),
        "fields": (
            "code",
            "cpxxextendname",
            "open",
            "high",
            "low",
            "last",
            "prev_close",
            "chg_rate",
            "volume",
            "amount",
        ),
    },
}
LOF_DETAIL_FIELDS = (
    "code",
    "name",
    "open",
    "high",
    "low",
    "last",
    "prev_close",
    "chg_rate",
    "volume",
    "amount",
)
LOF_DETAIL_SELECT = ",".join(LOF_DETAIL_FIELDS)
NUMERIC_COLUMNS = [
    "open",
    "high",
    "low",
    "last",
    "prev_close",
    "chg_rate",
    "volume",
    "amount",
]
OUTPUT_COLUMNS = [
    "market",
    "fund_type",
    "fund_code",
    "fund_name",
    "snapshot_time",
    "trade_date",
    *NUMERIC_COLUMNS,
    "trade_phase",
    "source",
    "source_route",
    "observed_at",
    "raw_record_json",
]
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def make_market_session(referer: str) -> requests.Session:
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


def _request_json(
    session: requests.Session,
    url: str,
    *,
    params: dict[str, Any],
    timeout: tuple[float, float],
) -> dict[str, Any]:
    response = session.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    try:
        payload = response.json()
    except (requests.JSONDecodeError, ValueError) as exc:
        raise ValueError("SSE quote response is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("SSE quote response must contain an object")
    if "list" not in payload or not isinstance(payload["list"], list):
        raise ValueError("SSE quote response has no list")
    return payload


def _server_timestamp(
    payload: dict[str, Any], observed_at: pd.Timestamp
) -> tuple[pd.Timestamp, pd.Timestamp, str]:
    date_value = str(payload.get("date") or "").strip()
    time_value = str(payload.get("time") or "").strip().zfill(6)
    try:
        if len(date_value) != 8 or len(time_value) != 6:
            raise ValueError
        parsed = pd.to_datetime(
            date_value + time_value, format="%Y%m%d%H%M%S", errors="raise"
        )
        snapshot = parsed.tz_localize(SHANGHAI_TZ)
        return snapshot, snapshot.normalize().tz_localize(None), "exchange_server"
    except (TypeError, ValueError):
        snapshot = observed_at.tz_convert(SHANGHAI_TZ)
        return snapshot, snapshot.normalize().tz_localize(None), "observed_at"


def _page_records(
    session: requests.Session,
    url: str,
    select: str,
    *,
    timeout: tuple[float, float],
    request_interval: float,
    page_size: int,
) -> tuple[list[list[Any]], list[dict[str, Any]], pd.Timestamp, pd.Timestamp, str]:
    if page_size <= 0:
        raise ValueError("page_size must be positive")
    if request_interval < 0:
        raise ValueError("request_interval cannot be negative")
    begin = 0
    records: list[list[Any]] = []
    envelopes: list[dict[str, Any]] = []
    timestamps: list[pd.Timestamp] = []
    trade_dates: list[pd.Timestamp] = []
    timestamp_sources: set[str] = set()
    expected_total: int | None = None
    while True:
        if begin:
            time.sleep(request_interval)
        observed = pd.Timestamp(datetime.now(timezone.utc))
        payload = _request_json(
            session,
            url,
            params={"select": select, "begin": begin, "end": begin + page_size},
            timeout=timeout,
        )
        rows = payload["list"]
        if not all(isinstance(row, list) for row in rows):
            raise ValueError("SSE quote list must contain arrays")
        total = int(payload.get("total") or 0)
        expected_total = total if expected_total is None else expected_total
        snapshot, trade_date, timestamp_source = _server_timestamp(payload, observed)
        timestamps.append(snapshot)
        trade_dates.append(trade_date)
        timestamp_sources.add(timestamp_source)
        records.extend(rows)
        envelopes.extend(
            {
                "response_date": payload.get("date"),
                "response_time": payload.get("time"),
                "record": row,
            }
            for row in rows
        )
        begin += len(rows)
        if not rows or begin >= total:
            break
    if expected_total is None or len(records) != expected_total:
        raise ValueError(
            f"SSE quote pagination returned {len(records)} rows, expected {expected_total}"
        )
    if not timestamps:
        now = pd.Timestamp(datetime.now(timezone.utc)).tz_convert(SHANGHAI_TZ)
        return records, envelopes, now, now.normalize().tz_localize(None), "observed_at"
    if len(set(trade_dates)) != 1:
        raise ValueError("SSE quote pages returned different trade dates")
    timestamp_source = (
        "exchange_server" if timestamp_sources == {"exchange_server"} else "observed_at"
    )
    return records, envelopes, max(timestamps), trade_dates[0], timestamp_source


def _normalise_records(
    records: list[list[Any]],
    envelopes: list[dict[str, Any]],
    fields: Iterable[str],
    *,
    route: str,
    fund_type: str,
    snapshot_time: pd.Timestamp,
    trade_date: pd.Timestamp,
    observed_at: pd.Timestamp,
) -> pd.DataFrame:
    field_names = tuple(fields)
    if any(len(row) != len(field_names) for row in records):
        raise ValueError(f"{route} quote row does not match requested select fields")
    raw = pd.DataFrame.from_records(records, columns=field_names)
    if raw.empty:
        return _empty_frame()
    if route == "etf":
        expanded = raw["cpxxextendname"].astype("string").str.strip()
        fallback = raw["name"].astype("string").str.strip()
        fund_name = expanded.mask(expanded.isna() | (expanded == ""), fallback)
    elif route == "reits":
        fund_name = raw["cpxxextendname"].astype("string").str.strip()
    else:
        fund_name = raw["name"].astype("string").str.strip()
    frame = pd.DataFrame(
        {
            "market": pd.Series(["SSE"] * len(raw), dtype="string"),
            "fund_type": pd.Series([fund_type] * len(raw), dtype="string"),
            "fund_code": raw["code"].astype("string").str.strip(),
            "fund_name": fund_name,
            "snapshot_time": pd.Series([snapshot_time] * len(raw)),
            "trade_date": pd.Series([trade_date] * len(raw)),
            "trade_phase": (
                raw["tradephase"].astype("string").str.strip()
                if "tradephase" in raw
                else pd.Series([pd.NA] * len(raw), dtype="string")
            ),
            "source": pd.Series(["sse_yunhq"] * len(raw), dtype="string"),
            "source_route": pd.Series([route] * len(raw), dtype="string"),
            "observed_at": pd.Series([observed_at] * len(raw)),
            "raw_record_json": pd.Series(
                [json.dumps(item, ensure_ascii=False, separators=(",", ":")) for item in envelopes],
                dtype="string",
            ),
        }
    )
    for column in NUMERIC_COLUMNS:
        frame[column] = pd.to_numeric(raw[column], errors="coerce").astype("Float64")
    frame.attrs["snapshot_time_source"] = "exchange_server"
    return frame[OUTPUT_COLUMNS].reset_index(drop=True)


def _empty_frame() -> pd.DataFrame:
    data: dict[str, pd.Series] = {
        "market": pd.Series(dtype="string"),
        "fund_type": pd.Series(dtype="string"),
        "fund_code": pd.Series(dtype="string"),
        "fund_name": pd.Series(dtype="string"),
        "snapshot_time": pd.Series(dtype="datetime64[ns, Asia/Shanghai]"),
        "trade_date": pd.Series(dtype="datetime64[ns]"),
        "trade_phase": pd.Series(dtype="string"),
        "source": pd.Series(dtype="string"),
        "source_route": pd.Series(dtype="string"),
        "observed_at": pd.Series(dtype="datetime64[ns, UTC]"),
        "raw_record_json": pd.Series(dtype="string"),
    }
    for column in NUMERIC_COLUMNS:
        data[column] = pd.Series(dtype="Float64")
    return pd.DataFrame(data)[OUTPUT_COLUMNS]


def _fetch_direct_route(
    route: str,
    *,
    timeout: tuple[float, float],
    request_interval: float,
    page_size: int,
    session: requests.Session | None,
) -> pd.DataFrame:
    config = SOURCE_CONFIG[route]
    client = session or make_market_session(REFERERS[route])
    records, envelopes, snapshot, trade_date, timestamp_source = _page_records(
        client,
        str(config["url"]),
        str(config["select"]),
        timeout=timeout,
        request_interval=request_interval,
        page_size=page_size,
    )
    observed_at = pd.Timestamp(datetime.now(timezone.utc))
    frame = _normalise_records(
        records,
        envelopes,
        config["fields"],
        route=route,
        fund_type=str(config["fund_type"]),
        snapshot_time=snapshot,
        trade_date=trade_date,
        observed_at=observed_at,
    )
    frame.attrs["snapshot_time_source"] = timestamp_source
    return frame


def fetch_etf_market_data(
    *,
    timeout: tuple[float, float] = (5.0, 30.0),
    request_interval: float = 0.1,
    page_size: int = 200,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    return _fetch_direct_route(
        "etf",
        timeout=timeout,
        request_interval=request_interval,
        page_size=page_size,
        session=session,
    )


def fetch_reits_market_data(
    *,
    timeout: tuple[float, float] = (5.0, 30.0),
    request_interval: float = 0.1,
    page_size: int = 200,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    return _fetch_direct_route(
        "reits",
        timeout=timeout,
        request_interval=request_interval,
        page_size=page_size,
        session=session,
    )


def fetch_lof_market_data(
    *,
    timeout: tuple[float, float] = (5.0, 30.0),
    request_interval: float = 0.1,
    page_size: int = 200,
    detail_batch_size: int = 50,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    if detail_batch_size <= 0:
        raise ValueError("detail_batch_size must be positive")
    client = session or make_market_session(REFERERS["lof"])
    list_rows, _, _, _, _ = _page_records(
        client,
        LOF_LIST_URL,
        "code,name",
        timeout=timeout,
        request_interval=request_interval,
        page_size=page_size,
    )
    codes = [str(row[0]).strip() for row in list_rows if row]
    records: list[list[Any]] = []
    envelopes: list[dict[str, Any]] = []
    snapshots: list[pd.Timestamp] = []
    trade_dates: list[pd.Timestamp] = []
    timestamp_sources: set[str] = set()
    observed_at = pd.Timestamp(datetime.now(timezone.utc))
    for index in range(0, len(codes), detail_batch_size):
        if index:
            time.sleep(request_interval)
        batch = codes[index : index + detail_batch_size]
        observed = pd.Timestamp(datetime.now(timezone.utc))
        payload = _request_json(
            client,
            f"{LOF_SELF_URL}/{'_'.join(batch)}",
            params={"select": LOF_DETAIL_SELECT},
            timeout=timeout,
        )
        rows = payload["list"]
        if not all(isinstance(row, list) for row in rows):
            raise ValueError("LOF quote detail list must contain arrays")
        snapshot, trade_date, timestamp_source = _server_timestamp(payload, observed)
        snapshots.append(snapshot)
        trade_dates.append(trade_date)
        timestamp_sources.add(timestamp_source)
        records.extend(rows)
        envelopes.extend(
            {
                "response_date": payload.get("date"),
                "response_time": payload.get("time"),
                "record": row,
            }
            for row in rows
        )
    observed_at = pd.Timestamp(datetime.now(timezone.utc))
    if len(records) != len(codes):
        raise ValueError(f"LOF details returned {len(records)} rows for {len(codes)} codes")
    if len(set(trade_dates)) != 1:
        raise ValueError("LOF detail batches returned different trade dates")
    snapshot = max(snapshots) if snapshots else observed_at.tz_convert(SHANGHAI_TZ)
    trade_date = (
        trade_dates[0]
        if trade_dates
        else snapshot.normalize().tz_localize(None)
    )
    frame = _normalise_records(
        records,
        envelopes,
        LOF_DETAIL_FIELDS,
        route="lof",
        fund_type="LOF",
        snapshot_time=snapshot,
        trade_date=trade_date,
        observed_at=observed_at,
    )
    frame.attrs["snapshot_time_source"] = (
        "exchange_server" if timestamp_sources == {"exchange_server"} else "observed_at"
    )
    return frame
