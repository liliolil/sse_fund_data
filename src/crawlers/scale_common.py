"""基金规模页面共用的 HTTP、JSONP 分页和扩位简称能力。"""

from __future__ import annotations

import time
from itertools import islice
from typing import Any, Iterable, Iterator

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.utils.jsonp import unwrap_jsonp


QUERY_URL = "https://query.sse.com.cn/commonQuery.do"
EXPAND_NAME_URL = "https://query.sse.com.cn/security/stock/queryExpandName.do"


def make_scale_session(referer: str) -> requests.Session:
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


def get_jsonp(
    session: requests.Session,
    url: str,
    params: dict[str, Any],
    timeout: tuple[float, float],
) -> dict[str, Any]:
    callback = f"sseCallback{time.time_ns()}"
    request_params = {"jsonCallBack": callback, **params, "_": int(time.time() * 1000)}
    response = session.get(url, params=request_params, timeout=timeout)
    response.raise_for_status()
    payload = unwrap_jsonp(response.text, expected_callback=callback)
    if not isinstance(payload, dict):
        raise ValueError("SSE JSONP response must contain an object")
    if payload.get("actionErrors"):
        raise RuntimeError(f"SSE API returned errors: {payload['actionErrors']}")
    return payload


def fetch_paginated_scale_rows(
    session: requests.Session,
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
    while True:
        if page_no > 1:
            time.sleep(request_interval)
        payload = get_jsonp(
            session,
            QUERY_URL,
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
            raise ValueError("Scale response has no pageHelp object")
        rows = page_help.get("data")
        if rows is None and int(page_help.get("total") or 0) == 0:
            rows = []
        if not isinstance(rows, list):
            raise ValueError("Scale response pageHelp has no data list")
        if not all(isinstance(row, dict) for row in rows):
            raise ValueError("Scale response data must contain objects")
        records.extend(rows)

        current_page = int(page_help.get("pageNo") or page_no)
        page_count = int(page_help.get("pageCount") or 0)
        total = int(page_help.get("total") or 0)
        if not rows or current_page >= page_count or len(records) >= total:
            break
        if current_page < page_no:
            raise RuntimeError("SSE pagination did not advance")
        page_no = current_page + 1
    return records


def _chunks(values: Iterable[str], size: int) -> Iterator[list[str]]:
    iterator = iter(values)
    while chunk := list(islice(iterator, size)):
        yield chunk


def fetch_expand_names(
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
        payload = get_jsonp(
            session,
            EXPAND_NAME_URL,
            {"secCodes": ",".join(batch)},
            timeout,
        )
        rows = payload.get("result")
        if not isinstance(rows, list):
            raise ValueError("Expand-name response has no result list")
        for row in rows:
            if isinstance(row, list) and len(row) >= 2:
                names[str(row[0]).strip().zfill(6)] = str(row[1]).strip()
    return names
