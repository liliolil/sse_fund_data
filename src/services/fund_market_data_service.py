"""基金当前行情快照的质量检查、追加存储和状态管理。"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

import pandas as pd

from src.config.logging_config import get_logger
from src.config.paths import PROCESSED_DATA_DIR, STATE_DIR
from src.crawlers.fund_market_data import (
    NUMERIC_COLUMNS,
    OUTPUT_COLUMNS,
    fetch_etf_market_data,
    fetch_lof_market_data,
    fetch_reits_market_data,
)
from src.storage.parquet_store import parquet_exists, read_parquet, save_parquet


DEFAULT_PARQUET_PATH = PROCESSED_DATA_DIR / "fund_market_data.parquet"
DEFAULT_STATE_PATH = STATE_DIR / "fund_market_data_update_state.json"
PRIMARY_KEY = ["market", "fund_code", "snapshot_time"]
VALID_ROUTES = {"etf": "ETF", "lof": "LOF", "reits": "REIT"}
logger = get_logger("fund-market-data")


@dataclass(frozen=True)
class FundMarketDataUpdateResult:
    status: str
    path: Path
    state_path: Path
    data: pd.DataFrame
    source_statuses: Mapping[str, str]
    source_rows: Mapping[str, int]
    new_records: int
    parquet_written: bool
    errors: tuple[str, ...] = ()


def _empty_frame() -> pd.DataFrame:
    from src.crawlers.fund_market_data import _empty_frame as crawler_empty_frame

    return crawler_empty_frame()


def validate_fund_market_data(
    frame: pd.DataFrame, *, allow_empty: bool = False
) -> pd.DataFrame:
    if frame.empty:
        if allow_empty:
            return _empty_frame()
        raise ValueError("Fund market data is empty")
    missing = set(OUTPUT_COLUMNS).difference(frame.columns)
    if missing:
        raise ValueError(f"Fund market data is missing fields: {sorted(missing)}")
    checked = frame[OUTPUT_COLUMNS].copy()
    for column in (
        "market",
        "fund_type",
        "fund_code",
        "fund_name",
        "trade_phase",
        "source",
        "source_route",
        "raw_record_json",
    ):
        checked[column] = checked[column].astype("string")
    checked["fund_code"] = checked["fund_code"].str.strip()
    checked["fund_type"] = checked["fund_type"].str.strip()
    checked["source_route"] = checked["source_route"].str.strip()
    checked["snapshot_time"] = pd.to_datetime(
        checked["snapshot_time"], errors="raise", utc=True
    )
    checked["trade_date"] = pd.to_datetime(
        checked["trade_date"], errors="raise"
    ).dt.normalize()
    checked["observed_at"] = pd.to_datetime(
        checked["observed_at"], errors="raise", utc=True
    )
    for column in NUMERIC_COLUMNS:
        checked[column] = pd.to_numeric(checked[column], errors="coerce").astype("Float64")
    if checked["fund_code"].isna().any() or (checked["fund_code"] == "").any():
        raise ValueError("Fund market data contains an empty fund_code")
    if checked["snapshot_time"].isna().any():
        raise ValueError("Fund market data contains an empty snapshot_time")
    if not checked["source_route"].isin(VALID_ROUTES).all():
        raise ValueError("Fund market data contains an invalid source_route")
    expected_types = checked["source_route"].map(VALID_ROUTES)
    if not checked["fund_type"].eq(expected_types.astype("string")).all():
        raise ValueError("Fund market data fund_type does not match source_route")
    if checked.duplicated(PRIMARY_KEY).any():
        raise ValueError("Fund market data contains duplicate snapshot keys")
    return checked.sort_values(["snapshot_time", "source_route", "fund_code"]).reset_index(
        drop=True
    )


def _read_state(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Fund market data state must contain an object")
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


def _load_local(path: Path) -> pd.DataFrame:
    return validate_fund_market_data(read_parquet(path)) if parquet_exists(path) else _empty_frame()


def update_fund_market_data(
    path: str | Path = DEFAULT_PARQUET_PATH,
    *,
    state_path: str | Path = DEFAULT_STATE_PATH,
    fetchers: Mapping[str, Callable[[], pd.DataFrame]] | None = None,
) -> FundMarketDataUpdateResult:
    target = Path(path)
    target_state = Path(state_path)
    route_fetchers = {
        "etf": fetch_etf_market_data,
        "lof": fetch_lof_market_data,
        "reits": fetch_reits_market_data,
        **(fetchers or {}),
    }
    successful: list[pd.DataFrame] = []
    source_statuses: dict[str, str] = {}
    source_rows: dict[str, int] = {}
    errors: list[str] = []
    timestamp_sources: dict[str, str] = {}
    for route in VALID_ROUTES:
        try:
            raw = route_fetchers[route]()
            if raw.empty:
                raise ValueError("empty response")
            timestamp_sources[route] = str(
                raw.attrs.get("snapshot_time_source", "unverified")
            )
            checked = validate_fund_market_data(raw)
            if set(checked["source_route"]) != {route}:
                raise ValueError("fetcher returned another source route")
            successful.append(checked)
            source_statuses[route] = "recorded"
            source_rows[route] = len(checked)
            missing_numeric = int(checked[NUMERIC_COLUMNS].isna().sum().sum())
            if missing_numeric:
                logger.warning(
                    "source=%s numeric values converted to missing count=%d",
                    route,
                    missing_numeric,
                )
        except Exception as exc:
            source_statuses[route] = "failed"
            source_rows[route] = 0
            errors.append(f"{route}: {type(exc).__name__}: {exc}")
            logger.exception("source=%s snapshot failed", route)

    local = _load_local(target)
    state = _read_state(target_state)
    now = datetime.now(timezone.utc).isoformat()
    if successful:
        batch = pd.concat(successful, ignore_index=True)
        # 同一采集轮次使用统一快照时间；优先采用成功响应中的最新服务器时间。
        snapshot_time = pd.Timestamp(batch["snapshot_time"].max())
        existing_times = set(local["snapshot_time"]) if not local.empty else set()
        snapshot_time_source = (
            "exchange_server"
            if timestamp_sources
            and all(value == "exchange_server" for value in timestamp_sources.values())
            else "mixed_or_observed_at"
        )
        if snapshot_time in existing_times:
            snapshot_time = pd.Timestamp(datetime.now(timezone.utc))
            snapshot_time_source = "observed_at_collision_adjustment"
        batch["snapshot_time"] = snapshot_time
        batch = validate_fund_market_data(batch)
        combined = pd.concat(([local] if not local.empty else []) + [batch], ignore_index=True)
        combined = validate_fund_market_data(combined)
        save_parquet(combined, target)
        status = "partial_success" if errors else "recorded"
        written = True
        new_records = len(batch)
        last_success = now
        last_snapshot = snapshot_time.isoformat()
    else:
        combined = local
        status = "failed"
        written = False
        new_records = 0
        last_success = state.get("last_success_time")
        last_snapshot = state.get("last_snapshot_time")
        snapshot_time_source = str(state.get("snapshot_time_source") or "unavailable")

    source_state: dict[str, object] = {}
    for route in VALID_ROUTES:
        missing_count = 0
        for frame in successful:
            if set(frame["source_route"]) == {route}:
                missing_count = int(frame[NUMERIC_COLUMNS].isna().sum().sum())
                break
        source_state[route] = {
            "status": source_statuses[route],
            "rows": source_rows[route],
            "missing_numeric_values": missing_count,
            "snapshot_time_source": timestamp_sources.get(route, "unavailable"),
        }
    state.update(
        {
            "last_check_time": now,
            "last_success_time": last_success,
            "last_snapshot_time": last_snapshot,
            "overall_status": status,
            "snapshot_time_source": snapshot_time_source,
            "sources": source_state,
            "new_records": new_records,
            "errors": errors,
            "history_capability": "snapshot_from_now",
        }
    )
    _write_state(target_state, state)
    return FundMarketDataUpdateResult(
        status,
        target,
        target_state,
        combined,
        source_statuses,
        source_rows,
        new_records,
        written,
        tuple(errors),
    )
