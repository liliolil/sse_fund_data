"""上交所基金—做市商当前关系及日快照服务。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal
from zoneinfo import ZoneInfo

import pandas as pd

from src.config.paths import HISTORY_DATA_DIR, PROCESSED_DATA_DIR
from src.crawlers.fund_market_maker import RELATION_COLUMNS, fetch_fund_market_makers
from src.storage.parquet_store import parquet_exists, read_parquet, save_parquet


DEFAULT_PARQUET_PATH = PROCESSED_DATA_DIR / "fund_market_makers.parquet"
DEFAULT_SNAPSHOT_DIR = HISTORY_DATA_DIR / "fund_market_makers"
MARKET_MAKER_COLUMNS = [*RELATION_COLUMNS[:-1], "observed_at", "raw_record_json"]
KEY_COLUMNS = ["market", "fund_code", "firm_name", "service_type"]


@dataclass(frozen=True)
class FundMarketMakerUpdateResult:
    status: Literal["initialized", "updated", "no_update"]
    data: pd.DataFrame
    total: int
    new_count: int
    removed_count: int
    parquet_written: bool
    snapshot_written: bool
    path: Path
    snapshot_path: Path | None


def validate_fund_market_makers(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        raise ValueError("Fund market-maker relation data is empty")
    if "effective_date" in frame.columns:
        raise ValueError("observed_at must not be represented as effective_date")
    missing = set(MARKET_MAKER_COLUMNS).difference(frame.columns)
    if missing:
        raise ValueError(f"Fund market-maker data is missing fields: {sorted(missing)}")
    checked = frame[MARKET_MAKER_COLUMNS].copy()
    for column in set(MARKET_MAKER_COLUMNS) - {"observed_at"}:
        checked[column] = checked[column].astype("string").str.strip()
    checked["observed_at"] = pd.to_datetime(
        checked["observed_at"], errors="raise", utc=True
    )
    for column in ("market", "fund_code", "firm_name", "service_type", "source"):
        if checked[column].isna().any() or (checked[column] == "").any():
            raise ValueError(f"Fund market-maker data contains an empty {column}")
    if checked.duplicated(KEY_COLUMNS).any():
        raise ValueError("Fund market-maker data contains duplicate relation keys")
    return checked.sort_values(KEY_COLUMNS).reset_index(drop=True)


def _prepare_relations(raw: pd.DataFrame, observed_at: pd.Timestamp) -> pd.DataFrame:
    missing = set(RELATION_COLUMNS).difference(raw.columns)
    if missing:
        raise ValueError(f"Market-maker crawler output is missing: {sorted(missing)}")
    frame = raw[RELATION_COLUMNS].copy()
    frame.insert(len(frame.columns) - 1, "observed_at", observed_at)
    return validate_fund_market_makers(frame)


def _keys(frame: pd.DataFrame) -> set[tuple[str, str, str, str]]:
    return set(frame[KEY_COLUMNS].itertuples(index=False, name=None))


def update_fund_market_makers(
    path: str | Path = DEFAULT_PARQUET_PATH,
    *,
    snapshot_dir: str | Path = DEFAULT_SNAPSHOT_DIR,
    fetcher: Callable[[], pd.DataFrame] = fetch_fund_market_makers,
    observed_at: datetime | pd.Timestamp | None = None,
) -> FundMarketMakerUpdateResult:
    checked_at = pd.Timestamp(observed_at or datetime.now(timezone.utc))
    checked_at = (
        checked_at.tz_localize("UTC")
        if checked_at.tzinfo is None
        else checked_at.tz_convert("UTC")
    )
    remote = _prepare_relations(fetcher(), checked_at)
    target = Path(path)
    local = validate_fund_market_makers(read_parquet(target)) if parquet_exists(target) else None
    remote_keys = _keys(remote)
    local_keys = set() if local is None else _keys(local)
    new_count = len(remote_keys - local_keys)
    removed_count = len(local_keys - remote_keys)
    compare_columns = [column for column in MARKET_MAKER_COLUMNS if column != "observed_at"]
    if local is None:
        status: Literal["initialized", "updated", "no_update"] = "initialized"
        data = remote
        written = True
    elif local[compare_columns].equals(remote[compare_columns]):
        status = "no_update"
        data = local
        written = False
    else:
        status = "updated"
        data = remote
        written = True

    snapshot_path: Path | None = None
    snapshot_written = False
    if written:
        save_parquet(data, target)
        date_text = checked_at.tz_convert(ZoneInfo("Asia/Shanghai")).date().isoformat()
        snapshot_path = Path(snapshot_dir) / f"{date_text}.parquet"
        if not snapshot_path.is_file():
            save_parquet(data, snapshot_path)
            snapshot_written = True
        else:
            existing = validate_fund_market_makers(read_parquet(snapshot_path))
            if not existing[MARKET_MAKER_COLUMNS].equals(data[MARKET_MAKER_COLUMNS]):
                save_parquet(data, snapshot_path)
                snapshot_written = True
    return FundMarketMakerUpdateResult(
        status=status,
        data=data,
        total=len(data),
        new_count=new_count,
        removed_count=removed_count,
        parquet_written=written,
        snapshot_written=snapshot_written,
        path=target,
        snapshot_path=snapshot_path,
    )
