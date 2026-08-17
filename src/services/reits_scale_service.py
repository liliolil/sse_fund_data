"""公募 REITs 规模的数据质量、历史回填、增量和存储服务。"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import pandas as pd

from src.config.paths import PROCESSED_DATA_DIR, STATE_DIR
from src.crawlers.reits_scale import (
    OUTPUT_COLUMNS,
    fetch_latest_reits_scale,
    fetch_reits_scale,
)
from src.services.scale_service_common import (
    ScaleBackfillResult,
    ScaleUpdateResult,
    backfill_scale,
    update_scale,
)


DEFAULT_PARQUET_PATH = PROCESSED_DATA_DIR / "reits_scale.parquet"
DEFAULT_STATE_PATH = STATE_DIR / "reits_scale_update_state.json"


def validate_reits_scale(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        raise ValueError("REITs scale data is empty")
    missing = set(OUTPUT_COLUMNS).difference(frame.columns)
    if missing:
        raise ValueError(f"REITs scale data is missing fields: {sorted(missing)}")

    checked = frame[OUTPUT_COLUMNS].copy()
    checked["date"] = pd.to_datetime(checked["date"], errors="raise").dt.normalize()
    checked["fund_code"] = checked["fund_code"].astype("string").str.strip()
    checked["fund_name"] = checked["fund_name"].astype("string").str.strip()
    checked["shares_10k"] = pd.to_numeric(
        checked["shares_10k"], errors="raise"
    ).astype("Float64")
    checked["raw_record_json"] = checked["raw_record_json"].astype("string")

    if checked["date"].isna().any():
        raise ValueError("REITs scale data contains a missing date")
    if not checked["fund_code"].str.fullmatch(r"\d{6}", na=False).all():
        raise ValueError("REITs scale data contains an invalid fund code")
    if checked["shares_10k"].isna().any():
        raise ValueError("REITs scale data contains a missing shares_10k value")
    if checked["raw_record_json"].isna().any() or (
        checked["raw_record_json"].str.strip() == ""
    ).any():
        raise ValueError("REITs scale data contains an empty raw_record_json")
    if checked.duplicated(["date", "fund_code"]).any():
        raise ValueError("REITs scale data contains duplicate date + fund_code keys")
    return checked.sort_values(["date", "fund_code"]).reset_index(drop=True)


def update_reits_scale(
    path: str | Path = DEFAULT_PARQUET_PATH,
    *,
    state_path: str | Path = DEFAULT_STATE_PATH,
    fetcher: Callable[[], pd.DataFrame] = fetch_latest_reits_scale,
) -> ScaleUpdateResult:
    return update_scale(
        source="reits_scale",
        path=path,
        state_path=state_path,
        fetcher=fetcher,
        validator=validate_reits_scale,
        empty_columns=OUTPUT_COLUMNS,
    )


def backfill_reits_scale(
    start_date: str,
    end_date: str,
    path: str | Path = DEFAULT_PARQUET_PATH,
    *,
    state_path: str | Path = DEFAULT_STATE_PATH,
    fetcher: Callable[[str], pd.DataFrame] = fetch_reits_scale,
    request_interval: float = 0.2,
) -> ScaleBackfillResult:
    return backfill_scale(
        start_date,
        end_date,
        source="reits_scale",
        path=path,
        state_path=state_path,
        fetcher=fetcher,
        validator=validate_reits_scale,
        empty_columns=OUTPUT_COLUMNS,
        request_interval=request_interval,
    )
