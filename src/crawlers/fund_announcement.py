"""上海证券交易所基金公告最新清单与历史搜索采集。"""

from __future__ import annotations

import json
import time
from datetime import date as date_type
from datetime import datetime
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.utils.jsonp import unwrap_jsonp


QUERY_URL = "https://query.sse.com.cn/commonQuery.do"
LATEST_JSON_URL = (
    "https://www.sse.com.cn/disclosure/fund/announcement/json/"
    "fund_bulletin_publish_order.json"
)
SQL_ID = "COMMON_PL_JJXX_JJGG_NEW_L"
REFERER = "https://www.sse.com.cn/disclosure/fund/announcement/"
SSE_BASE_URL = "https://www.sse.com.cn"
PERIODIC_BULLETIN_TYPE = "reits03,fund03"
ALL_BULLETIN_TYPES = (
    "reits01,fund01,reits02,fund02,reits03,fund03,reits04,fund04,"
    "reits05,fund05,reits06,fund06"
)
STANDARD_COLUMNS = [
    "announcement_date",
    "fund_code",
    "fund_name",
    "announcement_title",
    "announcement_type",
    "original_announcement_type",
    "pdf_url",
    "source",
    "source_announcement_id",
    "source_route",
    "announcement_key",
    "raw_record_json",
]
# 保留 XBRL -> SSE PDF 匹配模块已经使用的兼容输出。
ANNOUNCEMENT_COLUMNS = [
    "announcementDate",
    "securityCode",
    "fundExpansionAbbr",
    "announcementTitle",
    "bulletinType",
    "originalBulletinType",
    "pdfUrl",
]


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


def normalize_pdf_url(value: object) -> str:
    """将相对公告地址转成稳定的 SSE HTTPS 完整 URL。"""
    text = str(value or "").strip()
    if not text:
        raise ValueError("Fund announcement PDF URL is empty")
    absolute = urljoin(SSE_BASE_URL, text)
    parsed = urlsplit(absolute)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError(f"Unsupported announcement URL scheme: {parsed.scheme!r}")
    if parsed.netloc.lower() != "www.sse.com.cn":
        raise ValueError(f"Unexpected announcement URL host: {parsed.netloc!r}")
    if not parsed.path.lower().endswith(".pdf"):
        raise ValueError(f"Announcement URL is not a PDF: {absolute!r}")
    return urlunsplit(("https", "www.sse.com.cn", parsed.path, parsed.query, ""))


def build_announcement_key(
    source_announcement_id: object, pdf_url: object
) -> str:
    """最新 JSON 优先 discloseId；无来源 ID 的历史记录使用规范化 PDF URL。"""
    if source_announcement_id is not None and not pd.isna(source_announcement_id):
        source_id = str(source_announcement_id).strip()
        if source_id:
            return f"sse:disclose_id:{source_id}"
    return f"sse:pdf_url:{normalize_pdf_url(pdf_url)}"


def _raw_json(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _optional_string(series: pd.Series) -> pd.Series:
    return series.astype("string").str.strip().replace("", pd.NA)


def _empty_standard_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "announcement_date": pd.Series(dtype="datetime64[ns]"),
            "fund_code": pd.Series(dtype="string"),
            "fund_name": pd.Series(dtype="string"),
            "announcement_title": pd.Series(dtype="string"),
            "announcement_type": pd.Series(dtype="string"),
            "original_announcement_type": pd.Series(dtype="string"),
            "pdf_url": pd.Series(dtype="string"),
            "source": pd.Series(dtype="string"),
            "source_announcement_id": pd.Series(dtype="string"),
            "source_route": pd.Series(dtype="string"),
            "announcement_key": pd.Series(dtype="string"),
            "raw_record_json": pd.Series(dtype="string"),
        }
    )


def fetch_latest_fund_announcements(
    *,
    timeout: tuple[float, float] = (5.0, 30.0),
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """读取上交所最新基金公告静态 JSON。"""
    client = session or _make_session()
    response = client.get(
        LATEST_JSON_URL,
        params={"v": int(time.time() * 1000)},
        timeout=timeout,
    )
    response.raise_for_status()
    # 当前服务端 Content-Type 未声明 charset，明确使用 UTF-8 避免 requests 猜成 ISO-8859-1。
    response.encoding = "utf-8"
    try:
        payload = response.json()
    except (requests.JSONDecodeError, ValueError) as exc:
        raise ValueError("SSE latest announcement response is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("SSE latest announcement JSON must contain an object")
    rows = payload.get("publishData")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("SSE latest announcement JSON has no publishData list")
    if not rows:
        return _empty_standard_frame()
    raw = pd.DataFrame.from_records(rows)
    required = {
        "discloseId",
        "discloseDate",
        "bulletinTitle",
        "bulletinClassic",
        "bulletinUrl",
        "securityCode",
        "securityAbbr",
    }
    missing = required.difference(raw.columns)
    if missing:
        raise ValueError(
            f"SSE latest announcement JSON is missing fields: {sorted(missing)}"
        )
    pdf_urls = raw["bulletinUrl"].map(normalize_pdf_url)
    source_ids = _optional_string(raw["discloseId"])
    if source_ids.isna().any():
        raise ValueError("SSE latest announcement JSON contains an empty discloseId")
    frame = pd.DataFrame(
        {
            "announcement_date": pd.to_datetime(
                raw["discloseDate"], format="%Y-%m-%d", errors="raise"
            ),
            "fund_code": _optional_string(raw["securityCode"]),
            "fund_name": _optional_string(raw["securityAbbr"]),
            "announcement_title": _optional_string(raw["bulletinTitle"]),
            "announcement_type": _optional_string(raw["bulletinClassic"]),
            "original_announcement_type": pd.Series(pd.NA, index=raw.index, dtype="string"),
            "pdf_url": pd.Series(pdf_urls, dtype="string"),
            "source": pd.Series("sse", index=raw.index, dtype="string"),
            "source_announcement_id": source_ids,
            "source_route": pd.Series("latest_json", index=raw.index, dtype="string"),
            "announcement_key": pd.Series(
                [build_announcement_key(item, url) for item, url in zip(source_ids, pdf_urls)],
                dtype="string",
            ),
            "raw_record_json": pd.Series([_raw_json(row) for row in rows], dtype="string"),
        }
    )
    return frame[STANDARD_COLUMNS].reset_index(drop=True)


def _normalise_date(value: str | date_type | datetime, field: str) -> str:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a valid date") from exc
    return timestamp.date().isoformat()


def search_fund_announcements(
    start_date: str | date_type | datetime,
    end_date: str | date_type | datetime,
    *,
    title: str = "",
    security_code: str = "",
    bulletin_type: str = ALL_BULLETIN_TYPES,
    page_size: int = 100,
    timeout: tuple[float, float] = (5.0, 30.0),
    request_interval: float = 0.2,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """按已验证参数完整分页查询历史公告。"""
    if page_size <= 0:
        raise ValueError("page_size must be positive")
    if request_interval < 0:
        raise ValueError("request_interval cannot be negative")
    start = _normalise_date(start_date, "start_date")
    end = _normalise_date(end_date, "end_date")
    if start > end:
        raise ValueError("start_date cannot be later than end_date")
    code = str(security_code).strip()
    if code and (not code.isdigit() or len(code) != 6):
        raise ValueError("security_code must be empty or a six-digit string")

    client = session or _make_session()
    page_no = 1
    records: list[dict[str, Any]] = []
    total = 0
    while True:
        if page_no > 1:
            time.sleep(request_interval)
        callback = f"sseAnnouncementCallback{time.time_ns()}"
        params = {
            "jsonCallBack": callback,
            "isPagination": "true",
            "pageHelp.pageSize": page_size,
            "pageHelp.pageNo": page_no,
            "pageHelp.beginPage": page_no,
            "pageHelp.cacheSize": 1,
            "pageHelp.endPage": page_no,
            "type": "inParams",
            "sqlId": SQL_ID,
            "TITLE": str(title).strip(),
            "SECURITY_CODE": code,
            "BULLETIN_TYPE": str(bulletin_type).strip(),
            "OTHER_TYPE": "",
            "START_DATE": start,
            "END_DATE": end,
            "DATE_DESC": "1",
            "DATE_ASC": "",
            "CODE_DESC": "",
            "CODE_ASC": "",
            "_": int(time.time() * 1000),
        }
        response = client.get(QUERY_URL, params=params, timeout=timeout)
        response.raise_for_status()
        payload = unwrap_jsonp(response.text, expected_callback=callback)
        if not isinstance(payload, dict):
            raise ValueError("SSE historical announcement JSONP must contain an object")
        if payload.get("actionErrors"):
            raise RuntimeError(f"SSE announcement API returned errors: {payload['actionErrors']}")
        page_help = payload.get("pageHelp")
        if not isinstance(page_help, dict):
            raise ValueError("SSE announcement response has no pageHelp object")
        rows = page_help.get("data")
        if rows is None and int(page_help.get("total") or 0) == 0:
            rows = []
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ValueError("SSE announcement response has no data object list")
        records.extend(rows)
        current_page = int(page_help.get("pageNo") or page_no)
        page_count = int(page_help.get("pageCount") or 0)
        total = int(page_help.get("total") or 0)
        if not rows or current_page >= page_count or len(records) >= total:
            break
        if current_page < page_no:
            raise RuntimeError("SSE announcement pagination did not advance")
        page_no = current_page + 1

    if not records:
        result = _empty_standard_frame()
        result.attrs.update(api_total=0, pages_requested=page_no)
        return result
    raw = pd.DataFrame.from_records(records)
    required = {
        "SSEDATE",
        "SECURITY_CODE",
        "FUND_EXPANSION_ABBR",
        "TITLE",
        "BULLETIN_TYPE_DESC",
        "ORG_BULLETIN_TYPE_DESC",
        "URL",
    }
    missing = required.difference(raw.columns)
    if missing:
        raise ValueError(f"SSE announcement response is missing fields: {sorted(missing)}")
    pdf_urls = raw["URL"].map(normalize_pdf_url)
    frame = pd.DataFrame(
        {
            "announcement_date": pd.to_datetime(
                raw["SSEDATE"], format="%Y-%m-%d", errors="raise"
            ),
            "fund_code": _optional_string(raw["SECURITY_CODE"]),
            "fund_name": _optional_string(raw["FUND_EXPANSION_ABBR"]),
            "announcement_title": _optional_string(raw["TITLE"]),
            "announcement_type": _optional_string(raw["BULLETIN_TYPE_DESC"]),
            "original_announcement_type": _optional_string(raw["ORG_BULLETIN_TYPE_DESC"]),
            "pdf_url": pd.Series(pdf_urls, dtype="string"),
            "source": pd.Series("sse", index=raw.index, dtype="string"),
            "source_announcement_id": pd.Series(pd.NA, index=raw.index, dtype="string"),
            "source_route": pd.Series("historical_search", index=raw.index, dtype="string"),
            "announcement_key": pd.Series(
                [build_announcement_key(pd.NA, url) for url in pdf_urls], dtype="string"
            ),
            "raw_record_json": pd.Series([_raw_json(record) for record in records], dtype="string"),
        }
    )
    frame = frame.drop_duplicates("announcement_key").reset_index(drop=True)
    frame.attrs.update(api_total=total, pages_requested=page_no)
    return frame[STANDARD_COLUMNS]


def fetch_fund_announcements(
    security_code: str,
    start_date: str,
    end_date: str,
    *,
    bulletin_type: str = PERIODIC_BULLETIN_TYPE,
    page_size: int = 25,
    timeout: tuple[float, float] = (5.0, 30.0),
    request_interval: float = 0.2,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """兼容现有 XBRL 匹配模块的字段命名。"""
    standard = search_fund_announcements(
        start_date,
        end_date,
        security_code=security_code,
        bulletin_type=bulletin_type,
        page_size=page_size,
        timeout=timeout,
        request_interval=request_interval,
        session=session,
    )
    if standard.empty:
        return pd.DataFrame(columns=ANNOUNCEMENT_COLUMNS)
    return pd.DataFrame(
        {
            "announcementDate": standard["announcement_date"].dt.strftime("%Y-%m-%d"),
            "securityCode": standard["fund_code"],
            "fundExpansionAbbr": standard["fund_name"],
            "announcementTitle": standard["announcement_title"],
            "bulletinType": standard["announcement_type"],
            "originalBulletinType": standard["original_announcement_type"],
            "pdfUrl": standard["pdf_url"],
        },
        columns=ANNOUNCEMENT_COLUMNS,
    )
