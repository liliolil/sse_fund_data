"""基金 XBRL 第一阶段元数据、展示 HTML 与 Parquet 流程。"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import pandas as pd

from src.config.paths import PROCESSED_DATA_DIR, RAW_DATA_DIR, STATE_DIR
from src.crawlers.xbrl import (
    METADATA_COLUMNS,
    download_xbrl_html,
    fetch_xbrl_metadata,
    fetch_xbrl_remote_total,
)
from src.storage.parquet_store import parquet_exists, read_parquet, save_parquet


DEFAULT_METADATA_PATH = PROCESSED_DATA_DIR / "xbrl_metadata.parquet"
DEFAULT_HTML_DIR = RAW_DATA_DIR / "xbrl" / "html"
DEFAULT_STATE_PATH = STATE_DIR / "xbrl_update_state.json"
SECOND_QUARTER_REPORT_CODE = "FB030020"
SECOND_QUARTER_REPORT_DESP = "第二季度报告"
HTML_METADATA_COLUMNS = [
    "htmlRequestUrl",
    "htmlFinalUrl",
    "htmlHttpStatus",
    "htmlPath",
    "htmlSize",
]


@dataclass(frozen=True)
class XbrlMetadataUpdateResult:
    status: Literal["up_to_date", "updated", "needs_reconciliation"]
    lookback_start: str
    lookback_end: str
    date_query_requests: int
    new_records: int
    remote_total: int
    local_total: int
    parquet_written: bool
    state_path: Path


def validate_xbrl_metadata(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        raise ValueError("XBRL metadata is empty")
    missing = set(METADATA_COLUMNS).difference(frame.columns)
    if missing:
        raise ValueError(f"XBRL metadata is missing fields: {sorted(missing)}")
    checked = frame[METADATA_COLUMNS].copy()
    checked["uploadInfoId"] = pd.to_numeric(
        checked["uploadInfoId"], errors="raise"
    ).astype("Int64")
    checked["fundId"] = pd.to_numeric(checked["fundId"], errors="coerce").astype(
        "Int64"
    )
    checked["fundCode"] = (
        checked["fundCode"].astype("string").str.strip().replace("", pd.NA)
    )
    checked["fundShortName"] = checked["fundShortName"].astype("string")
    checked["reportYear"] = checked["reportYear"].astype("string").str.strip()
    checked["reportTypeCode"] = checked["reportTypeCode"].astype("string").str.strip()
    if checked["uploadInfoId"].isna().any():
        raise ValueError("XBRL metadata contains an empty uploadInfoId")
    if checked.duplicated("uploadInfoId").any():
        raise ValueError("XBRL metadata contains duplicate uploadInfoId values")
    present_codes = checked["fundCode"].dropna()
    if not present_codes.str.fullmatch(r"\d{6}", na=False).all():
        raise ValueError("XBRL metadata contains an invalid fundCode")
    if not checked["reportYear"].str.fullmatch(r"(?:19|20)\d{2}", na=False).all():
        raise ValueError("XBRL metadata contains an invalid reportYear")
    if not checked["reportTypeCode"].str.fullmatch(r"FB\d{3,6}", na=False).all():
        raise ValueError("XBRL metadata contains an invalid reportTypeCode")
    return checked.sort_values("uploadInfoId").reset_index(drop=True)


def collect_xbrl(
    report_type_code: str,
    report_year: str | int,
    fund_code: str | None = None,
    *,
    metadata_path: str | Path = DEFAULT_METADATA_PATH,
    html_dir: str | Path = DEFAULT_HTML_DIR,
    page_size: int = 20,
    request_interval: float = 0.2,
) -> pd.DataFrame:
    """查询元数据、下载展示 HTML，并合并保存到 Parquet。"""
    current = fetch_xbrl_metadata(
        report_type_code,
        report_year,
        fund_code,
        page_size=page_size,
        request_interval=request_interval,
    )
    if current.empty:
        raise ValueError("EID query returned no XBRL metadata")

    previous = (
        validate_xbrl_metadata(read_parquet(metadata_path))
        if parquet_exists(metadata_path)
        else None
    )
    previous_by_id = (
        previous.set_index("uploadInfoId", drop=False) if previous is not None else None
    )

    for index, row in current.iterrows():
        if index:
            time.sleep(request_interval)
        upload_id = int(row["uploadInfoId"])
        result = download_xbrl_html(upload_id, html_dir)
        current.at[index, "htmlRequestUrl"] = result.request_url
        current.at[index, "htmlPath"] = str(result.file_path)
        current.at[index, "htmlSize"] = result.size
        if result.skipped and previous_by_id is not None and upload_id in previous_by_id.index:
            old = previous_by_id.loc[upload_id]
            current.at[index, "htmlFinalUrl"] = old["htmlFinalUrl"]
            current.at[index, "htmlHttpStatus"] = old["htmlHttpStatus"]
        else:
            current.at[index, "htmlFinalUrl"] = result.final_url
            current.at[index, "htmlHttpStatus"] = result.http_status

    current = validate_xbrl_metadata(current)
    if current["htmlHttpStatus"].isna().any() or not (
        current["htmlHttpStatus"].astype("Int64") == 200
    ).all():
        raise ValueError("XBRL metadata contains an invalid HTML HTTP status")
    if (pd.to_numeric(current["htmlSize"], errors="raise") <= 0).any():
        raise ValueError("XBRL metadata contains an empty HTML file")

    combined = current if previous is None else pd.concat([previous, current], ignore_index=True)
    combined = combined.drop_duplicates("uploadInfoId", keep="last")
    combined = validate_xbrl_metadata(combined)
    save_parquet(combined, metadata_path)
    return current


def collect_xbrl_metadata_only(
    report_type_code: str,
    report_year: str | int,
    fund_code: str | None = None,
    *,
    metadata_path: str | Path = DEFAULT_METADATA_PATH,
    page_size: int = 100,
    request_interval: float = 0.2,
    expected_report_desp: str | None = None,
) -> pd.DataFrame:
    """全量分页采集一个筛选分区的元数据，不下载展示 HTML。"""
    if expected_report_desp is None and report_type_code == SECOND_QUARTER_REPORT_CODE:
        expected_report_desp = SECOND_QUARTER_REPORT_DESP

    current = fetch_xbrl_metadata(
        report_type_code,
        report_year,
        fund_code,
        page_size=page_size,
        request_interval=request_interval,
    )
    api_total = int(current.attrs.get("api_total_display_records", -1))
    raw_count = int(current.attrs.get("raw_rows_fetched", -1))
    if current.empty:
        raise ValueError("EID query returned no XBRL metadata")
    if raw_count != api_total or len(current) != api_total:
        raise ValueError(
            f"Incomplete EID pagination: API total={api_total}, raw={raw_count}, "
            f"unique={len(current)}"
        )

    current = validate_xbrl_metadata(current)
    expected_year = str(report_year)
    if not (current["reportYear"] == expected_year).all():
        raise ValueError(f"EID response contains a reportYear other than {expected_year}")
    if expected_report_desp is not None and not (
        current["reportDesp"] == expected_report_desp
    ).all():
        unexpected = sorted(current.loc[current["reportDesp"] != expected_report_desp, "reportDesp"].astype(str).unique())
        raise ValueError(f"Unexpected reportDesp values: {unexpected}")

    previous = (
        validate_xbrl_metadata(read_parquet(metadata_path))
        if parquet_exists(metadata_path)
        else None
    )
    if previous is not None:
        old_html = previous.set_index("uploadInfoId")[HTML_METADATA_COLUMNS]
        for column in HTML_METADATA_COLUMNS:
            preserved = current["uploadInfoId"].map(old_html[column])
            missing_values = current[column].isna()
            current.loc[missing_values, column] = preserved.loc[missing_values]
        combined = pd.concat([previous, current], ignore_index=True)
        combined = combined.drop_duplicates("uploadInfoId", keep="last")
    else:
        combined = current
    combined = validate_xbrl_metadata(combined)
    save_parquet(combined, metadata_path)

    current.attrs.update(
        api_total_records=int(current.attrs.get("api_total_records", api_total)),
        api_total_display_records=api_total,
        raw_rows_fetched=raw_count,
    )
    return current


def _write_update_state(path: str | Path, state: dict[str, object]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=f".{target.stem}.",
            suffix=".tmp",
            dir=target.parent,
            delete=False,
        ) as temporary:
            json.dump(state, temporary, ensure_ascii=False, indent=2)
            temporary.write("\n")
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, target)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def update_xbrl_metadata(
    report_type_code: str,
    report_year: str | int,
    lookback_days: int = 7,
    *,
    metadata_path: str | Path = DEFAULT_METADATA_PATH,
    state_path: str | Path = DEFAULT_STATE_PATH,
    as_of_date: str | date | None = None,
    request_interval: float = 0.2,
) -> XbrlMetadataUpdateResult:
    """按 reportSendDate 回看增量，并以远程总数做轻量完整性对账。"""
    if lookback_days <= 0:
        raise ValueError("lookback_days must be positive")
    end = pd.Timestamp(as_of_date or date.today()).normalize()
    start = end - timedelta(days=lookback_days - 1)
    lookback_start = start.date().isoformat()
    lookback_end = end.date().isoformat()
    year_text = str(report_year)

    if parquet_exists(metadata_path):
        local = validate_xbrl_metadata(read_parquet(metadata_path))
    else:
        local = pd.DataFrame(columns=METADATA_COLUMNS)
    if local.empty:
        local_ids: set[int] = set()
    else:
        local_partition = local[
            (local["reportTypeCode"] == report_type_code)
            & (local["reportYear"] == year_text)
        ]
        local_ids = set(local_partition["uploadInfoId"].astype(int))

    # 参数名为 start/endUploadDate，但真实接口验证其筛选 reportSendDate。
    recent = fetch_xbrl_metadata(
        report_type_code,
        report_year,
        None,
        request_interval=request_interval,
        report_send_date_start=lookback_start,
        report_send_date_end=lookback_end,
    )
    date_query_requests = int(recent.attrs.get("pages_requested", 1))
    if recent.empty:
        new_rows = recent
    else:
        recent = validate_xbrl_metadata(recent)
        if not (
            (recent["reportTypeCode"] == report_type_code)
            & (recent["reportYear"] == year_text)
        ).all():
            raise ValueError("Date query returned metadata outside the requested partition")
        new_rows = recent[~recent["uploadInfoId"].astype(int).isin(local_ids)].copy()

    parquet_written = not new_rows.empty
    if parquet_written:
        combined = new_rows if local.empty else pd.concat([local, new_rows], ignore_index=True)
        combined = combined.drop_duplicates("uploadInfoId", keep="first")
        combined = validate_xbrl_metadata(combined)
        save_parquet(combined, metadata_path)
        local = combined

    if local.empty:
        local_total = 0
    else:
        final_partition = local[
            (local["reportTypeCode"] == report_type_code)
            & (local["reportYear"] == year_text)
        ]
        local_total = int(final_partition["uploadInfoId"].nunique())

    remote_total = fetch_xbrl_remote_total(report_type_code, report_year, None)
    new_count = len(new_rows)
    if remote_total == local_total:
        status: Literal["up_to_date", "updated", "needs_reconciliation"] = (
            "updated" if new_count else "up_to_date"
        )
    else:
        status = "needs_reconciliation"

    state = {
        "reportTypeCode": report_type_code,
        "reportYear": year_text,
        "last_check_time": datetime.now(timezone.utc).isoformat(),
        "lookback_start": lookback_start,
        "lookback_end": lookback_end,
        "remote_total": remote_total,
        "local_total": local_total,
        "new_records": new_count,
        "status": status,
    }
    _write_update_state(state_path, state)
    return XbrlMetadataUpdateResult(
        status=status,
        lookback_start=lookback_start,
        lookback_end=lookback_end,
        date_query_requests=date_query_requests,
        new_records=new_count,
        remote_total=remote_total,
        local_total=local_total,
        parquet_written=parquet_written,
        state_path=Path(state_path),
    )
