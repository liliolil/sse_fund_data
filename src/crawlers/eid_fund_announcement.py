"""证监会 EID 公募基金公告 PDF 元数据查询。"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Mapping

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


SEARCH_URL = "http://eid.csrc.gov.cn/fund/disclose/advanced_search_report.do"
PDF_VIEW_URL = "http://eid.csrc.gov.cn/fund/disclose/instance_show_pdf_id.do"
REFERER = "http://eid.csrc.gov.cn/fund/disclose/index.html"

# uploadInfoId 在这个接口中属于 PDF 公告系统，不能与 XBRL uploadInfoId 混用。
ANNOUNCEMENT_COLUMNS = [
    "pdf_upload_info_id",
    "uploadInfoDetailId",
    "fundCode",
    "fundShortName",
    "reportCode",
    "reportDesp",
    "reportYear",
    "uploadDate",
    "reportSendDate",
    "reportName",
    "tableName",
    "correctionsNum",
    "operationUploadType",
    "attachFileName",
    "attachFilePath",
    "alterType",
    "isShowInfo",
]


@dataclass(frozen=True)
class PdfHttpValidation:
    request_url: str
    final_url: str
    http_status: int
    content_type: str
    content_length: int | None
    actual_size: int
    pdf_header_valid: bool


def make_eid_announcement_session() -> requests.Session:
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


def build_eid_announcement_ao_data(
    report_type_code: str,
    report_year: str | int,
    fund_code: str,
    *,
    display_start: int,
    display_length: int,
    start_date: str | None = None,
    end_date: str | None = None,
    echo: int = 1,
) -> list[dict[str, Any]]:
    """按 EID 当前公告页面的六列 DataTables 结构构造 aoData。"""
    columns = [
        "fundCode",
        "fundId",
        "reportName",
        "organName",
        "reportDesp",
        "reportSendDate",
    ]
    ao_data: list[dict[str, Any]] = [
        {"name": "sEcho", "value": echo},
        {"name": "iColumns", "value": len(columns)},
        {"name": "sColumns", "value": "," * (len(columns) - 1)},
        {"name": "iDisplayStart", "value": display_start},
        {"name": "iDisplayLength", "value": display_length},
    ]
    ao_data.extend(
        {"name": f"mDataProp_{index}", "value": column}
        for index, column in enumerate(columns)
    )
    ao_data.extend(
        [
            {"name": "fundType", "value": ""},
            {"name": "reportType", "value": str(report_type_code)},
            {"name": "reportYear", "value": str(report_year)},
            {"name": "fundCompanyShortName", "value": ""},
            {"name": "fundCode", "value": str(fund_code)},
            {"name": "fundShortName", "value": ""},
            {"name": "startUploadDate", "value": start_date or ""},
            {"name": "endUploadDate", "value": end_date or ""},
        ]
    )
    return ao_data


def fetch_eid_fund_announcements(
    report_type_code: str,
    report_year: str | int,
    fund_code: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    page_size: int = 20,
    timeout: tuple[float, float] = (5.0, 30.0),
    request_interval: float = 0.2,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """按筛选条件完整分页查询 EID PDF 公告元数据。"""
    if page_size <= 0:
        raise ValueError("page_size must be positive")
    if request_interval < 0:
        raise ValueError("request_interval cannot be negative")
    code = str(fund_code).strip()
    if not code:
        raise ValueError("fund_code cannot be empty")

    client = session or make_eid_announcement_session()
    offset = 0
    echo = 1
    pages_requested = 0
    expected_total: int | None = None
    rows: list[dict[str, Any]] = []

    while True:
        ao_data = build_eid_announcement_ao_data(
            report_type_code,
            report_year,
            code,
            display_start=offset,
            display_length=page_size,
            start_date=start_date,
            end_date=end_date,
            echo=echo,
        )
        response = client.get(
            SEARCH_URL,
            params={
                "aoData": json.dumps(
                    ao_data, ensure_ascii=False, separators=(",", ":")
                )
            },
            timeout=timeout,
        )
        response.raise_for_status()
        pages_requested += 1
        payload = response.json()
        page_rows = payload.get("aaData")
        if not isinstance(page_rows, list):
            raise ValueError("EID announcement response has no aaData list")
        total = int(payload.get("iTotalDisplayRecords", payload.get("iTotalRecords", 0)))
        if expected_total is None:
            expected_total = total
        elif total != expected_total:
            raise RuntimeError(
                "EID announcement total changed during pagination: "
                f"{expected_total} -> {total}"
            )
        rows.extend(row for row in page_rows if isinstance(row, dict))
        offset += len(page_rows)
        if offset >= total:
            break
        if not page_rows:
            raise RuntimeError(
                "EID announcement pagination returned an empty page before total"
            )
        time.sleep(request_interval)
        echo += 1

    if not rows:
        result = pd.DataFrame(columns=ANNOUNCEMENT_COLUMNS)
        result.attrs.update(
            api_total_records=expected_total or 0,
            raw_rows_fetched=0,
            pages_requested=pages_requested,
        )
        return result

    raw = pd.DataFrame.from_records(rows)
    required = {
        "uploadInfoId",
        "fundCode",
        "reportCode",
        "reportYear",
        "reportSendDate",
        "reportName",
    }
    missing = required.difference(raw.columns)
    if missing:
        raise ValueError(
            f"EID announcement response is missing fields: {sorted(missing)}"
        )
    raw = raw.rename(columns={"uploadInfoId": "pdf_upload_info_id"})
    for column in ANNOUNCEMENT_COLUMNS:
        if column not in raw:
            raw[column] = pd.NA
    raw["pdf_upload_info_id"] = pd.to_numeric(
        raw["pdf_upload_info_id"], errors="raise"
    ).astype("Int64")
    raw["uploadInfoDetailId"] = pd.to_numeric(
        raw["uploadInfoDetailId"], errors="coerce"
    ).astype("Int64")
    raw["fundCode"] = raw["fundCode"].astype("string").str.strip().str.zfill(6)
    raw_rows_fetched = len(raw)
    result = raw[ANNOUNCEMENT_COLUMNS].drop_duplicates(
        ["pdf_upload_info_id", "uploadInfoDetailId"], keep="last"
    )
    result = result.reset_index(drop=True)
    result.attrs.update(
        api_total_records=expected_total or 0,
        raw_rows_fetched=raw_rows_fetched,
        pages_requested=pages_requested,
    )
    return result


def is_normal_eid_pdf_record(record: Mapping[str, object]) -> bool:
    """只放行页面中已验证的普通 PDF 分支，其他分支留待后续实现。"""
    def has_value(value: object) -> bool:
        return bool(pd.notna(value) and str(value).strip())

    table_value = record.get("tableName")
    table_name = str(table_value).strip().upper() if has_value(table_value) else ""
    corrections = pd.to_numeric(record.get("correctionsNum"), errors="coerce")
    has_corrections = bool(pd.notna(corrections) and int(corrections) > 0)
    has_attachment = bool(
        has_value(record.get("attachFileName"))
        or has_value(record.get("attachFilePath"))
    )
    return table_name == "PDF" and not has_corrections and not has_attachment


def build_normal_eid_pdf_url(record: Mapping[str, object]) -> str | None:
    """普通记录返回真实 PDF URL；特殊记录返回 None，不猜测分支 URL。"""
    if not is_normal_eid_pdf_record(record):
        return None
    pdf_upload_info_id = record.get("pdf_upload_info_id")
    if pd.isna(pdf_upload_info_id) or not str(pdf_upload_info_id).strip():
        return None
    return f"{PDF_VIEW_URL}?instanceid={int(pdf_upload_info_id)}"


def validate_eid_pdf_http(
    pdf_url: str,
    *,
    timeout: tuple[float, float] = (5.0, 30.0),
    session: requests.Session | None = None,
) -> PdfHttpValidation:
    """流式读取 PDF 文件头，不在本地保存文件。"""
    client = session or make_eid_announcement_session()
    response = client.get(
        pdf_url,
        headers={"Range": "bytes=0-63"},
        timeout=timeout,
        allow_redirects=True,
        stream=True,
    )
    try:
        prefix = response.raw.read(8)
        actual_size = len(prefix)
        while True:
            chunk = response.raw.read(64 * 1024)
            if not chunk:
                break
            actual_size += len(chunk)
        content_type = response.headers.get("Content-Type", "")
        length_value = response.headers.get("Content-Range")
        if length_value and "/" in length_value:
            content_length = int(length_value.rsplit("/", 1)[1])
        else:
            header_length = response.headers.get("Content-Length")
            content_length = int(header_length) if header_length else None
        return PdfHttpValidation(
            request_url=pdf_url,
            final_url=response.url,
            http_status=response.status_code,
            content_type=content_type,
            content_length=content_length,
            actual_size=actual_size,
            pdf_header_valid=prefix.startswith(b"%PDF"),
        )
    finally:
        response.close()
