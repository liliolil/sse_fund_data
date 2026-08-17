"""货币基金每日申购/赎回限额的校验、修订检测和存储。"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pandas as pd

from src.config.logging_config import get_logger
from src.config.paths import PROCESSED_DATA_DIR, STATE_DIR
from src.crawlers.money_fund_redemption_params import (
    NUMERIC_COLUMNS,
    OUTPUT_COLUMNS,
    fetch_money_fund_redemption_params,
)
from src.storage.parquet_store import parquet_exists, read_parquet, save_parquet


DEFAULT_PARQUET_PATH = PROCESSED_DATA_DIR / "money_fund_redemption_params.parquet"
DEFAULT_STATE_PATH = STATE_DIR / "money_fund_redemption_params_update_state.json"
PRIMARY_KEY = ["market", "fund_code", "trade_date"]
CONTENT_COLUMNS = [column for column in OUTPUT_COLUMNS if column != "observed_at"]
logger = get_logger("money-fund-redemption-params")


@dataclass(frozen=True)
class MoneyFundRedemptionUpdateResult:
    status: str
    path: Path
    state_path: Path
    data: pd.DataFrame
    remote_data: pd.DataFrame
    new_records: int
    revision_detected: bool
    revision_count: int
    parquet_written: bool


def _empty_frame() -> pd.DataFrame:
    from src.crawlers.money_fund_redemption_params import _empty_frame as crawler_empty

    return crawler_empty()


def validate_money_fund_redemption_params(
    frame: pd.DataFrame, *, allow_empty: bool = False
) -> pd.DataFrame:
    if frame.empty:
        if allow_empty:
            return _empty_frame()
        raise ValueError("Money fund redemption parameter data is empty")
    missing = set(OUTPUT_COLUMNS).difference(frame.columns)
    if missing:
        raise ValueError(
            f"Money fund redemption parameter data is missing fields: {sorted(missing)}"
        )
    checked = frame[OUTPUT_COLUMNS].copy()
    for column in (
        "market",
        "fund_code",
        "fund_name",
        "company_name",
        "others",
        "source_num",
        "source",
        "source_route",
        "raw_record_json",
    ):
        checked[column] = checked[column].astype("string")
    checked["fund_code"] = checked["fund_code"].str.strip()
    checked["file_date"] = pd.to_datetime(
        checked["file_date"], errors="raise"
    ).dt.normalize()
    checked["trade_date"] = pd.to_datetime(
        checked["trade_date"], errors="raise"
    ).dt.normalize()
    checked["observed_at"] = pd.to_datetime(
        checked["observed_at"], errors="raise", utc=True
    )
    for column in NUMERIC_COLUMNS:
        checked[column] = pd.to_numeric(checked[column], errors="coerce").astype("Float64")
    if checked["fund_code"].isna().any() or (checked["fund_code"] == "").any():
        raise ValueError("Money fund redemption data contains an empty fund_code")
    if checked["trade_date"].isna().any():
        raise ValueError("Money fund redemption data contains an empty trade_date")
    if checked["source_route"].ne("money_fund_redemption_params").any():
        raise ValueError("Money fund redemption data contains an invalid source_route")
    if checked.duplicated(PRIMARY_KEY).any():
        raise ValueError("Money fund redemption data contains duplicate business keys")
    return checked.sort_values(["trade_date", "fund_code"]).reset_index(drop=True)


def _read_state(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Money fund redemption state must contain an object")
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


def _latest_date(frame: pd.DataFrame) -> str | None:
    if frame.empty:
        return None
    return pd.Timestamp(frame["trade_date"].max()).date().isoformat()


def _content_map(frame: pd.DataFrame) -> dict[tuple[object, ...], tuple[object, ...]]:
    canonical = frame[PRIMARY_KEY + [c for c in CONTENT_COLUMNS if c not in PRIMARY_KEY]].copy()
    canonical = canonical.astype("object").where(pd.notna(canonical), None)
    result: dict[tuple[object, ...], tuple[object, ...]] = {}
    value_columns = [column for column in canonical.columns if column not in PRIMARY_KEY]
    for _, row in canonical.iterrows():
        key = tuple(row[column] for column in PRIMARY_KEY)
        result[key] = tuple(row[column] for column in value_columns)
    return result


def update_money_fund_redemption_params(
    path: str | Path = DEFAULT_PARQUET_PATH,
    *,
    state_path: str | Path = DEFAULT_STATE_PATH,
    fetcher: Callable[[], pd.DataFrame] = fetch_money_fund_redemption_params,
) -> MoneyFundRedemptionUpdateResult:
    target = Path(path)
    target_state = Path(state_path)
    exists = parquet_exists(target)
    local = (
        validate_money_fund_redemption_params(read_parquet(target))
        if exists
        else _empty_frame()
    )
    remote_raw = fetcher()
    state = _read_state(target_state)
    now = datetime.now(timezone.utc).isoformat()
    if remote_raw.empty:
        status = "no_update"
        remote = _empty_frame()
        new_records = 0
        revision_count = 0
        written = False
        last_success = state.get("last_success_time")
    else:
        remote = validate_money_fund_redemption_params(remote_raw)
        remote_dates = set(remote["trade_date"])
        local_map = _content_map(local)
        remote_map = _content_map(remote)
        new_records = sum(key not in local_map for key in remote_map)
        revision_count = 0
        for trade_date in remote_dates:
            local_date_map = {
                key: value for key, value in local_map.items() if key[2] == trade_date
            }
            if not local_date_map:
                continue
            remote_date_map = {
                key: value for key, value in remote_map.items() if key[2] == trade_date
            }
            revision_count += sum(
                local_date_map.get(key) != remote_date_map.get(key)
                for key in set(local_date_map) | set(remote_date_map)
            )

        if new_records == 0 and revision_count == 0:
            combined = local
            status = "no_update"
            written = False
        else:
            keep = ~local["trade_date"].isin(remote_dates) if not local.empty else []
            retained = local.loc[keep] if not local.empty else local
            combined = pd.concat(
                ([retained] if not retained.empty else []) + [remote], ignore_index=True
            )
            combined = validate_money_fund_redemption_params(combined)
            save_parquet(combined, target)
            written = True
            if not exists:
                status = "initialized"
            elif revision_count and new_records:
                status = "updated_with_revision"
            elif revision_count:
                status = "revised"
            else:
                status = "updated"
        last_success = now
    if remote_raw.empty:
        combined = local

    mismatch_count = (
        int((remote["file_date"] != remote["trade_date"]).sum())
        if not remote.empty
        else 0
    )
    missing_numeric = (
        int(remote[NUMERIC_COLUMNS].isna().sum().sum()) if not remote.empty else 0
    )
    if missing_numeric:
        logger.warning("numeric limit values converted to missing count=%d", missing_numeric)
    state.update(
        {
            "last_check_time": now,
            "last_success_time": last_success,
            "latest_remote_trade_date": _latest_date(remote),
            "latest_local_trade_date": _latest_date(combined),
            "status": status,
            "rows_remote": len(remote),
            "rows_local": len(combined),
            "history_capability": "snapshot_from_now",
            "revision_detected": revision_count > 0,
            "revision_count": revision_count,
            "revision_count_total": int(state.get("revision_count_total") or 0)
            + revision_count,
            "file_trade_date_mismatch_count": mismatch_count,
            "missing_numeric_values": missing_numeric,
        }
    )
    _write_state(target_state, state)
    return MoneyFundRedemptionUpdateResult(
        status,
        target,
        target_state,
        combined,
        remote,
        new_records,
        revision_count > 0,
        revision_count,
        written,
    )
