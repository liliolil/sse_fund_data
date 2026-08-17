"""证监会 EID 基金 XBRL 元数据与展示 HTML 采集。"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


SEARCH_URL = "http://eid.csrc.gov.cn/fund/disclose/advanced_search_xbrl.do"
HTML_VIEW_URL = "http://eid.csrc.gov.cn/fund/disclose/instance_html_view.do"
REFERER = "http://eid.csrc.gov.cn/fund/disclose/index.html"
RAW_FIELDS = [
    "reportYear",
    "reportDesp",
    "uploadDate",
    "reportSendDate",
    "uploadInfoId",
    "fundId",
    "fundCode",
    "fundShortName",
    "fundSign",
    "organName",
]
METADATA_COLUMNS = [
    *RAW_FIELDS,
    "reportTypeCode",
    "htmlRequestUrl",
    "htmlFinalUrl",
    "htmlHttpStatus",
    "htmlPath",
    "htmlSize",
]


@dataclass(frozen=True)
class HtmlDownloadResult:
    request_url: str
    final_url: str | None
    http_status: int | None
    file_path: Path
    size: int
    skipped: bool


def make_eid_session() -> requests.Session:
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
    session.mount("http://", HTTPAdapter(max_retries=retry))
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


def build_ao_data(
    report_type_code: str,
    report_year: str | int,
    fund_code: str | None,
    *,
    display_start: int,
    display_length: int,
    echo: int = 1,
    report_send_date_start: str | None = None,
    report_send_date_end: str | None = None,
) -> list[dict[str, Any]]:
    """构造 aoData；接口的 UploadDate 参数实测筛选 reportSendDate。"""
    return [
        {"name": "sEcho", "value": echo},
        {"name": "iColumns", "value": 5},
        {"name": "sColumns", "value": ",,,,"},
        {"name": "iDisplayStart", "value": display_start},
        {"name": "iDisplayLength", "value": display_length},
        {"name": "mDataProp_0", "value": "fundShortName"},
        {"name": "mDataProp_1", "value": "fundCode"},
        {"name": "mDataProp_2", "value": "reportDesp"},
        {"name": "mDataProp_3", "value": "reportSendDate"},
        {"name": "mDataProp_4", "value": "uploadInfoId"},
        {"name": "fundType", "value": ""},
        {"name": "reportTypeCode", "value": str(report_type_code)},
        {"name": "reportYear", "value": str(report_year)},
        {"name": "fundCompanyShortName", "value": ""},
        {"name": "fundCode", "value": "" if fund_code is None else str(fund_code)},
        {"name": "fundShortName", "value": ""},
        {"name": "startUploadDate", "value": report_send_date_start or ""},
        {"name": "endUploadDate", "value": report_send_date_end or ""},
    ]


def fetch_xbrl_metadata(
    report_type_code: str,
    report_year: str | int,
    fund_code: str | None = None,
    *,
    page_size: int = 20,
    timeout: tuple[float, float] = (5.0, 30.0),
    request_interval: float = 0.2,
    session: requests.Session | None = None,
    report_send_date_start: str | None = None,
    report_send_date_end: str | None = None,
) -> pd.DataFrame:
    """分页查询元数据；日期参数按实测语义筛选 reportSendDate。"""
    if page_size <= 0:
        raise ValueError("page_size must be positive")
    if request_interval < 0:
        raise ValueError("request_interval cannot be negative")
    client = session or make_eid_session()
    offset = 0
    echo = 1
    rows: list[dict[str, Any]] = []
    expected_total: int | None = None
    pages_requested = 0

    while True:
        ao_data = build_ao_data(
            report_type_code,
            report_year,
            fund_code,
            display_start=offset,
            display_length=page_size,
            echo=echo,
            report_send_date_start=report_send_date_start,
            report_send_date_end=report_send_date_end,
        )
        response = client.get(
            SEARCH_URL,
            params={
                "aoData": json.dumps(ao_data, ensure_ascii=False, separators=(",", ":"))
            },
            timeout=timeout,
        )
        response.raise_for_status()
        pages_requested += 1
        payload = response.json()
        page_rows = payload.get("aaData")
        if not isinstance(page_rows, list):
            raise ValueError("EID response has no aaData list")
        total = int(payload.get("iTotalDisplayRecords", payload.get("iTotalRecords", 0)))
        total_records = int(payload.get("iTotalRecords", total))
        if expected_total is None:
            expected_total = total
        elif total != expected_total:
            raise RuntimeError(
                f"EID result total changed during pagination: {expected_total} -> {total}"
            )
        rows.extend(item for item in page_rows if isinstance(item, dict))
        offset += len(page_rows)
        if offset >= total:
            break
        if not page_rows:
            raise RuntimeError("EID pagination returned an empty page before total")
        time.sleep(request_interval)
        echo += 1

    if not rows:
        empty = pd.DataFrame(columns=METADATA_COLUMNS)
        empty.attrs.update(
            api_total_records=expected_total or 0,
            api_total_display_records=expected_total or 0,
            raw_rows_fetched=0,
            pages_requested=pages_requested,
        )
        return empty
    frame = pd.DataFrame.from_records(rows)
    missing = set(RAW_FIELDS).difference(frame.columns)
    if missing:
        raise ValueError(f"EID response is missing fields: {sorted(missing)}")
    frame["reportTypeCode"] = str(report_type_code)
    frame["fundCode"] = frame["fundCode"].astype("string")
    raw_rows_fetched = len(frame)
    frame = frame.drop_duplicates("uploadInfoId", keep="last")
    for column in METADATA_COLUMNS:
        if column not in frame:
            frame[column] = pd.NA
    result = frame[METADATA_COLUMNS].reset_index(drop=True)
    result.attrs.update(
        api_total_records=total_records,
        api_total_display_records=expected_total or 0,
        raw_rows_fetched=raw_rows_fetched,
        pages_requested=pages_requested,
    )
    return result


def fetch_xbrl_remote_total(
    report_type_code: str,
    report_year: str | int,
    fund_code: str | None = None,
    *,
    timeout: tuple[float, float] = (5.0, 30.0),
    session: requests.Session | None = None,
) -> int:
    """仅请求无日期条件的第一页，返回远程分区总数。"""
    client = session or make_eid_session()
    ao_data = build_ao_data(
        report_type_code,
        report_year,
        fund_code,
        display_start=0,
        display_length=20,
    )
    response = client.get(
        SEARCH_URL,
        params={
            "aoData": json.dumps(ao_data, ensure_ascii=False, separators=(",", ":"))
        },
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    if "iTotalDisplayRecords" not in payload and "iTotalRecords" not in payload:
        raise ValueError("EID response has no total record count")
    return int(payload.get("iTotalDisplayRecords", payload["iTotalRecords"]))


def is_valid_html_file(path: str | Path) -> bool:
    candidate = Path(path)
    if not candidate.is_file() or candidate.stat().st_size == 0:
        return False
    prefix = candidate.read_bytes()[:4096].lower()
    return b"<html" in prefix or b"<!doctype html" in prefix


def download_xbrl_html(
    upload_info_id: str | int,
    output_dir: str | Path,
    *,
    timeout: tuple[float, float] = (5.0, 60.0),
    session: requests.Session | None = None,
) -> HtmlDownloadResult:
    """下载 EID 生成的展示 HTML；不推测生产原始 XBRL 地址。"""
    instance_id = str(upload_info_id).strip()
    if not instance_id:
        raise ValueError("uploadInfoId cannot be empty")
    request_url = f"{HTML_VIEW_URL}?instanceid={instance_id}"
    target = Path(output_dir) / f"{instance_id}.html"
    if is_valid_html_file(target):
        return HtmlDownloadResult(
            request_url, None, None, target, target.stat().st_size, True
        )

    client = session or make_eid_session()
    response = client.get(request_url, timeout=timeout, allow_redirects=True)
    if response.status_code != 200:
        raise RuntimeError(
            f"EID HTML request returned HTTP {response.status_code}: {request_url}"
        )
    content = response.content
    if not content or b"<html" not in content[:4096].lower():
        raise ValueError(f"EID HTML response is empty or invalid: {request_url}")

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{instance_id}.", suffix=".tmp", dir=target.parent, delete=False
        ) as temporary:
            temporary.write(content)
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, target)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return HtmlDownloadResult(
        request_url,
        response.url,
        response.status_code,
        target,
        len(content),
        False,
    )
