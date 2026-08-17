"""EID XBRL 元数据与上交所基金公告 PDF 的可解释匹配。"""

from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Iterable, Mapping
from urllib.parse import urlparse

import pandas as pd

from src.config.paths import PROCESSED_DATA_DIR
from src.crawlers.eid_fund_announcement import (
    build_normal_eid_pdf_url,
    fetch_eid_fund_announcements,
)
from src.crawlers.fund_announcement import fetch_fund_announcements
from src.storage.parquet_store import parquet_exists, read_parquet, save_parquet


DEFAULT_LINKS_PATH = PROCESSED_DATA_DIR / "xbrl_pdf_links.parquet"
MATCH_COLUMNS = [
    "uploadInfoId",
    "fundCode",
    "reportTypeCode",
    "reportYear",
    "reportSendDate",
    "announcementDate",
    "announcementTitle",
    "pdfUrl",
    "match_score",
    "match_status",
    "candidate_count",
    "queryStartDate",
    "queryEndDate",
]
LINK_COLUMNS = [
    "xbrl_upload_info_id",
    "pdf_upload_info_id",
    "pdf_upload_info_detail_id",
    "fund_code",
    "report_type_code",
    "report_year",
    "xbrl_report_send_date",
    "pdf_report_send_date",
    "announcement_title",
    "pdf_url",
    "source",
    "match_score",
    "match_status",
    "candidate_count",
    "query_start_date",
    "query_end_date",
]
MATCH_STATUSES = {
    "matched",
    "ambiguous",
    "not_found",
    "requires_special_handling",
}


@dataclass(frozen=True)
class ReportTypeRule:
    description: str
    title_aliases: tuple[str, ...]


REPORT_TYPE_MAPPING: dict[str, ReportTypeRule] = {
    "FB030010": ReportTypeRule("第一季度报告", ("第一季度报告", "第1季度报告")),
    "FB030020": ReportTypeRule("第二季度报告", ("第二季度报告", "第2季度报告")),
    "FB030030": ReportTypeRule("第三季度报告", ("第三季度报告", "第3季度报告")),
    "FB030040": ReportTypeRule("第四季度报告", ("第四季度报告", "第4季度报告")),
    "FB020010": ReportTypeRule("中期报告", ("中期报告", "半年度报告")),
    "FB010010": ReportTypeRule("年度报告", ("年度报告",)),
}


def normalize_title(value: object) -> str:
    """统一全半角、季度数字和标点，保留标题语义字符。"""
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    replacements = {
        "第一季度": "第1季度",
        "第二季度": "第2季度",
        "第三季度": "第3季度",
        "第四季度": "第4季度",
        "半年度报告": "中期报告",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)


def _valid_pdf_url(value: object) -> bool:
    parsed = urlparse(str(value))
    return (
        parsed.scheme == "https"
        and parsed.netloc == "www.sse.com.cn"
        and parsed.path.lower().endswith(".pdf")
    )


def _valid_eid_pdf_url(value: object) -> bool:
    parsed = urlparse(str(value))
    return (
        parsed.scheme == "http"
        and parsed.netloc == "eid.csrc.gov.cn"
        and parsed.path == "/fund/disclose/instance_show_pdf_id.do"
        and parsed.query.startswith("instanceid=")
    )


def _score_candidate(metadata: Mapping[str, object], candidate: pd.Series) -> int:
    rule = REPORT_TYPE_MAPPING[str(metadata["reportTypeCode"])]
    title = normalize_title(candidate["announcementTitle"])
    score = 0
    if str(candidate["securityCode"]) == str(metadata["fundCode"]):
        score += 40
    report_date = pd.Timestamp(metadata["reportSendDate"]).normalize()
    announcement_date = pd.Timestamp(candidate["announcementDate"]).normalize()
    distance = abs((announcement_date - report_date).days)
    score += {0: 25, 1: 15, 2: 8}.get(distance, 0)
    if any(normalize_title(alias) in title for alias in rule.title_aliases):
        score += 20
    if normalize_title(f"{metadata['reportYear']}年") in title:
        score += 10
    if normalize_title(metadata.get("reportDesp", "")) == normalize_title(rule.description):
        score += 5
    return score


def match_candidates(
    metadata: Mapping[str, object], candidates: pd.DataFrame
) -> dict[str, object]:
    """对候选公告评分；最高分并列时返回 ambiguous，不强选。"""
    report_type_code = str(metadata["reportTypeCode"])
    if report_type_code not in REPORT_TYPE_MAPPING:
        raise ValueError(f"Unsupported reportTypeCode: {report_type_code}")
    base = {
        "uploadInfoId": int(metadata["uploadInfoId"]),
        "fundCode": str(metadata["fundCode"]),
        "reportTypeCode": report_type_code,
        "reportYear": str(metadata["reportYear"]),
        "reportSendDate": pd.Timestamp(metadata["reportSendDate"]).date().isoformat(),
        "candidate_count": len(candidates),
    }
    if candidates.empty:
        return {
            **base,
            "announcementDate": pd.NA,
            "announcementTitle": pd.NA,
            "pdfUrl": pd.NA,
            "match_score": 0,
            "match_status": "not_found",
        }

    scored = candidates.copy()
    scored["match_score"] = [
        _score_candidate(metadata, row) for _, row in scored.iterrows()
    ]
    top_score = int(scored["match_score"].max())
    top = scored[scored["match_score"] == top_score]
    if top_score < 80:
        return {
            **base,
            "announcementDate": pd.NA,
            "announcementTitle": pd.NA,
            "pdfUrl": pd.NA,
            "match_score": top_score,
            "match_status": "not_found",
        }
    if len(top) != 1:
        return {
            **base,
            "announcementDate": pd.NA,
            "announcementTitle": pd.NA,
            "pdfUrl": pd.NA,
            "match_score": top_score,
            "match_status": "ambiguous",
        }
    winner = top.iloc[0]
    if not _valid_pdf_url(winner["pdfUrl"]):
        raise ValueError(f"Invalid SSE PDF URL: {winner['pdfUrl']}")
    return {
        **base,
        "announcementDate": str(winner["announcementDate"]),
        "announcementTitle": str(winner["announcementTitle"]),
        "pdfUrl": str(winner["pdfUrl"]),
        "match_score": top_score,
        "match_status": "matched",
    }


def match_xbrl_pdf(
    metadata: Mapping[str, object], *, date_window_days: int = 2
) -> dict[str, object]:
    """先查送出日当天，无候选时才扩大到有限的 ±N 日窗口。"""
    report_date = pd.Timestamp(metadata["reportSendDate"]).normalize()
    exact = report_date.date().isoformat()
    candidates = fetch_fund_announcements(str(metadata["fundCode"]), exact, exact)
    query_start = exact
    query_end = exact
    if candidates.empty and date_window_days:
        query_start = (report_date - timedelta(days=date_window_days)).date().isoformat()
        query_end = (report_date + timedelta(days=date_window_days)).date().isoformat()
        candidates = fetch_fund_announcements(
            str(metadata["fundCode"]), query_start, query_end
        )
    result = match_candidates(metadata, candidates)
    result["queryStartDate"] = query_start
    result["queryEndDate"] = query_end
    return result


def _score_eid_candidate(
    metadata: Mapping[str, object], candidate: pd.Series
) -> int:
    report_type_code = str(metadata["reportTypeCode"])
    rule = REPORT_TYPE_MAPPING[report_type_code]
    title = normalize_title(candidate.get("reportName", ""))
    description = normalize_title(candidate.get("reportDesp", ""))
    score = 0
    if str(candidate.get("fundCode", "")) == str(metadata["fundCode"]):
        score += 30
    if str(candidate.get("reportCode", "")) == report_type_code:
        score += 25
    if str(candidate.get("reportYear", "")) == str(metadata["reportYear"]):
        score += 15
    if pd.Timestamp(candidate.get("reportSendDate")).normalize() == pd.Timestamp(
        metadata["reportSendDate"]
    ).normalize():
        score += 15
    if any(normalize_title(alias) in title for alias in rule.title_aliases) or (
        description == normalize_title(rule.description)
    ):
        score += 15
    return score


def match_eid_pdf_candidates(
    metadata: Mapping[str, object], candidates: pd.DataFrame
) -> dict[str, object]:
    """匹配 EID 的独立 PDF ID；并列候选不强选，特殊分支不猜 URL。"""
    report_type_code = str(metadata["reportTypeCode"])
    if report_type_code not in REPORT_TYPE_MAPPING:
        raise ValueError(f"Unsupported reportTypeCode: {report_type_code}")
    xbrl_upload_info_id = int(metadata["uploadInfoId"])
    base = {
        "xbrl_upload_info_id": xbrl_upload_info_id,
        "pdf_upload_info_id": pd.NA,
        "pdf_upload_info_detail_id": pd.NA,
        "fund_code": str(metadata["fundCode"]),
        "report_type_code": report_type_code,
        "report_year": str(metadata["reportYear"]),
        "xbrl_report_send_date": pd.Timestamp(
            metadata["reportSendDate"]
        ).date().isoformat(),
        "pdf_report_send_date": pd.NA,
        "announcement_title": pd.NA,
        "pdf_url": pd.NA,
        "source": "eid_pdf",
        "candidate_count": len(candidates),
        "query_start_date": pd.NA,
        "query_end_date": pd.NA,
    }
    if candidates.empty:
        return {**base, "match_score": 0, "match_status": "not_found"}

    scored = candidates.copy()
    scored["match_score"] = [
        _score_eid_candidate(metadata, row) for _, row in scored.iterrows()
    ]
    top_score = int(scored["match_score"].max())
    top = scored[scored["match_score"] == top_score]
    if top_score < 90:
        return {**base, "match_score": top_score, "match_status": "not_found"}
    if len(top) != 1:
        return {**base, "match_score": top_score, "match_status": "ambiguous"}

    winner = top.iloc[0]
    result = {
        **base,
        "pdf_upload_info_id": int(winner["pdf_upload_info_id"]),
        "pdf_upload_info_detail_id": (
            pd.NA
            if pd.isna(winner.get("uploadInfoDetailId"))
            else int(winner["uploadInfoDetailId"])
        ),
        "pdf_report_send_date": str(winner.get("reportSendDate", "")),
        "announcement_title": str(winner.get("reportName", "")),
        "match_score": top_score,
    }
    pdf_url = build_normal_eid_pdf_url(winner)
    if pdf_url is None:
        return {
            **result,
            "pdf_url": pd.NA,
            "match_status": "requires_special_handling",
        }
    if not _valid_eid_pdf_url(pdf_url):
        raise ValueError(f"Invalid EID PDF URL: {pdf_url}")
    return {**result, "pdf_url": pdf_url, "match_status": "matched"}


def match_xbrl_to_eid_pdf(metadata: Mapping[str, object]) -> dict[str, object]:
    """以 EID 公告信息 API 为主来源查询并匹配一条 XBRL 元数据。"""
    candidates = fetch_eid_fund_announcements(
        str(metadata["reportTypeCode"]),
        str(metadata["reportYear"]),
        str(metadata["fundCode"]),
    )
    return match_eid_pdf_candidates(metadata, candidates)


def _legacy_sse_links_to_multisource(frame: pd.DataFrame) -> pd.DataFrame:
    """将现有单来源 SSE 表转换为多来源结构，保留历史匹配证据。"""
    required = {
        "uploadInfoId",
        "fundCode",
        "reportTypeCode",
        "reportYear",
        "reportSendDate",
        "announcementDate",
        "announcementTitle",
        "pdfUrl",
        "match_score",
        "match_status",
        "candidate_count",
        "queryStartDate",
        "queryEndDate",
    }
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(
            f"Existing XBRL PDF links have an unsupported schema: {sorted(missing)}"
        )
    return pd.DataFrame(
        {
            "xbrl_upload_info_id": frame["uploadInfoId"],
            "pdf_upload_info_id": pd.NA,
            "pdf_upload_info_detail_id": pd.NA,
            "fund_code": frame["fundCode"],
            "report_type_code": frame["reportTypeCode"],
            "report_year": frame["reportYear"],
            "xbrl_report_send_date": frame["reportSendDate"],
            "pdf_report_send_date": frame["announcementDate"],
            "announcement_title": frame["announcementTitle"],
            "pdf_url": frame["pdfUrl"],
            "source": "sse",
            "match_score": frame["match_score"],
            "match_status": frame["match_status"],
            "candidate_count": frame["candidate_count"],
            "query_start_date": frame["queryStartDate"],
            "query_end_date": frame["queryEndDate"],
        },
        columns=LINK_COLUMNS,
    )


def _normalize_link_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if set(LINK_COLUMNS).issubset(frame.columns):
        normalized = frame[LINK_COLUMNS].copy()
    else:
        normalized = _legacy_sse_links_to_multisource(frame)
    normalized["xbrl_upload_info_id"] = pd.to_numeric(
        normalized["xbrl_upload_info_id"], errors="raise"
    ).astype("Int64")
    for column in ["pdf_upload_info_id", "pdf_upload_info_detail_id"]:
        normalized[column] = pd.to_numeric(
            normalized[column], errors="coerce"
        ).astype("Int64")
    for column in [
        "fund_code",
        "report_type_code",
        "report_year",
        "xbrl_report_send_date",
        "pdf_report_send_date",
        "announcement_title",
        "pdf_url",
        "source",
        "match_status",
        "query_start_date",
        "query_end_date",
    ]:
        normalized[column] = normalized[column].astype("string")
    normalized["fund_code"] = normalized["fund_code"].str.zfill(6)
    normalized["match_score"] = pd.to_numeric(
        normalized["match_score"], errors="raise"
    ).astype("Int64")
    normalized["candidate_count"] = pd.to_numeric(
        normalized["candidate_count"], errors="raise"
    ).astype("Int64")
    if normalized["xbrl_upload_info_id"].isna().any():
        raise ValueError("XBRL PDF links contain an empty xbrl_upload_info_id")
    if normalized["source"].isna().any() or (normalized["source"].str.len() == 0).any():
        raise ValueError("XBRL PDF links contain an empty source")
    if not normalized["match_status"].isin(MATCH_STATUSES).all():
        raise ValueError("XBRL PDF links contain an invalid match_status")
    if normalized.duplicated(["xbrl_upload_info_id", "source"]).any():
        raise ValueError("XBRL PDF links contain a duplicate source-level key")

    matched = normalized[normalized["match_status"] == "matched"]
    for _, row in matched.iterrows():
        if row["source"] == "sse" and not _valid_pdf_url(row["pdf_url"]):
            raise ValueError(f"Invalid SSE PDF URL: {row['pdf_url']}")
        if row["source"] == "eid_pdf" and not _valid_eid_pdf_url(row["pdf_url"]):
            raise ValueError(f"Invalid EID PDF URL: {row['pdf_url']}")
    return normalized.sort_values(
        ["xbrl_upload_info_id", "source"]
    ).reset_index(drop=True)


def save_xbrl_pdf_link_results(
    current: pd.DataFrame, output_path: str | Path = DEFAULT_LINKS_PATH
) -> pd.DataFrame:
    """按 XBRL ID + 来源更新；不同来源并存，同一来源的重跑可替换。"""
    current = _normalize_link_frame(current)
    if parquet_exists(output_path):
        previous = _normalize_link_frame(read_parquet(output_path))
        current_keys = set(
            zip(
                current["xbrl_upload_info_id"].astype(int),
                current["source"].astype(str),
            )
        )
        keep = [
            (int(row.xbrl_upload_info_id), str(row.source)) not in current_keys
            for row in previous.itertuples(index=False)
        ]
        combined = pd.concat([previous.loc[keep], current], ignore_index=True)
    else:
        combined = current
    combined = _normalize_link_frame(combined)
    save_parquet(combined, output_path)
    return current


def match_and_save_eid_pdf_links(
    metadata_rows: Iterable[Mapping[str, object]],
    *,
    output_path: str | Path = DEFAULT_LINKS_PATH,
    request_interval: float = 0.2,
) -> pd.DataFrame:
    if request_interval < 0:
        raise ValueError("request_interval cannot be negative")
    records = []
    for index, row in enumerate(metadata_rows):
        if index:
            time.sleep(request_interval)
        records.append(match_xbrl_to_eid_pdf(row))
    if not records:
        raise ValueError("No XBRL metadata rows were supplied")
    current = pd.DataFrame.from_records(records, columns=LINK_COLUMNS)
    return save_xbrl_pdf_link_results(current, output_path)


def match_and_save_xbrl_pdf_links(
    metadata_rows: Iterable[Mapping[str, object]],
    *,
    output_path: str | Path = DEFAULT_LINKS_PATH,
    date_window_days: int = 2,
) -> pd.DataFrame:
    """保留原 SSE 匹配入口，并将结果写入统一多来源表。"""
    records = [
        match_xbrl_pdf(row, date_window_days=date_window_days) for row in metadata_rows
    ]
    if not records:
        raise ValueError("No XBRL metadata rows were supplied")
    legacy = pd.DataFrame.from_records(records, columns=MATCH_COLUMNS)
    if legacy["uploadInfoId"].isna().any() or legacy.duplicated("uploadInfoId").any():
        raise ValueError("XBRL PDF links contain an invalid uploadInfoId key")
    if not legacy["match_status"].isin({"matched", "ambiguous", "not_found"}).all():
        raise ValueError("XBRL PDF links contain an invalid match_status")
    matched_urls = legacy.loc[legacy["match_status"] == "matched", "pdfUrl"]
    if not matched_urls.map(_valid_pdf_url).all():
        raise ValueError("Matched XBRL PDF links contain an invalid PDF URL")
    current = _legacy_sse_links_to_multisource(legacy)
    return save_xbrl_pdf_link_results(current, output_path)
