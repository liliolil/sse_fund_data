"""基金主数据相关 SSE JSONP 接口的共用传输与分页。"""

from __future__ import annotations

import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.utils.jsonp import unwrap_jsonp


QUERY_URL = "https://query.sse.com.cn/commonQuery.do"
SOA_QUERY_URL = "https://query.sse.com.cn/commonSoaQuery.do"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127 Safari/537.36"
)


def make_reference_session(referer: str) -> requests.Session:
    """建立带有限重试及官方 Referer 的低频请求会话。"""
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
    session.headers.update({"User-Agent": USER_AGENT, "Referer": referer})
    return session


def request_jsonp(
    session: requests.Session,
    url: str,
    params: dict[str, Any],
    *,
    timeout: tuple[float, float],
) -> dict[str, Any]:
    """请求并严格校验 JSONP 及 SSE 业务错误。"""
    callback = f"sseFundReferenceCallback{time.time_ns()}"
    request_params = {
        "jsonCallBack": callback,
        **params,
        "_": int(time.time() * 1000),
    }
    response = session.get(url, params=request_params, timeout=timeout)
    response.raise_for_status()
    response.encoding = "utf-8"
    payload = unwrap_jsonp(response.text, expected_callback=callback)
    if not isinstance(payload, dict):
        raise ValueError("SSE JSONP response must contain an object")
    if payload.get("success") is False or str(payload.get("success", "")).lower() == "false":
        raise RuntimeError(
            f"SSE API returned a business error: {payload.get('error') or payload}"
        )
    errors = payload.get("actionErrors")
    if errors:
        raise RuntimeError(f"SSE API returned actionErrors: {errors}")
    if payload.get("error"):
        raise RuntimeError(f"SSE API returned an error: {payload['error']}")
    return payload


def fetch_paginated_result(
    session: requests.Session,
    url: str,
    business_params: dict[str, Any],
    *,
    page_size: int,
    request_interval: float,
    timeout: tuple[float, float],
) -> tuple[list[dict[str, Any]], int, int]:
    """完整读取以顶层 result 返回数据的 SSE 分页接口。"""
    if page_size <= 0:
        raise ValueError("page_size must be positive")
    if request_interval < 0:
        raise ValueError("request_interval cannot be negative")

    records: list[dict[str, Any]] = []
    page_no = 1
    pages_requested = 0
    total = 0
    while True:
        if pages_requested:
            time.sleep(request_interval)
        payload = request_jsonp(
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
            timeout=timeout,
        )
        pages_requested += 1
        page_help = payload.get("pageHelp")
        if not isinstance(page_help, dict):
            raise ValueError("SSE paginated response has no pageHelp object")
        rows = payload.get("result")
        total = int(page_help.get("total") or 0)
        if rows is None and total == 0:
            rows = []
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ValueError("SSE paginated response has no result object list")
        records.extend(rows)
        current_page = int(page_help.get("pageNo") or page_no)
        page_count = int(page_help.get("pageCount") or 0)
        if not rows or current_page >= page_count or len(records) >= total:
            break
        if current_page < page_no:
            raise RuntimeError("SSE pagination did not advance")
        page_no = current_page + 1

    if len(records) != total:
        raise ValueError(
            f"SSE pagination is incomplete: expected {total}, got {len(records)}"
        )
    return records, total, pages_requested
