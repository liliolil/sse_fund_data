"""ETF 规模数据初始化与基础增量更新流程。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

import pandas as pd

from src.config.paths import PROCESSED_DATA_DIR
from src.crawlers.etf_scale import OUTPUT_COLUMNS, fetch_etf_scale
from src.storage.parquet_store import parquet_exists, read_parquet, save_parquet


DEFAULT_PARQUET_PATH = PROCESSED_DATA_DIR / "etf_scale.parquet"
PRIMARY_KEY = ["date", "fund_code"]


@dataclass(frozen=True)
class UpdateResult:
    status: Literal["initialized", "updated", "no_update"]
    path: Path
    data: pd.DataFrame
    remote_date: pd.Timestamp


@dataclass(frozen=True)
class BackfillResult:
    status: Literal["backfilled", "no_update"]
    path: Path
    data: pd.DataFrame
    requested_dates: tuple[str, ...]
    skipped_dates: tuple[str, ...]
    non_trading_dates: tuple[str, ...]
    added_dates: tuple[str, ...]
    date_mismatches: tuple[tuple[str, str], ...]


def generate_date_range(start_date: str, end_date: str) -> tuple[str, ...]:
    """生成包含首尾日期的 ISO 日期区间。"""
    try:
        start = pd.Timestamp(start_date).normalize()
        end = pd.Timestamp(end_date).normalize()
    except (TypeError, ValueError) as exc:
        raise ValueError("start_date and end_date must be valid dates") from exc
    if start > end:
        raise ValueError("start_date cannot be later than end_date")
    return tuple(day.date().isoformat() for day in pd.date_range(start, end, freq="D"))


def validate_etf_scale(frame: pd.DataFrame) -> pd.DataFrame:
    """规范化并检查保存前的 ETF 规模数据。"""
    if frame.empty:
        raise ValueError("ETF scale data is empty")
    missing = set(OUTPUT_COLUMNS).difference(frame.columns)
    if missing:
        raise ValueError(f"ETF scale data is missing fields: {sorted(missing)}")

    checked = frame[OUTPUT_COLUMNS].copy()
    checked["date"] = pd.to_datetime(checked["date"], errors="raise").dt.normalize()
    checked["fund_code"] = checked["fund_code"].astype("string").str.strip()
    checked["fund_name"] = checked["fund_name"].astype("string")
    checked["shares_10k"] = pd.to_numeric(checked["shares_10k"], errors="raise")

    if checked["date"].isna().any():
        raise ValueError("ETF scale data contains a missing date")
    if not checked["fund_code"].str.fullmatch(r"\d{6}", na=False).all():
        raise ValueError("ETF scale data contains an invalid fund code")
    if checked["shares_10k"].isna().any():
        raise ValueError("ETF scale data contains a missing shares_10k value")
    if checked.duplicated(PRIMARY_KEY).any():
        raise ValueError("ETF scale data contains duplicate date + fund_code keys")
    return checked.sort_values(PRIMARY_KEY).reset_index(drop=True)


def update_etf_scale(
    path: str | Path = DEFAULT_PARQUET_PATH,
    *,
    fetcher: Callable[[], pd.DataFrame] = fetch_etf_scale,
) -> UpdateResult:
    """用远程最近可用日期初始化或更新本地 ETF 规模 Parquet。"""
    target = Path(path)
    remote = validate_etf_scale(fetcher())
    remote_dates = remote["date"].drop_duplicates()
    if len(remote_dates) != 1:
        raise ValueError("Latest remote response must contain exactly one data date")
    remote_date = remote_dates.iloc[0]

    if not parquet_exists(target):
        save_parquet(remote, target)
        return UpdateResult("initialized", target, remote, remote_date)

    local = validate_etf_scale(read_parquet(target))
    local_latest = local["date"].max()
    if remote_date < local_latest:
        raise ValueError(
            f"Remote latest date {remote_date.date()} is earlier than local latest "
            f"date {local_latest.date()}"
        )
    if remote_date == local_latest:
        return UpdateResult("no_update", target, local, remote_date)

    combined = pd.concat([local, remote], ignore_index=True)
    combined = combined.drop_duplicates(PRIMARY_KEY, keep="last")
    combined = validate_etf_scale(combined)
    if combined["date"].max() != remote_date:
        raise ValueError("Merged ETF scale data has an unexpected latest date")
    save_parquet(combined, target)
    return UpdateResult("updated", target, combined, remote_date)


def backfill_etf_scale(
    start_date: str,
    end_date: str,
    path: str | Path = DEFAULT_PARQUET_PATH,
    *,
    fetcher: Callable[[str], pd.DataFrame] = fetch_etf_scale,
) -> BackfillResult:
    """按自然日查询区间数据，并将尚未保存的实际数据日期追加到 Parquet。"""
    target = Path(path)
    requested_range = generate_date_range(start_date, end_date)
    if parquet_exists(target):
        local = validate_etf_scale(read_parquet(target))
    else:
        local = pd.DataFrame(columns=OUTPUT_COLUMNS)

    known_dates = (
        set(local["date"].dt.date.astype(str)) if not local.empty else set()
    )
    requested: list[str] = []
    skipped: list[str] = []
    non_trading: list[str] = []
    added: list[str] = []
    mismatches: list[tuple[str, str]] = []
    additions: list[pd.DataFrame] = []

    for requested_date in requested_range:
        if requested_date in known_dates:
            skipped.append(requested_date)
            continue

        requested.append(requested_date)
        response = fetcher(requested_date)
        if response.empty:
            # 2026-08-08、08-09 及 05-01 的真实接口验证均为空且无报错。
            non_trading.append(requested_date)
            continue

        checked = validate_etf_scale(response)
        actual_dates = checked["date"].drop_duplicates()
        if len(actual_dates) != 1:
            raise ValueError(
                f"Response for {requested_date} must contain exactly one data date"
            )
        actual_date = actual_dates.iloc[0].date().isoformat()
        if actual_date != requested_date:
            mismatches.append((requested_date, actual_date))
        if actual_date in known_dates:
            skipped.append(requested_date)
            continue

        additions.append(checked)
        known_dates.add(actual_date)
        added.append(actual_date)

    if not additions:
        if local.empty:
            result_data = local.copy()
        else:
            result_data = local
        return BackfillResult(
            "no_update",
            target,
            result_data,
            tuple(requested),
            tuple(skipped),
            tuple(non_trading),
            tuple(added),
            tuple(mismatches),
        )

    frames_to_merge = additions if local.empty else [local, *additions]
    combined = pd.concat(frames_to_merge, ignore_index=True)
    combined = combined.drop_duplicates(PRIMARY_KEY, keep="last")
    combined = validate_etf_scale(combined)
    save_parquet(combined, target)
    return BackfillResult(
        "backfilled",
        target,
        combined,
        tuple(requested),
        tuple(skipped),
        tuple(non_trading),
        tuple(added),
        tuple(mismatches),
    )
