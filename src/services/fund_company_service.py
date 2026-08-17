"""上交所基金管理公司维表的质量校验与当前快照更新。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

import pandas as pd

from src.config.paths import PROCESSED_DATA_DIR
from src.crawlers.fund_company import OUTPUT_COLUMNS, fetch_fund_companies
from src.storage.parquet_store import parquet_exists, read_parquet, save_parquet


DEFAULT_PARQUET_PATH = PROCESSED_DATA_DIR / "fund_companies.parquet"
COMPANY_COLUMNS = ["company_id", *OUTPUT_COLUMNS[:-1], "observed_at", "raw_record_json"]


@dataclass(frozen=True)
class FundCompanyUpdateResult:
    status: Literal["initialized", "updated", "no_update"]
    data: pd.DataFrame
    total: int
    invalid_code_count: int
    parquet_written: bool
    path: Path


def normalize_company_name(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()


def company_business_id(code: object, name: object) -> str:
    code_text = "" if code is None or pd.isna(code) else str(code).strip()
    if code_text and code_text != "-":
        return f"SSE:CODE:{code_text}"
    normalized_name = normalize_company_name(
        "" if name is None or pd.isna(name) else name
    )
    if not normalized_name:
        raise ValueError("company_name is required when company_code is invalid")
    return f"SSE:NAME:{normalized_name}"


def validate_fund_companies(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        raise ValueError("Fund company data is empty")
    missing = set(COMPANY_COLUMNS).difference(frame.columns)
    if missing:
        raise ValueError(f"Fund company data is missing fields: {sorted(missing)}")
    checked = frame[COMPANY_COLUMNS].copy()
    for column in set(COMPANY_COLUMNS) - {"observed_at"}:
        checked[column] = checked[column].astype("string").str.strip()
    checked["observed_at"] = pd.to_datetime(
        checked["observed_at"], errors="raise", utc=True
    )
    if checked["company_name"].isna().any() or (checked["company_name"] == "").any():
        raise ValueError("Fund company data contains an empty company_name")
    expected = [
        company_business_id(code, name)
        for code, name in zip(checked["company_code"], checked["company_name"])
    ]
    if checked["company_id"].tolist() != expected:
        raise ValueError("Fund company data contains an invalid company_id")
    if checked.duplicated("company_id").any():
        raise ValueError("Fund company data contains duplicate business keys")
    return checked.sort_values("company_id").reset_index(drop=True)


def _prepare_companies(raw: pd.DataFrame, observed_at: pd.Timestamp) -> pd.DataFrame:
    missing = set(OUTPUT_COLUMNS).difference(raw.columns)
    if missing:
        raise ValueError(f"Fund company crawler output is missing: {sorted(missing)}")
    frame = raw[OUTPUT_COLUMNS].copy()
    frame.insert(
        0,
        "company_id",
        [
            company_business_id(code, name)
            for code, name in zip(frame["company_code"], frame["company_name"])
        ],
    )
    frame.insert(len(frame.columns) - 1, "observed_at", observed_at)
    return validate_fund_companies(frame)


def update_fund_companies(
    path: str | Path = DEFAULT_PARQUET_PATH,
    *,
    fetcher: Callable[[], pd.DataFrame] = fetch_fund_companies,
    observed_at: datetime | pd.Timestamp | None = None,
) -> FundCompanyUpdateResult:
    checked_at = pd.Timestamp(observed_at or datetime.now(timezone.utc))
    checked_at = (
        checked_at.tz_localize("UTC")
        if checked_at.tzinfo is None
        else checked_at.tz_convert("UTC")
    )
    remote = _prepare_companies(fetcher(), checked_at)
    target = Path(path)
    local = validate_fund_companies(read_parquet(target)) if parquet_exists(target) else None
    compare_columns = [column for column in COMPANY_COLUMNS if column != "observed_at"]
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
    if written:
        save_parquet(data, target)
    invalid_codes = int(
        data["company_code"].isna().sum() + (data["company_code"] == "-").sum()
    )
    return FundCompanyUpdateResult(
        status, data, len(data), invalid_codes, written, target
    )
