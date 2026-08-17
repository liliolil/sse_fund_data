"""上交所基金主数据的质量校验、详情补充、快照和增量更新。"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal
from zoneinfo import ZoneInfo

import pandas as pd

from src.config.paths import HISTORY_DATA_DIR, PROCESSED_DATA_DIR, RAW_DATA_DIR, STATE_DIR
from src.crawlers.fund_master import (
    fetch_fund_categories,
    fetch_fund_detail,
    fetch_fund_products,
    fetch_legacy_fund_supplement,
)
from src.storage.parquet_store import parquet_exists, read_parquet, save_parquet


DEFAULT_PARQUET_PATH = PROCESSED_DATA_DIR / "fund_master.parquet"
DEFAULT_SNAPSHOT_DIR = HISTORY_DATA_DIR / "fund_master_snapshots"
DEFAULT_DETAIL_CACHE_DIR = RAW_DATA_DIR / "fund_master" / "details"
DEFAULT_STATE_PATH = STATE_DIR / "fund_master_update_state.json"
MASTER_COLUMNS = [
    "fund_id",
    "market",
    "fund_code",
    "fund_name",
    "fund_expand_name",
    "fund_legal_name",
    "fund_type_code",
    "fund_type_name",
    "product_type",
    "list_date",
    "establish_date",
    "management_company_code",
    "management_company_name",
    "fund_manager_person",
    "underlying_index_code",
    "underlying_index_name",
    "custodian",
    "source",
    "observed_at",
    "raw_record_json",
]
DETAIL_COLUMNS = [
    "fund_legal_name",
    "establish_date",
    "custodian",
    "fund_manager_person",
]
COMPARE_COLUMNS = [
    column for column in MASTER_COLUMNS if column not in {"observed_at", "raw_record_json"}
]
KEY_COLUMNS = ["market", "fund_code"]


@dataclass(frozen=True)
class FundMasterUpdateResult:
    status: Literal["initialized", "updated", "no_update"]
    data: pd.DataFrame
    remote_total: int
    local_total: int
    new_count: int
    changed_count: int
    unchanged_count: int
    missing_count: int
    detail_requested: int
    detail_succeeded: int
    detail_pending: int
    parquet_written: bool
    snapshot_written: bool
    path: Path
    snapshot_path: Path | None
    state_path: Path


def stable_fund_id(market: object, fund_code: object) -> str:
    market_text = str(market).strip().upper()
    code_text = str(fund_code).strip()
    if not market_text or not code_text:
        raise ValueError("market and fund_code are required for fund_id")
    return f"{market_text}:{code_text}"


def build_category_mapping(
    categories: pd.DataFrame,
) -> dict[str, tuple[str, str]]:
    """返回 category_code -> (叶子名称, F000 下顶层产品类型)。"""
    required = {"category_code", "parent_code", "category_name"}
    missing = required.difference(categories.columns)
    if missing:
        raise ValueError(f"Fund categories are missing fields: {sorted(missing)}")
    rows = {
        str(row.category_code).strip(): (
            str(row.parent_code).strip(),
            str(row.category_name).strip(),
        )
        for row in categories.itertuples(index=False)
    }
    result: dict[str, tuple[str, str]] = {}
    for code, (_, leaf_name) in rows.items():
        current = code
        visited: set[str] = set()
        while True:
            if current in visited:
                raise ValueError(f"Fund category tree contains a cycle at {current}")
            visited.add(current)
            parent, name = rows[current]
            if parent == "F000":
                result[code] = (leaf_name, name)
                break
            if parent not in rows:
                raise ValueError(
                    f"Fund category {current} has unknown parent {parent}"
                )
            current = parent
    return result


def _optional_strings(series: pd.Series) -> pd.Series:
    return series.astype("string").str.strip().replace({"": pd.NA, "-": pd.NA})


def validate_fund_master(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        raise ValueError("Fund master data is empty")
    missing = set(MASTER_COLUMNS).difference(frame.columns)
    if missing:
        raise ValueError(f"Fund master data is missing fields: {sorted(missing)}")
    checked = frame[MASTER_COLUMNS].copy()
    required_strings = {
        "fund_id",
        "market",
        "fund_code",
        "fund_name",
        "fund_type_code",
        "fund_type_name",
        "product_type",
        "management_company_name",
        "source",
        "raw_record_json",
    }
    for column in set(MASTER_COLUMNS) - {"list_date", "establish_date", "observed_at"}:
        checked[column] = checked[column].astype("string").str.strip()
        if column not in required_strings:
            checked[column] = checked[column].replace({"": pd.NA, "-": pd.NA})
    checked["list_date"] = pd.to_datetime(checked["list_date"], errors="raise").dt.normalize()
    checked["establish_date"] = pd.to_datetime(
        checked["establish_date"], errors="raise"
    ).dt.normalize()
    checked["observed_at"] = pd.to_datetime(
        checked["observed_at"], errors="raise", utc=True
    )
    for column in required_strings:
        if checked[column].isna().any() or (checked[column] == "").any():
            raise ValueError(f"Fund master contains an empty {column}")
    expected_ids = [
        stable_fund_id(market, code)
        for market, code in zip(checked["market"], checked["fund_code"])
    ]
    if checked["fund_id"].tolist() != expected_ids:
        raise ValueError("Fund master contains an unstable fund_id")
    if checked.duplicated(KEY_COLUMNS).any():
        raise ValueError("Fund master contains duplicate market + fund_code keys")
    return checked.sort_values(KEY_COLUMNS).reset_index(drop=True)


def _write_json_atomic(path: str | Path, payload: dict[str, Any]) -> None:
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


def _detail_cache_path(cache_dir: str | Path, fund_code: str) -> Path:
    if not fund_code or any(char not in "0123456789" for char in fund_code):
        raise ValueError(f"Unsafe fund code for detail cache: {fund_code!r}")
    return Path(cache_dir) / f"{fund_code}.json"


def _load_cached_detail(cache_dir: str | Path, fund_code: str) -> dict[str, Any] | None:
    path = _detail_cache_path(cache_dir, fund_code)
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or str(payload.get("fund_code", "")) != fund_code:
        raise ValueError(f"Invalid cached fund detail: {path}")
    return payload


def _save_cached_detail(
    cache_dir: str | Path, fund_code: str, detail: dict[str, Any]
) -> None:
    _write_json_atomic(_detail_cache_path(cache_dir, fund_code), detail)


def _apply_detail(frame: pd.DataFrame, index: int, detail: dict[str, Any]) -> None:
    if str(detail.get("fund_code", "")).strip() != str(frame.at[index, "fund_code"]):
        raise ValueError("Fund detail code does not match target row")
    frame.at[index, "fund_legal_name"] = detail.get("fund_legal_name")
    establish = detail.get("establish_date")
    frame.at[index, "establish_date"] = (
        pd.to_datetime(establish, errors="raise").normalize() if establish else pd.NaT
    )
    frame.at[index, "custodian"] = detail.get("custodian") or frame.at[index, "custodian"]
    frame.at[index, "fund_manager_person"] = detail.get("fund_manager_person")


def _prepare_remote(
    products: pd.DataFrame,
    categories: pd.DataFrame,
    legacy: pd.DataFrame,
    observed_at: pd.Timestamp,
) -> pd.DataFrame:
    mapping = build_category_mapping(categories)
    remote = products.copy()
    unknown = sorted(set(remote["fund_type_code"].astype(str)).difference(mapping))
    if unknown:
        raise ValueError(f"Fund products contain unknown category codes: {unknown}")
    remote["fund_type_name"] = remote["fund_type_code"].map(
        lambda code: mapping[str(code)][0]
    )
    remote["product_type"] = remote["fund_type_code"].map(
        lambda code: mapping[str(code)][1]
    )
    if legacy.empty:
        remote["underlying_index_code"] = pd.NA
        remote["custodian"] = pd.NA
    else:
        supplement = legacy[["fund_code", "underlying_index_code", "custodian"]].copy()
        if supplement.duplicated("fund_code").any():
            raise ValueError("Legacy fund supplement contains duplicate fund_code values")
        remote = remote.merge(supplement, on="fund_code", how="left", validate="one_to_one")
    remote.insert(0, "market", "SSE")
    remote.insert(0, "fund_id", [f"SSE:{code}" for code in remote["fund_code"]])
    remote["fund_legal_name"] = pd.NA
    remote["establish_date"] = pd.NaT
    remote["fund_manager_person"] = pd.NA
    remote["observed_at"] = observed_at
    return remote.reindex(columns=MASTER_COLUMNS)


def _rows_equal(left: pd.Series, right: pd.Series) -> bool:
    for column in COMPARE_COLUMNS:
        a, b = left[column], right[column]
        if pd.isna(a) and pd.isna(b):
            continue
        if isinstance(a, pd.Timestamp) or isinstance(b, pd.Timestamp):
            if pd.Timestamp(a) != pd.Timestamp(b):
                return False
        elif str(a) != str(b):
            return False
    return True


def _save_snapshot(
    frame: pd.DataFrame, snapshot_dir: str | Path, snapshot_date: str
) -> tuple[Path, bool]:
    target = Path(snapshot_dir) / f"{snapshot_date}.parquet"
    if target.is_file():
        existing = validate_fund_master(read_parquet(target))
        if existing[MASTER_COLUMNS].equals(frame[MASTER_COLUMNS]):
            return target, False
    save_parquet(frame, target)
    return target, True


def update_fund_master(
    path: str | Path = DEFAULT_PARQUET_PATH,
    *,
    state_path: str | Path = DEFAULT_STATE_PATH,
    snapshot_dir: str | Path = DEFAULT_SNAPSHOT_DIR,
    detail_cache_dir: str | Path = DEFAULT_DETAIL_CACHE_DIR,
    product_fetcher: Callable[[], pd.DataFrame] = fetch_fund_products,
    category_fetcher: Callable[[], pd.DataFrame] = fetch_fund_categories,
    legacy_fetcher: Callable[[], pd.DataFrame] = fetch_legacy_fund_supplement,
    detail_fetcher: Callable[[str], dict[str, Any]] = fetch_fund_detail,
    detail_request_interval: float = 0.2,
    detail_batch_size: int | None = None,
    observed_at: datetime | pd.Timestamp | None = None,
) -> FundMasterUpdateResult:
    """更新当前主表；只为新增或关键详情缺失基金请求详情。"""
    if detail_request_interval < 0:
        raise ValueError("detail_request_interval cannot be negative")
    if detail_batch_size is not None and detail_batch_size <= 0:
        raise ValueError("detail_batch_size must be positive or None")
    checked_at = pd.Timestamp(observed_at or datetime.now(timezone.utc))
    if checked_at.tzinfo is None:
        checked_at = checked_at.tz_localize("UTC")
    else:
        checked_at = checked_at.tz_convert("UTC")
    snapshot_date = checked_at.tz_convert(ZoneInfo("Asia/Shanghai")).date().isoformat()

    products = product_fetcher()
    categories = category_fetcher()
    legacy = legacy_fetcher()
    remote_total = int(products.attrs.get("api_total", len(products)))
    if remote_total != len(products):
        raise ValueError("Unified fund list count does not match API total")
    remote = _prepare_remote(products, categories, legacy, checked_at)

    target = Path(path)
    local = validate_fund_master(read_parquet(target)) if parquet_exists(target) else None
    local_total = 0 if local is None else len(local)
    local_by_key = (
        {} if local is None else {
            (row.market, row.fund_code): row
            for row in local.itertuples(index=False)
        }
    )

    # 先沿用本地已补充详情；新版列表变化不应触发所有详情重查。
    for index, row in remote.iterrows():
        old = local_by_key.get((str(row["market"]), str(row["fund_code"])))
        if old is not None:
            for column in DETAIL_COLUMNS:
                remote.at[index, column] = getattr(old, column)

    detail_requested = 0
    detail_succeeded = 0
    detail_candidates: list[int] = []
    for index, row in remote.iterrows():
        code = str(row["fund_code"])
        cached = _load_cached_detail(detail_cache_dir, code)
        if cached is not None:
            _apply_detail(remote, index, cached)
            continue
        key = (str(row["market"]), code)
        is_new = key not in local_by_key
        has_missing_detail = any(pd.isna(remote.at[index, column]) for column in DETAIL_COLUMNS)
        if is_new or has_missing_detail:
            detail_candidates.append(index)

    selected = (
        detail_candidates
        if detail_batch_size is None
        else detail_candidates[:detail_batch_size]
    )
    for sequence, index in enumerate(selected):
        if sequence:
            time.sleep(detail_request_interval)
        code = str(remote.at[index, "fund_code"])
        detail_requested += 1
        detail = detail_fetcher(code)
        _save_cached_detail(detail_cache_dir, code, detail)
        _apply_detail(remote, index, detail)
        detail_succeeded += 1
    detail_pending = len(detail_candidates) - len(selected)

    remote = validate_fund_master(remote)
    remote_by_key = {
        (row.market, row.fund_code): row
        for row in remote.itertuples(index=False)
    }
    remote_keys = set(remote_by_key)
    local_keys = set(local_by_key)
    new_keys = remote_keys - local_keys
    missing_keys = local_keys - remote_keys
    changed_keys: set[tuple[str, str]] = set()
    unchanged_keys: set[tuple[str, str]] = set()
    if local is not None:
        local_index = local.set_index(KEY_COLUMNS, drop=False)
        remote_index = remote.set_index(KEY_COLUMNS, drop=False)
        for key in remote_keys & local_keys:
            if _rows_equal(remote_index.loc[key], local_index.loc[key]):
                unchanged_keys.add(key)
            else:
                changed_keys.add(key)

    parquet_written = local is None or bool(new_keys or changed_keys)
    snapshot_written = False
    snapshot_path: Path | None = None
    if local is None:
        data = remote
        status: Literal["initialized", "updated", "no_update"] = "initialized"
    elif parquet_written:
        retained_missing = local[
            local.apply(lambda row: (row["market"], row["fund_code"]) in missing_keys, axis=1)
        ]
        data = validate_fund_master(pd.concat([remote, retained_missing], ignore_index=True))
        status = "updated"
    else:
        data = local
        status = "no_update"

    if parquet_written:
        save_parquet(data, target)
        snapshot_path, snapshot_written = _save_snapshot(
            data, snapshot_dir, snapshot_date
        )

    state = {
        "last_check_time": checked_at.isoformat(),
        "remote_total": remote_total,
        "local_total": len(data),
        "previous_local_total": local_total,
        "new_count": len(new_keys),
        "changed_count": len(changed_keys),
        "unchanged_count": len(unchanged_keys),
        "missing_count": len(missing_keys),
        "detail_requested": detail_requested,
        "detail_succeeded": detail_succeeded,
        "detail_pending": detail_pending,
        "status": status,
    }
    _write_json_atomic(state_path, state)
    return FundMasterUpdateResult(
        status=status,
        data=data,
        remote_total=remote_total,
        local_total=len(data),
        new_count=len(new_keys),
        changed_count=len(changed_keys),
        unchanged_count=len(unchanged_keys),
        missing_count=len(missing_keys),
        detail_requested=detail_requested,
        detail_succeeded=detail_succeeded,
        detail_pending=detail_pending,
        parquet_written=parquet_written,
        snapshot_written=snapshot_written,
        path=target,
        snapshot_path=snapshot_path,
        state_path=Path(state_path),
    )
