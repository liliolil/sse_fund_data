"""基金成交概况的质量检查、回填、增量更新和状态管理。"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Literal

import pandas as pd

from src.config.paths import PROCESSED_DATA_DIR, STATE_DIR
from src.crawlers.fund_turnover import (
    Frequency,
    OUTPUT_COLUMNS,
    ROUTE_SUPPORT,
    fetch_daily_turnover,
    fetch_monthly_turnover,
    fetch_weekly_turnover,
    fetch_yearly_turnover,
)
from src.storage.parquet_store import parquet_exists, read_parquet, save_parquet


DEFAULT_PATHS: dict[Frequency, Path] = {
    "daily": PROCESSED_DATA_DIR / "fund_turnover_daily.parquet",
    "weekly": PROCESSED_DATA_DIR / "fund_turnover_weekly.parquet",
    "monthly": PROCESSED_DATA_DIR / "fund_turnover_monthly.parquet",
    "yearly": PROCESSED_DATA_DIR / "fund_turnover_yearly.parquet",
}
DEFAULT_STATE_PATH = STATE_DIR / "fund_turnover_update_state.json"
PRIMARY_KEY = ["period_key", "product_code"]
NUMERIC_COLUMNS = [
    "list_count",
    "trade_volume_100m_shares",
    "trade_amount_100m_cny",
    "market_value_100m_cny",
    "negotiable_value_100m_cny",
    "trading_days",
    "high_trade_volume_100m_shares",
    "low_trade_volume_100m_shares",
    "high_trade_amount_100m_cny",
    "low_trade_amount_100m_cny",
]
DATE_COLUMNS = [
    "period_key",
    "period_start",
    "period_end",
    "high_trade_volume_date",
    "low_trade_volume_date",
    "high_trade_amount_date",
    "low_trade_amount_date",
]


@dataclass(frozen=True)
class TurnoverUpdateResult:
    status: Literal["initialized", "updated", "no_update"]
    frequency: Frequency
    path: Path
    state_path: Path
    new_records: int
    latest_data_period: str | None
    parquet_written: bool
    data: pd.DataFrame


@dataclass(frozen=True)
class TurnoverBackfillResult:
    status: Literal["backfilled", "no_update"]
    frequency: Frequency
    path: Path
    state_path: Path
    requested_periods: tuple[str, ...]
    skipped_periods: tuple[str, ...]
    empty_periods: tuple[str, ...]
    added_periods: tuple[str, ...]
    data: pd.DataFrame


def _check_frequency(frequency: str) -> Frequency:
    if frequency not in DEFAULT_PATHS:
        raise ValueError("frequency must be daily, weekly, monthly, or yearly")
    return frequency  # type: ignore[return-value]


def validate_fund_turnover(
    frame: pd.DataFrame,
    frequency: Frequency,
    *,
    allow_empty: bool = False,
) -> pd.DataFrame:
    """规范类型并检查一个频率的数据；空响应只有显式允许时才返回。"""
    missing = set(OUTPUT_COLUMNS).difference(frame.columns)
    if missing:
        raise ValueError(f"Fund turnover data is missing fields: {sorted(missing)}")
    if frame.empty:
        if not allow_empty:
            raise ValueError("Fund turnover data is empty")
        return frame[OUTPUT_COLUMNS].copy()

    checked = frame[OUTPUT_COLUMNS].copy()
    checked["frequency"] = checked["frequency"].astype("string").str.strip()
    if not (checked["frequency"] == frequency).all():
        raise ValueError("Fund turnover data contains an unexpected frequency")
    for column in DATE_COLUMNS:
        checked[column] = pd.to_datetime(checked[column], errors="coerce").dt.normalize()
    if checked[["period_key", "period_start", "period_end"]].isna().any().any():
        raise ValueError("Fund turnover data contains an invalid period date")
    if (checked["period_start"] > checked["period_end"]).any():
        raise ValueError("Fund turnover data has period_start after period_end")

    checked["product_code"] = checked["product_code"].astype("string").str.strip()
    if checked["product_code"].isna().any() or (checked["product_code"] == "").any():
        raise ValueError("Fund turnover data contains an empty product_code")
    for column in NUMERIC_COLUMNS:
        checked[column] = pd.to_numeric(checked[column], errors="coerce")
    for column in ["list_count", "trading_days"]:
        checked[column] = checked[column].astype("Int64")
    for column in set(NUMERIC_COLUMNS).difference({"list_count", "trading_days"}):
        checked[column] = checked[column].astype("Float64")

    for column in ["source_route", "support_status", "raw_record_json"]:
        checked[column] = checked[column].astype("string")
        if checked[column].isna().any() or (checked[column] == "").any():
            raise ValueError(f"Fund turnover data contains an empty {column}")
    if checked.duplicated(PRIMARY_KEY).any():
        raise ValueError("Fund turnover data contains duplicate period + product keys")
    return checked.sort_values(PRIMARY_KEY).reset_index(drop=True)


def generate_periods(
    frequency: Frequency, start_date: str | date, end_date: str | date
) -> tuple[pd.Timestamp, ...]:
    """生成回填期键：日、周一、月初或年初。"""
    frequency = _check_frequency(frequency)
    start = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_date).normalize()
    if start > end:
        raise ValueError("start_date cannot be later than end_date")
    if frequency == "daily":
        values = pd.date_range(start, end, freq="D")
    elif frequency == "weekly":
        first = start - pd.Timedelta(days=start.weekday())
        values = pd.date_range(first, end, freq="7D")
    elif frequency == "monthly":
        first = start.replace(day=1)
        values = pd.date_range(first, end, freq="MS")
    else:
        first = pd.Timestamp(year=start.year, month=1, day=1)
        values = pd.date_range(first, end, freq="YS")
    return tuple(pd.Timestamp(value).normalize() for value in values)


def _empty_data() -> pd.DataFrame:
    return pd.DataFrame(columns=OUTPUT_COLUMNS)


def _period_label(frequency: Frequency, period: pd.Timestamp) -> str:
    if frequency == "daily":
        return period.date().isoformat()
    if frequency == "weekly":
        return f"{period.date().isoformat()}/{(period + pd.Timedelta(days=6)).date().isoformat()}"
    if frequency == "monthly":
        return period.strftime("%Y-%m")
    return period.strftime("%Y")


def _fetch_period(frequency: Frequency, period: pd.Timestamp) -> pd.DataFrame:
    if frequency == "daily":
        return fetch_daily_turnover(period.date().isoformat())
    if frequency == "weekly":
        return fetch_weekly_turnover(
            period.date().isoformat(),
            (period + pd.Timedelta(days=6)).date().isoformat(),
            source="history",
        )
    if frequency == "monthly":
        return fetch_monthly_turnover(period.strftime("%Y-%m"))
    return fetch_yearly_turnover(period.strftime("%Y"))


def _latest_fetcher(frequency: Frequency, as_of: pd.Timestamp) -> pd.DataFrame:
    if frequency == "daily":
        return fetch_daily_turnover()
    if frequency == "weekly":
        return fetch_weekly_turnover()
    if frequency == "monthly":
        last_month = as_of.replace(day=1) - pd.Timedelta(days=1)
        return fetch_monthly_turnover(last_month.strftime("%Y-%m"))
    return fetch_yearly_turnover(str(as_of.year - 1))


def _read_state(path: str | Path) -> dict[str, object]:
    target = Path(path)
    if not target.is_file():
        return {"frequencies": {}}
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Fund turnover state must contain a JSON object")
    frequencies = data.setdefault("frequencies", {})
    if not isinstance(frequencies, dict):
        raise ValueError("Fund turnover state frequencies must contain an object")
    return data


def _write_state(path: str | Path, state: dict[str, object]) -> None:
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


def _record_state(
    state_path: str | Path,
    frequency: Frequency,
    *,
    operation: Literal["incremental", "backfill"],
    status: str,
    latest_data_period: str | None,
    new_records: int,
) -> None:
    state = _read_state(state_path)
    frequencies = state["frequencies"]
    assert isinstance(frequencies, dict)
    support_route = {
        ("daily", "incremental"): "daily_current",
        ("daily", "backfill"): "daily_history",
        ("weekly", "incremental"): "weekly_current",
        ("weekly", "backfill"): "weekly_history",
        ("monthly", "incremental"): "monthly_history",
        ("monthly", "backfill"): "monthly_history",
        ("yearly", "incremental"): "yearly_history",
        ("yearly", "backfill"): "yearly_history",
    }[(frequency, operation)]
    frequencies[frequency] = {
        "last_successful_check_time": datetime.now(timezone.utc).isoformat(),
        "latest_data_period": latest_data_period,
        "operation": operation,
        "status": status,
        "new_records": new_records,
        "support_status": ROUTE_SUPPORT[support_route],
    }
    _write_state(state_path, state)


def _latest_label(frame: pd.DataFrame, frequency: Frequency) -> str | None:
    if frame.empty:
        return None
    latest_key = pd.Timestamp(frame["period_key"].max())
    if frequency == "weekly":
        latest_rows = frame[pd.to_datetime(frame["period_key"]) == latest_key]
        latest_end = pd.Timestamp(latest_rows["period_end"].max())
        return f"{latest_key.date().isoformat()}/{latest_end.date().isoformat()}"
    return _period_label(frequency, latest_key)


def backfill_fund_turnover(
    frequency: Frequency,
    start_date: str | date,
    end_date: str | date,
    path: str | Path | None = None,
    *,
    state_path: str | Path = DEFAULT_STATE_PATH,
    fetcher: Callable[[pd.Timestamp], pd.DataFrame] | None = None,
    request_interval: float = 0.2,
) -> TurnoverBackfillResult:
    """按自然周期回填；已有期跳过，空期不覆盖既有 Parquet。"""
    frequency = _check_frequency(frequency)
    if request_interval < 0:
        raise ValueError("request_interval cannot be negative")
    target = Path(path) if path is not None else DEFAULT_PATHS[frequency]
    local = (
        validate_fund_turnover(read_parquet(target), frequency)
        if parquet_exists(target)
        else _empty_data()
    )
    known = (
        set(pd.to_datetime(local["period_key"]).dt.normalize())
        if not local.empty
        else set()
    )
    requested: list[str] = []
    skipped: list[str] = []
    empty: list[str] = []
    added: list[str] = []
    additions: list[pd.DataFrame] = []

    for period in generate_periods(frequency, start_date, end_date):
        label = _period_label(frequency, period)
        if period in known:
            skipped.append(label)
            continue
        if requested:
            time.sleep(request_interval)
        requested.append(label)
        response = (fetcher or (lambda item: _fetch_period(frequency, item)))(period)
        if response.empty:
            empty.append(label)
            continue
        checked = validate_fund_turnover(response, frequency)
        actual_periods = set(checked["period_key"])
        unseen = actual_periods.difference(known)
        if not unseen:
            skipped.append(label)
            continue
        additions.append(checked[checked["period_key"].isin(unseen)])
        known.update(unseen)
        added.extend(sorted(item.date().isoformat() for item in unseen))

    if not additions:
        latest = _latest_label(local, frequency)
        _record_state(
            state_path,
            frequency,
            operation="backfill",
            status="no_update",
            latest_data_period=latest,
            new_records=0,
        )
        return TurnoverBackfillResult(
            "no_update",
            frequency,
            target,
            Path(state_path),
            tuple(requested),
            tuple(skipped),
            tuple(empty),
            tuple(added),
            local,
        )

    combined = pd.concat(([local] if not local.empty else []) + additions, ignore_index=True)
    combined = combined.drop_duplicates(PRIMARY_KEY, keep="last")
    combined = validate_fund_turnover(combined, frequency)
    save_parquet(combined, target)
    _record_state(
        state_path,
        frequency,
        operation="backfill",
        status="backfilled",
        latest_data_period=_latest_label(combined, frequency),
        new_records=sum(len(item) for item in additions),
    )
    return TurnoverBackfillResult(
        "backfilled",
        frequency,
        target,
        Path(state_path),
        tuple(requested),
        tuple(skipped),
        tuple(empty),
        tuple(added),
        combined,
    )


def update_fund_turnover(
    frequency: Frequency,
    path: str | Path | None = None,
    *,
    state_path: str | Path = DEFAULT_STATE_PATH,
    fetcher: Callable[[], pd.DataFrame] | None = None,
    as_of_date: str | date | None = None,
) -> TurnoverUpdateResult:
    """检查一个频率的最近完整数据期，并仅在出现新期时写入。"""
    frequency = _check_frequency(frequency)
    target = Path(path) if path is not None else DEFAULT_PATHS[frequency]
    as_of = pd.Timestamp(as_of_date or date.today()).normalize()
    remote = (fetcher or (lambda: _latest_fetcher(frequency, as_of)))()
    if remote.empty:
        local = (
            validate_fund_turnover(read_parquet(target), frequency)
            if parquet_exists(target)
            else _empty_data()
        )
        latest = _latest_label(local, frequency)
        _record_state(
            state_path,
            frequency,
            operation="incremental",
            status="no_update",
            latest_data_period=latest,
            new_records=0,
        )
        return TurnoverUpdateResult(
            "no_update", frequency, target, Path(state_path), 0, latest, False, local
        )

    remote = validate_fund_turnover(remote, frequency)
    remote_periods = set(remote["period_key"])
    if len(remote_periods) != 1:
        raise ValueError("Latest turnover response must contain exactly one period")
    remote_period = next(iter(remote_periods))
    if not parquet_exists(target):
        save_parquet(remote, target)
        latest = _period_label(frequency, remote_period)
        _record_state(
            state_path,
            frequency,
            operation="incremental",
            status="initialized",
            latest_data_period=latest,
            new_records=len(remote),
        )
        return TurnoverUpdateResult(
            "initialized",
            frequency,
            target,
            Path(state_path),
            len(remote),
            latest,
            True,
            remote,
        )

    local = validate_fund_turnover(read_parquet(target), frequency)
    if remote_period in set(local["period_key"]):
        latest = _latest_label(local, frequency)
        _record_state(
            state_path,
            frequency,
            operation="incremental",
            status="no_update",
            latest_data_period=latest,
            new_records=0,
        )
        return TurnoverUpdateResult(
            "no_update", frequency, target, Path(state_path), 0, latest, False, local
        )

    combined = pd.concat([local, remote], ignore_index=True)
    combined = combined.drop_duplicates(PRIMARY_KEY, keep="last")
    combined = validate_fund_turnover(combined, frequency)
    save_parquet(combined, target)
    latest = _latest_label(combined, frequency)
    _record_state(
        state_path,
        frequency,
        operation="incremental",
        status="updated",
        latest_data_period=latest,
        new_records=len(remote),
    )
    return TurnoverUpdateResult(
        "updated",
        frequency,
        target,
        Path(state_path),
        len(remote),
        latest,
        True,
        combined,
    )
