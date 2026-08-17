"""LOF 与交易型货币基金规模共用的存储和日期驱动流程。"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

import pandas as pd

from src.storage.parquet_store import parquet_exists, read_parquet, save_parquet


@dataclass(frozen=True)
class ScaleUpdateResult:
    status: Literal["initialized", "updated", "no_update"]
    path: Path
    state_path: Path
    data: pd.DataFrame
    remote_date: pd.Timestamp | None
    new_records: int
    missing_names: int
    parquet_written: bool


@dataclass(frozen=True)
class ScaleBackfillResult:
    status: Literal["backfilled", "no_update"]
    path: Path
    state_path: Path
    data: pd.DataFrame
    requested_dates: tuple[str, ...]
    skipped_dates: tuple[str, ...]
    empty_dates: tuple[str, ...]
    added_dates: tuple[str, ...]
    date_mismatches: tuple[tuple[str, str], ...]
    missing_names: int
    parquet_written: bool


def generate_date_range(start_date: str, end_date: str) -> tuple[str, ...]:
    try:
        start = pd.Timestamp(start_date).normalize()
        end = pd.Timestamp(end_date).normalize()
    except (TypeError, ValueError) as exc:
        raise ValueError("start_date and end_date must be valid dates") from exc
    if start > end:
        raise ValueError("start_date cannot be later than end_date")
    return tuple(day.date().isoformat() for day in pd.date_range(start, end, freq="D"))


def _read_state(path: str | Path) -> dict[str, object]:
    target = Path(path)
    if not target.is_file():
        return {}
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Scale update state must contain a JSON object")
    return payload


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
    path: str | Path,
    *,
    source: str,
    operation: Literal["incremental", "backfill"],
    status: str,
    latest_data_date: str | None,
    new_records: int,
    missing_names: int,
    requested_start: str | None = None,
    requested_end: str | None = None,
) -> None:
    state = _read_state(path)
    state.update(
        {
            "source": source,
            "last_successful_check_time": datetime.now(timezone.utc).isoformat(),
            "operation": operation,
            "status": status,
            "latest_data_date": latest_data_date,
            "new_records": new_records,
            "missing_names": missing_names,
            "history_boundary": "partially_verified",
        }
    )
    if requested_start is not None:
        state["requested_start"] = requested_start
    else:
        state.pop("requested_start", None)
    if requested_end is not None:
        state["requested_end"] = requested_end
    else:
        state.pop("requested_end", None)
    _write_state(path, state)


def _latest_date(frame: pd.DataFrame) -> str | None:
    if frame.empty:
        return None
    return pd.Timestamp(frame["date"].max()).date().isoformat()


def _missing_names(frame: pd.DataFrame) -> int:
    if frame.empty or "fund_name" not in frame:
        return 0
    names = frame["fund_name"].astype("string")
    return int((names.isna() | (names.str.strip() == "")).sum())


def update_scale(
    *,
    source: str,
    path: str | Path,
    state_path: str | Path,
    fetcher: Callable[[], pd.DataFrame],
    validator: Callable[[pd.DataFrame], pd.DataFrame],
    empty_columns: list[str],
) -> ScaleUpdateResult:
    target = Path(path)
    remote_raw = fetcher()
    if remote_raw.empty:
        local = validator(read_parquet(target)) if parquet_exists(target) else pd.DataFrame(
            columns=empty_columns
        )
        missing = _missing_names(local)
        _record_state(
            state_path,
            source=source,
            operation="incremental",
            status="no_update",
            latest_data_date=_latest_date(local),
            new_records=0,
            missing_names=missing,
        )
        return ScaleUpdateResult(
            "no_update", target, Path(state_path), local, None, 0, missing, False
        )

    remote = validator(remote_raw)
    dates = remote["date"].drop_duplicates()
    if len(dates) != 1:
        raise ValueError("Latest scale response must contain exactly one data date")
    remote_date = pd.Timestamp(dates.iloc[0])
    missing = _missing_names(remote)

    if not parquet_exists(target):
        save_parquet(remote, target)
        _record_state(
            state_path,
            source=source,
            operation="incremental",
            status="initialized",
            latest_data_date=remote_date.date().isoformat(),
            new_records=len(remote),
            missing_names=missing,
        )
        return ScaleUpdateResult(
            "initialized",
            target,
            Path(state_path),
            remote,
            remote_date,
            len(remote),
            missing,
            True,
        )

    local = validator(read_parquet(target))
    local_latest = pd.Timestamp(local["date"].max())
    if remote_date < local_latest:
        raise ValueError(
            f"Remote latest date {remote_date.date()} is earlier than local latest "
            f"date {local_latest.date()}"
        )
    if remote_date == local_latest:
        local_missing = _missing_names(local)
        _record_state(
            state_path,
            source=source,
            operation="incremental",
            status="no_update",
            latest_data_date=local_latest.date().isoformat(),
            new_records=0,
            missing_names=local_missing,
        )
        return ScaleUpdateResult(
            "no_update",
            target,
            Path(state_path),
            local,
            remote_date,
            0,
            local_missing,
            False,
        )

    combined = pd.concat([local, remote], ignore_index=True)
    combined = combined.drop_duplicates(["date", "fund_code"], keep="last")
    combined = validator(combined)
    save_parquet(combined, target)
    combined_missing = _missing_names(combined)
    _record_state(
        state_path,
        source=source,
        operation="incremental",
        status="updated",
        latest_data_date=remote_date.date().isoformat(),
        new_records=len(remote),
        missing_names=combined_missing,
    )
    return ScaleUpdateResult(
        "updated",
        target,
        Path(state_path),
        combined,
        remote_date,
        len(remote),
        combined_missing,
        True,
    )


def backfill_scale(
    start_date: str,
    end_date: str,
    *,
    source: str,
    path: str | Path,
    state_path: str | Path,
    fetcher: Callable[[str], pd.DataFrame],
    validator: Callable[[pd.DataFrame], pd.DataFrame],
    empty_columns: list[str],
    request_interval: float,
) -> ScaleBackfillResult:
    if request_interval < 0:
        raise ValueError("request_interval cannot be negative")
    target = Path(path)
    local = validator(read_parquet(target)) if parquet_exists(target) else pd.DataFrame(
        columns=empty_columns
    )
    known_dates = (
        set(pd.to_datetime(local["date"]).dt.date.astype(str)) if not local.empty else set()
    )
    requested: list[str] = []
    skipped: list[str] = []
    empty: list[str] = []
    added: list[str] = []
    mismatches: list[tuple[str, str]] = []
    additions: list[pd.DataFrame] = []

    for requested_date in generate_date_range(start_date, end_date):
        if requested_date in known_dates:
            skipped.append(requested_date)
            continue
        if requested:
            time.sleep(request_interval)
        requested.append(requested_date)
        response = fetcher(requested_date)
        if response.empty:
            empty.append(requested_date)
            continue
        checked = validator(response)
        actual_dates = checked["date"].drop_duplicates()
        if len(actual_dates) != 1:
            raise ValueError(
                f"Response for {requested_date} must contain exactly one data date"
            )
        actual_date = pd.Timestamp(actual_dates.iloc[0]).date().isoformat()
        if actual_date != requested_date:
            mismatches.append((requested_date, actual_date))
        if actual_date in known_dates:
            skipped.append(requested_date)
            continue
        additions.append(checked)
        known_dates.add(actual_date)
        added.append(actual_date)

    if not additions:
        missing = _missing_names(local)
        _record_state(
            state_path,
            source=source,
            operation="backfill",
            status="no_update",
            latest_data_date=_latest_date(local),
            new_records=0,
            missing_names=missing,
            requested_start=start_date,
            requested_end=end_date,
        )
        return ScaleBackfillResult(
            "no_update",
            target,
            Path(state_path),
            local,
            tuple(requested),
            tuple(skipped),
            tuple(empty),
            tuple(added),
            tuple(mismatches),
            missing,
            False,
        )

    combined = pd.concat(([local] if not local.empty else []) + additions, ignore_index=True)
    combined = combined.drop_duplicates(["date", "fund_code"], keep="last")
    combined = validator(combined)
    save_parquet(combined, target)
    missing = _missing_names(combined)
    new_records = sum(len(frame) for frame in additions)
    _record_state(
        state_path,
        source=source,
        operation="backfill",
        status="backfilled",
        latest_data_date=_latest_date(combined),
        new_records=new_records,
        missing_names=missing,
        requested_start=start_date,
        requested_end=end_date,
    )
    return ScaleBackfillResult(
        "backfilled",
        target,
        Path(state_path),
        combined,
        tuple(requested),
        tuple(skipped),
        tuple(empty),
        tuple(added),
        tuple(mismatches),
        missing,
        True,
    )
