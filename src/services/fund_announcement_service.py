"""上交所基金公告元数据的保存、历史回填和增量服务。"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

import pandas as pd

from src.config.paths import PROCESSED_DATA_DIR, STATE_DIR
from src.crawlers.fund_announcement import (
    STANDARD_COLUMNS,
    build_announcement_key,
    fetch_latest_fund_announcements,
    normalize_pdf_url,
    search_fund_announcements,
)
from src.storage.parquet_store import parquet_exists, read_parquet, save_parquet


DEFAULT_PARQUET_PATH = PROCESSED_DATA_DIR / "fund_announcements.parquet"
DEFAULT_STATE_PATH = STATE_DIR / "fund_announcement_update_state.json"
UPDATE_STATUSES = {"initialized", "updated", "no_update", "needs_reconciliation"}


@dataclass(frozen=True)
class FundAnnouncementUpdateResult:
    status: Literal["initialized", "updated", "no_update", "needs_reconciliation"]
    data: pd.DataFrame
    new_records: int
    latest_remote_date: pd.Timestamp | None
    local_max_date: pd.Timestamp | None
    parquet_written: bool
    path: Path
    state_path: Path


@dataclass(frozen=True)
class FundAnnouncementBackfillResult:
    status: Literal["initialized", "updated", "no_update"]
    data: pd.DataFrame
    new_records: int
    requested_windows: tuple[tuple[str, str], ...]
    empty_windows: tuple[tuple[str, str], ...]
    parquet_written: bool
    path: Path
    state_path: Path


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=STANDARD_COLUMNS)


def validate_fund_announcements(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return _empty_frame()
    missing = set(STANDARD_COLUMNS).difference(frame.columns)
    if missing:
        raise ValueError(f"Fund announcements are missing fields: {sorted(missing)}")
    checked = frame[STANDARD_COLUMNS].copy()
    checked["announcement_date"] = pd.to_datetime(
        checked["announcement_date"], errors="raise"
    ).dt.normalize()
    for column in STANDARD_COLUMNS:
        if column != "announcement_date":
            checked[column] = checked[column].astype("string")
    checked["fund_code"] = checked["fund_code"].str.strip().replace("", pd.NA)
    checked["fund_name"] = checked["fund_name"].str.strip().replace("", pd.NA)
    checked["source_announcement_id"] = (
        checked["source_announcement_id"].str.strip().replace("", pd.NA)
    )
    if checked["announcement_date"].isna().any():
        raise ValueError("Fund announcements contain a missing announcement_date")
    present_codes = checked["fund_code"].dropna()
    if not present_codes.str.fullmatch(r"\d{6}", na=False).all():
        raise ValueError("Fund announcements contain an invalid fund_code")
    if checked["announcement_title"].isna().any() or (
        checked["announcement_title"].str.strip() == ""
    ).any():
        raise ValueError("Fund announcements contain an empty announcement_title")
    checked["pdf_url"] = checked["pdf_url"].map(normalize_pdf_url).astype("string")
    if checked["announcement_key"].isna().any() or (
        checked["announcement_key"].str.strip() == ""
    ).any():
        raise ValueError("Fund announcements contain an empty announcement_key")
    expected_keys = [
        build_announcement_key(source_id, url)
        for source_id, url in zip(
            checked["source_announcement_id"], checked["pdf_url"]
        )
    ]
    if checked["announcement_key"].tolist() != expected_keys:
        raise ValueError("Fund announcements contain an inconsistent announcement_key")
    if not (checked["source"] == "sse").all():
        raise ValueError("Fund announcements contain an invalid source")
    if not checked["source_route"].isin({"latest_json", "historical_search"}).all():
        raise ValueError("Fund announcements contain an invalid source_route")
    if checked["raw_record_json"].isna().any() or (
        checked["raw_record_json"].str.strip() == ""
    ).any():
        raise ValueError("Fund announcements contain an empty raw_record_json")
    if checked.duplicated("announcement_key").any():
        raise ValueError("Fund announcements contain duplicate announcement_key values")
    if checked.duplicated("pdf_url").any():
        raise ValueError("Fund announcements contain duplicate PDF URLs")
    return checked.sort_values(
        ["announcement_date", "fund_code", "announcement_key"],
        na_position="last",
    ).reset_index(drop=True)


def merge_fund_announcements(
    previous: pd.DataFrame, current: pd.DataFrame
) -> pd.DataFrame:
    """按 PDF URL 跨路由合并；同一公告存在最新 JSON 时保留 discloseId 证据。"""
    old = validate_fund_announcements(previous)
    new = validate_fund_announcements(current)
    if old.empty:
        return new
    if new.empty:
        return old
    combined = pd.concat([old, new], ignore_index=True)
    combined["_route_priority"] = combined["source_route"].map(
        {"historical_search": 0, "latest_json": 1}
    )
    combined["_order"] = range(len(combined))
    combined = combined.sort_values(["_route_priority", "_order"])
    combined = combined.drop_duplicates("pdf_url", keep="last")
    combined = combined.drop_duplicates("announcement_key", keep="last")
    return validate_fund_announcements(combined[STANDARD_COLUMNS])


def _write_state(path: str | Path, payload: dict[str, object]) -> None:
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
            json.dump(payload, temporary, ensure_ascii=False, indent=2)
            temporary.write("\n")
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, target)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _date_or_none(frame: pd.DataFrame, operation: str) -> pd.Timestamp | None:
    if frame.empty:
        return None
    return pd.Timestamp(getattr(frame["announcement_date"], operation)())


def _frames_equal(left: pd.DataFrame, right: pd.DataFrame) -> bool:
    return validate_fund_announcements(left).equals(validate_fund_announcements(right))


def _record_state(
    path: str | Path,
    *,
    operation: str,
    status: str,
    latest_remote_date: pd.Timestamp | None,
    local_max_date: pd.Timestamp | None,
    new_records: int,
) -> None:
    if status not in UPDATE_STATUSES:
        raise ValueError(f"Unsupported announcement update status: {status}")
    _write_state(
        path,
        {
            "source": "sse",
            "operation": operation,
            "last_check_time": datetime.now(timezone.utc).isoformat(),
            "latest_remote_date": (
                latest_remote_date.date().isoformat()
                if latest_remote_date is not None
                else None
            ),
            "local_max_date": (
                local_max_date.date().isoformat() if local_max_date is not None else None
            ),
            "new_records": new_records,
            "status": status,
        },
    )


def update_fund_announcements(
    path: str | Path = DEFAULT_PARQUET_PATH,
    *,
    state_path: str | Path = DEFAULT_STATE_PATH,
    fetcher: Callable[[], pd.DataFrame] = fetch_latest_fund_announcements,
) -> FundAnnouncementUpdateResult:
    """使用最新静态 JSON 发现新公告；没有变化时不重写 Parquet。"""
    target = Path(path)
    local = (
        validate_fund_announcements(read_parquet(target))
        if parquet_exists(target)
        else _empty_frame()
    )
    remote = validate_fund_announcements(fetcher())
    latest_remote_date = _date_or_none(remote, "max")
    old_urls = set(local["pdf_url"].astype(str)) if not local.empty else set()
    old_keys = set(local["announcement_key"].astype(str)) if not local.empty else set()
    new_records = int(
        sum(
            url not in old_urls and key not in old_keys
            for url, key in zip(remote["pdf_url"], remote["announcement_key"])
        )
    )
    merged = merge_fund_announcements(local, remote)
    changed = not _frames_equal(local, merged)
    if local.empty and not remote.empty:
        status: Literal["initialized", "updated", "no_update", "needs_reconciliation"] = (
            "initialized"
        )
    elif changed:
        status = "updated"
    else:
        status = "no_update"
    if changed:
        save_parquet(merged, target)
    local_max_date = _date_or_none(merged, "max")
    _record_state(
        state_path,
        operation="incremental",
        status=status,
        latest_remote_date=latest_remote_date,
        local_max_date=local_max_date,
        new_records=new_records,
    )
    return FundAnnouncementUpdateResult(
        status=status,
        data=merged,
        new_records=new_records,
        latest_remote_date=latest_remote_date,
        local_max_date=local_max_date,
        parquet_written=changed,
        path=target,
        state_path=Path(state_path),
    )


def _date_windows(start_date: str, end_date: str) -> tuple[tuple[str, str], ...]:
    try:
        start = pd.Timestamp(start_date).normalize()
        end = pd.Timestamp(end_date).normalize()
    except (TypeError, ValueError) as exc:
        raise ValueError("start_date and end_date must be valid dates") from exc
    if start > end:
        raise ValueError("start_date cannot be later than end_date")
    windows: list[tuple[str, str]] = []
    cursor = start
    # 无代码/关键字时前端限制至多三个月；31 天小窗口兼顾负载和可恢复性。
    while cursor <= end:
        window_end = min(cursor + pd.Timedelta(days=30), end)
        windows.append((cursor.date().isoformat(), window_end.date().isoformat()))
        cursor = window_end + pd.Timedelta(days=1)
    return tuple(windows)


def backfill_fund_announcements(
    start_date: str,
    end_date: str,
    path: str | Path = DEFAULT_PARQUET_PATH,
    *,
    state_path: str | Path = DEFAULT_STATE_PATH,
    fetcher: Callable[[str, str], pd.DataFrame] = search_fund_announcements,
) -> FundAnnouncementBackfillResult:
    """按有限日期窗口分页回填；重复执行以公告键和 PDF URL 幂等合并。"""
    target = Path(path)
    local = (
        validate_fund_announcements(read_parquet(target))
        if parquet_exists(target)
        else _empty_frame()
    )
    windows = _date_windows(start_date, end_date)
    frames: list[pd.DataFrame] = []
    empty_windows: list[tuple[str, str]] = []
    for window_start, window_end in windows:
        frame = validate_fund_announcements(fetcher(window_start, window_end))
        if frame.empty:
            empty_windows.append((window_start, window_end))
        else:
            frames.append(frame)
    remote = (
        validate_fund_announcements(pd.concat(frames, ignore_index=True).drop_duplicates(
            "announcement_key", keep="last"
        ))
        if frames
        else _empty_frame()
    )
    old_urls = set(local["pdf_url"].astype(str)) if not local.empty else set()
    old_keys = set(local["announcement_key"].astype(str)) if not local.empty else set()
    new_records = int(
        sum(
            url not in old_urls and key not in old_keys
            for url, key in zip(remote["pdf_url"], remote["announcement_key"])
        )
    )
    merged = merge_fund_announcements(local, remote)
    changed = not _frames_equal(local, merged)
    if local.empty and not remote.empty:
        status: Literal["initialized", "updated", "no_update"] = "initialized"
    elif changed:
        status = "updated"
    else:
        status = "no_update"
    if changed:
        save_parquet(merged, target)
    _record_state(
        state_path,
        operation="backfill",
        status=status,
        latest_remote_date=_date_or_none(remote, "max"),
        local_max_date=_date_or_none(merged, "max"),
        new_records=new_records,
    )
    return FundAnnouncementBackfillResult(
        status=status,
        data=merged,
        new_records=new_records,
        requested_windows=windows,
        empty_windows=tuple(empty_windows),
        parquet_written=changed,
        path=target,
        state_path=Path(state_path),
    )
