"""LOF 日净值与 REITs 评估净值的统一存储、回填和增量服务。"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal, Mapping, Sequence

import pandas as pd

from src.config.paths import PROCESSED_DATA_DIR, STATE_DIR
from src.crawlers.fund_nav import (
    OUTPUT_COLUMNS,
    fetch_latest_lof_nav,
    fetch_latest_reits_nav,
    fetch_lof_nav,
    fetch_reits_nav,
)
from src.storage.parquet_store import parquet_exists, read_parquet, save_parquet


DEFAULT_PARQUET_PATH = PROCESSED_DATA_DIR / "fund_nav.parquet"
DEFAULT_STATE_PATH = STATE_DIR / "fund_nav_update_state.json"
PRIMARY_KEY = ["market", "fund_code", "nav_date", "nav_type"]
SOURCE_SEMANTICS = {"lof": "daily_nav", "reits": "appraisal_nav"}


@dataclass(frozen=True)
class FundNavUpdateResult:
    status: Literal["initialized", "updated", "no_update"]
    path: Path
    state_path: Path
    data: pd.DataFrame
    source_statuses: Mapping[str, str]
    new_records: int
    parquet_written: bool


@dataclass(frozen=True)
class FundNavBackfillResult:
    status: Literal["backfilled", "no_update"]
    path: Path
    state_path: Path
    data: pd.DataFrame
    source_route: str
    requested_dates: tuple[str, ...]
    skipped_dates: tuple[str, ...]
    empty_dates: tuple[str, ...]
    added_dates: tuple[str, ...]
    new_records: int
    parquet_written: bool


def _empty_frame() -> pd.DataFrame:
    from src.crawlers.fund_nav import _empty_frame as crawler_empty_frame

    return crawler_empty_frame()


def validate_fund_nav(frame: pd.DataFrame, *, allow_empty: bool = False) -> pd.DataFrame:
    if frame.empty:
        if allow_empty:
            return _empty_frame()
        raise ValueError("Fund NAV data is empty")
    missing = set(OUTPUT_COLUMNS).difference(frame.columns)
    if missing:
        raise ValueError(f"Fund NAV data is missing fields: {sorted(missing)}")
    checked = frame[OUTPUT_COLUMNS].copy()
    for column in (
        "market",
        "fund_code",
        "fund_name",
        "fund_full_name",
        "nav_type",
        "product_type",
        "source",
        "source_route",
        "raw_record_json",
    ):
        checked[column] = checked[column].astype("string")
    checked["market"] = checked["market"].str.strip()
    checked["fund_code"] = checked["fund_code"].str.strip()
    checked["nav_type"] = checked["nav_type"].str.strip()
    checked["source_route"] = checked["source_route"].str.strip()
    checked["nav_date"] = pd.to_datetime(checked["nav_date"], errors="raise").dt.normalize()
    checked["nav"] = pd.to_numeric(checked["nav"], errors="raise").astype("Float64")
    checked["observed_at"] = pd.to_datetime(
        checked["observed_at"], errors="raise", utc=True
    )

    if checked["fund_code"].isna().any() or (checked["fund_code"] == "").any():
        raise ValueError("Fund NAV data contains an empty fund_code")
    if checked["nav_date"].isna().any():
        raise ValueError("Fund NAV data contains an empty nav_date")
    if checked["nav"].isna().any():
        raise ValueError("Fund NAV data contains an empty nav")
    if checked["nav_type"].isna().any() or (checked["nav_type"] == "").any():
        raise ValueError("Fund NAV data contains an empty nav_type")
    if checked["source_route"].isna().any() or (checked["source_route"] == "").any():
        raise ValueError("Fund NAV data contains an empty source_route")
    for route, expected_type in SOURCE_SEMANTICS.items():
        wrong = (checked["source_route"] == route) & (checked["nav_type"] != expected_type)
        if wrong.any():
            raise ValueError(f"{route} NAV rows must use nav_type={expected_type}")
    if checked.duplicated(PRIMARY_KEY).any():
        raise ValueError("Fund NAV data contains duplicate business keys")
    return checked.sort_values(PRIMARY_KEY).reset_index(drop=True)


def _read_state(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Fund NAV state must contain an object")
    return payload


def _write_state(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=f".{path.stem}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as temporary:
            json.dump(payload, temporary, ensure_ascii=False, indent=2)
            temporary.write("\n")
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _route_latest(frame: pd.DataFrame, route: str) -> str | None:
    rows = frame.loc[frame["source_route"] == route] if not frame.empty else frame
    if rows.empty:
        return None
    return pd.Timestamp(rows["nav_date"].max()).date().isoformat()


def _record_state(
    state_path: Path,
    data: pd.DataFrame,
    route_statuses: Mapping[str, str],
    remote_dates: Mapping[str, str | None],
    *,
    overall_status: str,
    operation: str,
    new_records: int,
) -> None:
    state = _read_state(state_path)
    for route in SOURCE_SEMANTICS:
        previous = state.get(route)
        section = dict(previous) if isinstance(previous, dict) else {}
        if route in remote_dates:
            section["latest_remote_date"] = remote_dates[route]
        section.update(
            {
                "latest_local_date": _route_latest(data, route),
                "status": route_statuses.get(route, section.get("status", "not_checked")),
                "history_boundary": "partially_verified",
            }
        )
        state[route] = section
    state.update(
        {
            "last_check_time": datetime.now(timezone.utc).isoformat(),
            "operation": operation,
            "status": overall_status,
            "new_records": new_records,
        }
    )
    _write_state(state_path, state)


def _load_local(path: Path) -> pd.DataFrame:
    if not parquet_exists(path):
        return _empty_frame()
    return validate_fund_nav(read_parquet(path))


def update_fund_nav(
    path: str | Path = DEFAULT_PARQUET_PATH,
    *,
    state_path: str | Path = DEFAULT_STATE_PATH,
    sources: Sequence[str] = ("lof", "reits"),
    fetchers: Mapping[str, Callable[[], pd.DataFrame]] | None = None,
) -> FundNavUpdateResult:
    selected = tuple(dict.fromkeys(str(source).strip().lower() for source in sources))
    if not selected or any(source not in SOURCE_SEMANTICS for source in selected):
        raise ValueError("sources must contain lof and/or reits")
    target = Path(path)
    target_state = Path(state_path)
    local = _load_local(target)
    was_initialized = parquet_exists(target)
    route_fetchers = {
        "lof": fetch_latest_lof_nav,
        "reits": fetch_latest_reits_nav,
        **(fetchers or {}),
    }
    additions: list[pd.DataFrame] = []
    statuses: dict[str, str] = {}
    remote_dates: dict[str, str | None] = {}

    for route in selected:
        remote_raw = route_fetchers[route]()
        if remote_raw.empty:
            statuses[route] = "no_update"
            remote_dates[route] = None
            continue
        remote = validate_fund_nav(remote_raw)
        if set(remote["source_route"]) != {route}:
            raise ValueError(f"{route} fetcher returned rows from another source route")
        dates = remote["nav_date"].drop_duplicates()
        if len(dates) != 1:
            raise ValueError(f"Latest {route} NAV response must contain one nav_date")
        remote_date = pd.Timestamp(dates.iloc[0]).date().isoformat()
        remote_dates[route] = remote_date
        local_date = _route_latest(local, route)
        if local_date is not None and remote_date < local_date:
            raise ValueError(
                f"Remote {route} NAV date {remote_date} is earlier than local {local_date}"
            )
        if local_date == remote_date:
            statuses[route] = "no_update"
            continue
        additions.append(remote)
        statuses[route] = "updated" if was_initialized else "initialized"

    new_records = sum(len(frame) for frame in additions)
    if additions:
        combined = pd.concat(([local] if not local.empty else []) + additions, ignore_index=True)
        combined = combined.drop_duplicates(PRIMARY_KEY, keep="last")
        combined = validate_fund_nav(combined)
        save_parquet(combined, target)
        status: Literal["initialized", "updated", "no_update"] = (
            "updated" if was_initialized else "initialized"
        )
        written = True
    else:
        combined = local
        status = "no_update"
        written = False
    _record_state(
        target_state,
        combined,
        statuses,
        remote_dates,
        overall_status=status,
        operation="incremental",
        new_records=new_records,
    )
    return FundNavUpdateResult(
        status, target, target_state, combined, statuses, new_records, written
    )


def _backfill_dates(
    route: str,
    requested_dates: Sequence[str],
    *,
    path: str | Path,
    state_path: str | Path,
    fetcher: Callable[[str], pd.DataFrame],
    request_interval: float,
) -> FundNavBackfillResult:
    if route not in SOURCE_SEMANTICS:
        raise ValueError("source_route must be lof or reits")
    if request_interval < 0:
        raise ValueError("request_interval cannot be negative")
    dates = tuple(dict.fromkeys(pd.Timestamp(value).date().isoformat() for value in requested_dates))
    if not dates:
        raise ValueError("at least one date is required")
    target = Path(path)
    target_state = Path(state_path)
    local = _load_local(target)
    known_dates = set(
        local.loc[local["source_route"] == route, "nav_date"].dt.date.astype(str)
    )
    requested: list[str] = []
    skipped: list[str] = []
    empty: list[str] = []
    added: list[str] = []
    additions: list[pd.DataFrame] = []
    remote_dates: dict[str, str | None] = {route: None}

    for value in dates:
        if value in known_dates:
            skipped.append(value)
            continue
        if requested:
            time.sleep(request_interval)
        requested.append(value)
        response = fetcher(value)
        if response.empty:
            empty.append(value)
            continue
        checked = validate_fund_nav(response)
        if set(checked["source_route"]) != {route}:
            raise ValueError(f"{route} backfill returned another source route")
        actual_dates = checked["nav_date"].drop_duplicates()
        if len(actual_dates) != 1:
            raise ValueError(f"{route} response for {value} has multiple nav dates")
        actual = pd.Timestamp(actual_dates.iloc[0]).date().isoformat()
        if actual != value:
            raise ValueError(f"{route} response date {actual} does not match request {value}")
        if actual in known_dates:
            skipped.append(value)
            continue
        additions.append(checked)
        known_dates.add(actual)
        added.append(actual)
        remote_dates[route] = actual

    if additions:
        combined = pd.concat(([local] if not local.empty else []) + additions, ignore_index=True)
        combined = combined.drop_duplicates(PRIMARY_KEY, keep="last")
        combined = validate_fund_nav(combined)
        save_parquet(combined, target)
        status: Literal["backfilled", "no_update"] = "backfilled"
        written = True
    else:
        combined = local
        status = "no_update"
        written = False
    new_records = sum(len(frame) for frame in additions)
    _record_state(
        target_state,
        combined,
        {route: status},
        remote_dates,
        overall_status=status,
        operation="backfill",
        new_records=new_records,
    )
    return FundNavBackfillResult(
        status,
        target,
        target_state,
        combined,
        route,
        tuple(requested),
        tuple(skipped),
        tuple(empty),
        tuple(added),
        new_records,
        written,
    )


def backfill_lof_nav(
    start_date: str,
    end_date: str,
    path: str | Path = DEFAULT_PARQUET_PATH,
    *,
    state_path: str | Path = DEFAULT_STATE_PATH,
    fetcher: Callable[[str], pd.DataFrame] = fetch_lof_nav,
    request_interval: float = 0.2,
) -> FundNavBackfillResult:
    start = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_date).normalize()
    if start > end:
        raise ValueError("start_date cannot be later than end_date")
    dates = [day.date().isoformat() for day in pd.date_range(start, end, freq="D")]
    return _backfill_dates(
        "lof",
        dates,
        path=path,
        state_path=state_path,
        fetcher=fetcher,
        request_interval=request_interval,
    )


def backfill_reits_nav(
    appraise_dates: Sequence[str],
    path: str | Path = DEFAULT_PARQUET_PATH,
    *,
    state_path: str | Path = DEFAULT_STATE_PATH,
    fetcher: Callable[[str], pd.DataFrame] = fetch_reits_nav,
    request_interval: float = 0.2,
) -> FundNavBackfillResult:
    """只查询调用方明确给出的评估日，禁止隐式逐日扩展。"""
    return _backfill_dates(
        "reits",
        appraise_dates,
        path=path,
        state_path=state_path,
        fetcher=fetcher,
        request_interval=request_interval,
    )


def backfill_fund_nav_cli(source: str, start_date: str, end_date: str) -> FundNavBackfillResult:
    route = source.strip().lower()
    if route == "lof":
        return backfill_lof_nav(start_date, end_date)
    if route == "reits":
        if start_date != end_date:
            raise ValueError(
                "REITs CLI backfill requires one explicit appraisal date; "
                "use the service date-list API for multiple known dates"
            )
        return backfill_reits_nav([start_date])
    raise ValueError("source must be lof or reits")
