"""ETF PCF 最新文件的增量保存、质量校验和 checkpoint 服务。"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Literal, Mapping

import pandas as pd

from src.config.paths import PROCESSED_DATA_DIR, RAW_DATA_DIR, STATE_DIR
from src.crawlers.etf_pcf import (
    COMPONENT_COLUMNS,
    HEADER_COLUMNS,
    PcfXmlDownload,
    download_latest_pcf_xml,
    parse_pcf_xml,
)
from src.storage.parquet_store import parquet_exists, read_parquet, save_parquet


DEFAULT_HEADER_PATH = PROCESSED_DATA_DIR / "etf_pcf_headers.parquet"
DEFAULT_COMPONENT_PATH = PROCESSED_DATA_DIR / "etf_pcf_components.parquet"
DEFAULT_XML_DIR = RAW_DATA_DIR / "etf_pcf" / "xml"
DEFAULT_STATE_PATH = STATE_DIR / "etf_pcf_update_state.json"


@dataclass(frozen=True)
class PcfFundUpdateResult:
    fund_code: str
    trading_day: pd.Timestamp
    record_number: int
    component_count: int
    status: Literal["updated", "revised", "no_update"]
    etf_class: str | None
    pcf_class: str | None
    xml_path: Path
    xml_saved: bool
    missing_header_fields: tuple[str, ...]
    missing_component_fields: tuple[str, ...]
    non_six_digit_component_codes: int


@dataclass(frozen=True)
class PcfUpdateResult:
    status: Literal["updated", "revised", "no_update"]
    funds: tuple[PcfFundUpdateResult, ...]
    headers: pd.DataFrame
    components: pd.DataFrame
    header_path: Path
    component_path: Path
    state_path: Path
    parquet_written: bool


def _empty_headers() -> pd.DataFrame:
    return pd.DataFrame(columns=HEADER_COLUMNS)


def _empty_components() -> pd.DataFrame:
    return pd.DataFrame(columns=COMPONENT_COLUMNS)


def validate_pcf_headers(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return _empty_headers()
    # 兼容旧 Parquet：新增的分类和 XML 可选节点以 null 补齐。
    for column in set(HEADER_COLUMNS).difference(frame.columns):
        frame = frame.assign(**{column: pd.NA})
    checked = frame[HEADER_COLUMNS].copy()
    checked["fund_code"] = checked["fund_code"].astype("string").str.strip()
    for column in (
        "etf_class",
        "pcf_class",
        "publish_iopv_flag",
        "creation_redemption_switch",
        "creation_redemption_mechanism",
    ):
        checked[column] = checked[column].astype("string")
    checked["trading_day"] = pd.to_datetime(
        checked["trading_day"], errors="raise"
    ).dt.normalize()
    checked["pre_trading_day"] = pd.to_datetime(
        checked["pre_trading_day"], errors="raise"
    ).dt.normalize()
    checked["creation_redemption_unit"] = pd.to_numeric(
        checked["creation_redemption_unit"], errors="raise"
    ).astype("Int64")
    for column in (
        "nav_per_cu",
        "nav",
        "pre_cash_component",
        "estimated_cash_component",
        "max_cash_ratio",
        "redemption_limit",
    ):
        checked[column] = pd.to_numeric(checked[column], errors="raise").astype("Float64")
    checked["record_number"] = pd.to_numeric(
        checked["record_number"], errors="raise"
    ).astype("Int64")
    checked["raw_xml_path"] = checked["raw_xml_path"].astype("string")
    if not checked["fund_code"].str.fullmatch(r"\d{6}", na=False).all():
        raise ValueError("PCF headers contain an invalid fund_code")
    if checked["trading_day"].isna().any():
        raise ValueError("PCF headers contain a missing trading_day")
    if checked["record_number"].isna().any() or (checked["record_number"] < 0).any():
        raise ValueError("PCF headers contain an invalid record_number")
    if checked["raw_xml_path"].isna().any() or (
        checked["raw_xml_path"].str.strip() == ""
    ).any():
        raise ValueError("PCF headers contain an empty raw_xml_path")
    if checked.duplicated(["fund_code", "trading_day"]).any():
        raise ValueError("PCF headers contain duplicate fund_code + trading_day keys")
    return checked.sort_values(["trading_day", "fund_code"]).reset_index(drop=True)


def validate_pcf_components(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return _empty_components()
    missing = set(COMPONENT_COLUMNS).difference(frame.columns)
    if missing:
        raise ValueError(f"PCF components are missing fields: {sorted(missing)}")
    checked = frame[COMPONENT_COLUMNS].copy()
    checked["fund_code"] = checked["fund_code"].astype("string").str.strip()
    checked["trading_day"] = pd.to_datetime(
        checked["trading_day"], errors="raise"
    ).dt.normalize()
    for column in (
        "component_code",
        "component_name",
        "substitution_flag",
        "underlying_security_id",
    ):
        checked[column] = checked[column].astype("string")
    for column in (
        "quantity",
        "creation_premium_rate",
        "redemption_discount_rate",
        "substitution_cash_amount",
    ):
        checked[column] = pd.to_numeric(checked[column], errors="raise").astype("Float64")
    if not checked["fund_code"].str.fullmatch(r"\d{6}", na=False).all():
        raise ValueError("PCF components contain an invalid fund_code")
    if checked["trading_day"].isna().any():
        raise ValueError("PCF components contain a missing trading_day")
    if checked["component_code"].isna().any() or (
        checked["component_code"].str.strip() == ""
    ).any():
        raise ValueError("PCF components contain an empty component_code")
    primary_key = ["fund_code", "trading_day", "component_code"]
    if checked.duplicated(primary_key).any():
        raise ValueError("PCF components contain duplicate source keys")
    return checked.sort_values(primary_key).reset_index(drop=True)


def _validate_record_counts(headers: pd.DataFrame, components: pd.DataFrame) -> None:
    counts = (
        components.groupby(["fund_code", "trading_day"], dropna=False)
        .size()
        .to_dict()
        if not components.empty
        else {}
    )
    for row in headers.itertuples(index=False):
        key = (row.fund_code, row.trading_day)
        actual = int(counts.get(key, 0))
        expected = int(row.record_number)
        if actual != expected:
            raise ValueError(
                f"PCF {row.fund_code} {row.trading_day.date()} has "
                f"RecordNumber={expected}, components={actual}"
            )


def _write_json_state(path: str | Path, payload: dict[str, object]) -> None:
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


def _save_raw_xml(
    download: PcfXmlDownload,
    trading_day: pd.Timestamp,
    xml_dir: str | Path,
) -> tuple[Path, bool]:
    target = Path(xml_dir) / (
        f"{download.fund_code}_{trading_day.strftime('%Y%m%d')}.xml"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        try:
            existing_content = target.read_bytes()
            existing = parse_pcf_xml(existing_content, raw_xml_path=target)
            row = existing.header.iloc[0]
            if (
                row["fund_code"] == download.fund_code
                and pd.Timestamp(row["trading_day"]) == trading_day
                and existing_content == download.content
            ):
                return target, False
        except (OSError, ValueError):
            # 已存在但校验失败时，用本次已校验下载进行原子替换。
            pass

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{target.stem}.", suffix=".tmp.xml", dir=target.parent, delete=False
        ) as temporary:
            temporary.write(download.content)
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, target)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return target, True


def _missing_columns(frame: pd.DataFrame) -> tuple[str, ...]:
    missing: list[str] = []
    for column in frame.columns:
        values = frame[column]
        if values.isna().any() or (
            pd.api.types.is_string_dtype(values.dtype)
            and (values.astype("string").str.strip() == "").any()
        ):
            missing.append(column)
    return tuple(missing)


def _load_existing(
    header_path: Path, component_path: Path
) -> tuple[pd.DataFrame, pd.DataFrame]:
    header_exists = parquet_exists(header_path)
    component_exists = parquet_exists(component_path)
    if header_exists != component_exists:
        raise ValueError("PCF header/component Parquet files are inconsistent")
    if not header_exists:
        return _empty_headers(), _empty_components()
    headers = validate_pcf_headers(read_parquet(header_path))
    components = validate_pcf_components(read_parquet(component_path))
    _validate_record_counts(headers, components)
    return headers, components


def update_etf_pcf(
    fund_codes: Iterable[str],
    *,
    header_path: str | Path = DEFAULT_HEADER_PATH,
    component_path: str | Path = DEFAULT_COMPONENT_PATH,
    xml_dir: str | Path = DEFAULT_XML_DIR,
    state_path: str | Path = DEFAULT_STATE_PATH,
    downloader: Callable[[str], PcfXmlDownload] = download_latest_pcf_xml,
    etf_class_by_fund_code: Mapping[str, str] | None = None,
    request_interval: float = 0.2,
) -> PcfUpdateResult:
    """顺序检查指定 ETF 最新 PCF；不构造任何历史下载参数。"""
    if request_interval < 0:
        raise ValueError("request_interval cannot be negative")
    codes = tuple(dict.fromkeys(str(code).strip() for code in fund_codes))
    if not codes:
        raise ValueError("fund_codes cannot be empty")

    target_headers = Path(header_path)
    target_components = Path(component_path)
    local_headers, local_components = _load_existing(
        target_headers, target_components
    )
    known_keys = set(
        zip(local_headers.get("fund_code", []), local_headers.get("trading_day", []))
    )
    changed_headers: list[pd.DataFrame] = []
    changed_components: list[pd.DataFrame] = []
    fund_results: list[PcfFundUpdateResult] = []

    for index, code in enumerate(codes):
        if index:
            time.sleep(request_interval)
        download = downloader(code)
        official_class = (etf_class_by_fund_code or {}).get(code)
        parsed_without_path = parse_pcf_xml(download.content, etf_class=official_class)
        header_row = parsed_without_path.header.iloc[0]
        trading_day = pd.Timestamp(header_row["trading_day"])
        xml_path, xml_saved = _save_raw_xml(download, trading_day, xml_dir)
        parsed = parse_pcf_xml(
            download.content, raw_xml_path=xml_path, etf_class=official_class
        )
        header = validate_pcf_headers(parsed.header)
        components = validate_pcf_components(parsed.components)
        _validate_record_counts(header, components)
        key = (str(header.loc[0, "fund_code"]), pd.Timestamp(header.loc[0, "trading_day"]))
        is_new = key not in known_keys
        revised = False
        if not is_new:
            old_header = local_headers[
                (local_headers["fund_code"] == key[0])
                & (local_headers["trading_day"] == key[1])
            ].reset_index(drop=True)
            old_components = local_components[
                (local_components["fund_code"] == key[0])
                & (local_components["trading_day"] == key[1])
            ].reset_index(drop=True)
            # raw_xml_path 相同且内容相同才是真正 no_update；分类补录也属于兼容升级。
            revised = xml_saved or not header.equals(old_header) or not components.equals(old_components)
        if is_new or revised:
            changed_headers.append(header)
            changed_components.append(components)
            known_keys.add(key)
        component_codes = components["component_code"].astype("string")
        fund_results.append(
            PcfFundUpdateResult(
                fund_code=key[0],
                trading_day=key[1],
                record_number=int(header.loc[0, "record_number"]),
                component_count=len(components),
                status="updated" if is_new else ("revised" if revised else "no_update"),
                etf_class=None if pd.isna(header.loc[0, "etf_class"]) else str(header.loc[0, "etf_class"]),
                pcf_class=None if pd.isna(header.loc[0, "pcf_class"]) else str(header.loc[0, "pcf_class"]),
                xml_path=xml_path,
                xml_saved=xml_saved,
                missing_header_fields=_missing_columns(header),
                missing_component_fields=_missing_columns(components),
                non_six_digit_component_codes=int(
                    (~component_codes.str.fullmatch(r"\d{6}", na=False)).sum()
                ),
            )
        )

    parquet_written = bool(changed_headers)
    if parquet_written:
        changed_keys = {
            (str(frame.loc[0, "fund_code"]), pd.Timestamp(frame.loc[0, "trading_day"]))
            for frame in changed_headers
        }
        if not local_headers.empty:
            keep_header = [
                (str(row.fund_code), pd.Timestamp(row.trading_day)) not in changed_keys
                for row in local_headers.itertuples(index=False)
            ]
            local_headers = local_headers.loc[keep_header]
        if not local_components.empty:
            keep_component = [
                (str(row.fund_code), pd.Timestamp(row.trading_day)) not in changed_keys
                for row in local_components.itertuples(index=False)
            ]
            local_components = local_components.loc[keep_component]
        header_frames = ([local_headers] if not local_headers.empty else []) + changed_headers
        component_frames = (
            ([local_components] if not local_components.empty else []) + changed_components
        )
        headers = pd.concat(header_frames, ignore_index=True)
        components = pd.concat(component_frames, ignore_index=True)
        headers = headers.drop_duplicates(["fund_code", "trading_day"], keep="last")
        components = components.drop_duplicates(
            ["fund_code", "trading_day", "component_code"], keep="last"
        )
        headers = validate_pcf_headers(headers)
        components = validate_pcf_components(components)
        _validate_record_counts(headers, components)
        save_parquet(headers, target_headers)
        save_parquet(components, target_components)
    else:
        headers, components = local_headers, local_components

    statuses = {result.status for result in fund_results}
    status: Literal["updated", "revised", "no_update"] = (
        "updated" if "updated" in statuses else ("revised" if "revised" in statuses else "no_update")
    )
    state = {
        "source": "sse_etf_pcf",
        "last_successful_check_time": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "history_supported": False,
        "new_headers": sum(result.status == "updated" for result in fund_results),
        "new_components": sum(
            result.component_count for result in fund_results if result.status == "updated"
        ),
        "revised_headers": sum(result.status == "revised" for result in fund_results),
        "funds": [
            {
                "fund_code": result.fund_code,
                "trading_day": result.trading_day.date().isoformat(),
                "status": result.status,
                "etf_class": result.etf_class,
                "pcf_class": result.pcf_class,
                "record_number": result.record_number,
                "component_count": result.component_count,
                "xml_path": str(result.xml_path),
                "xml_saved": result.xml_saved,
            }
            for result in fund_results
        ],
    }
    _write_json_state(state_path, state)
    return PcfUpdateResult(
        status=status,
        funds=tuple(fund_results),
        headers=headers,
        components=components,
        header_path=target_headers,
        component_path=target_components,
        state_path=Path(state_path),
        parquet_written=parquet_written,
    )
