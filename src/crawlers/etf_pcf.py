"""上海证券交易所 ETF 申购赎回清单（PCF）采集与 XML 解析。"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.crawlers.scale_common import fetch_paginated_scale_rows, get_jsonp


QUERY_URL = "https://query.sse.com.cn/commonQuery.do"
DOWNLOAD_URL = "https://query.sse.com.cn/etfDownload/downloadETF2Bulletin.do"
REFERER = "https://www.sse.com.cn/disclosure/fund/etflist/"
LIST_SQL_ID = "COMMON_SSE_PL_ETFGGSGSHQD_L"
HEADER_SQL_ID = "COMMON_SSE_CP_JJLB_ETFJJGK_GGSGSHQD_JBXX_C"
COMPONENT_SQL_ID = "COMMON_SSE_CP_JJLB_ETFJJGK_GGSGSHQD_COMPONENT_C"
XML_ROOT = "SSEPortfolioCompositionFile"

LIST_COLUMNS = [
    "fund_code",
    "trading_day",
    "etf_class",
    "etf_version",
    "fund_full_name",
    "fund_company",
    "raw_record_json",
]
HEADER_COLUMNS = [
    "fund_code",
    "trading_day",
    "etf_class",
    "pcf_class",
    "pre_trading_day",
    "creation_redemption_unit",
    "nav_per_cu",
    "nav",
    "pre_cash_component",
    "estimated_cash_component",
    "max_cash_ratio",
    "redemption_limit",
    "publish_iopv_flag",
    "creation_redemption_switch",
    "creation_redemption_mechanism",
    "record_number",
    "raw_xml_path",
]

MONEY_MARKET_ETF_CLASSES = frozenset({"05", "07"})
COMPONENT_COLUMNS = [
    "fund_code",
    "trading_day",
    "component_code",
    "component_name",
    "quantity",
    "substitution_flag",
    "creation_premium_rate",
    "redemption_discount_rate",
    "substitution_cash_amount",
    "underlying_security_id",
]


@dataclass(frozen=True)
class PcfXmlDownload:
    fund_code: str
    request_url: str
    http_status: int
    content_type: str
    content_disposition: str
    content: bytes


@dataclass(frozen=True)
class ParsedPcf:
    header: pd.DataFrame
    components: pd.DataFrame


def make_pcf_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127 Safari/537.36"
            ),
            "Referer": REFERER,
        }
    )
    return session


def _normalise_fund_code(value: str) -> str:
    code = str(value).strip()
    if not code.isdigit() or len(code) != 6:
        raise ValueError("fund_code must be a six-digit string")
    return code


def _json_text(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fetch_etf_pcf_list(
    *,
    etf_class: str = "",
    fund_code: str = "",
    keywords: str = "",
    timeout: tuple[float, float] = (5.0, 30.0),
    request_interval: float = 0.2,
    page_size: int = 100,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """分页查询 ETF PCF 列表；接口只提供当前最新清单信息。"""
    code = _normalise_fund_code(fund_code) if fund_code else ""
    client = session or make_pcf_session()
    records = fetch_paginated_scale_rows(
        client,
        {
            "sqlId": LIST_SQL_ID,
            "ETF_CLASS": str(etf_class).strip(),
            "type": "inParams",
            "FUND_CODE": code,
            "KEY_WORDS": str(keywords).strip(),
        },
        timeout=timeout,
        request_interval=request_interval,
        page_size=page_size,
    )
    if not records:
        return pd.DataFrame(columns=LIST_COLUMNS)
    raw = pd.DataFrame.from_records(records)
    required = {"FUNDID2", "TRADING_DAY"}
    missing = required.difference(raw.columns)
    if missing:
        raise ValueError(f"ETF PCF list response is missing fields: {sorted(missing)}")
    frame = pd.DataFrame(
        {
            "fund_code": raw["FUNDID2"].astype("string").str.strip().str.zfill(6),
            "trading_day": pd.to_datetime(
                raw["TRADING_DAY"], format="%Y%m%d", errors="raise"
            ),
            "etf_class": raw.get("ETF_CLASS", pd.Series(pd.NA, index=raw.index)).astype(
                "string"
            ),
            "etf_version": raw.get(
                "ETF_VERSION", pd.Series(pd.NA, index=raw.index)
            ).astype("string"),
            "fund_full_name": raw.get(
                "ETF_FULLNAME", pd.Series(pd.NA, index=raw.index)
            ).astype("string"),
            "fund_company": raw.get(
                "FUND_COMP_NAME", pd.Series(pd.NA, index=raw.index)
            ).astype("string"),
            "raw_record_json": pd.Series([_json_text(row) for row in records], dtype="string"),
        }
    )
    if frame.duplicated(["fund_code", "trading_day"]).any():
        raise ValueError("ETF PCF list contains duplicate fund_code + trading_day keys")
    return frame[LIST_COLUMNS].reset_index(drop=True)


def standardize_pcf_class(etf_class: object) -> object:
    """按官方 ETF_CLASS 标准化 PCF 分类；未知分类不根据代码猜测。"""
    if etf_class is None or etf_class is pd.NA or not str(etf_class).strip():
        return pd.NA
    return "money_market" if str(etf_class).strip() in MONEY_MARKET_ETF_CLASSES else "etf"


def _fetch_detail_records(
    fund_code: str,
    sql_id: str,
    *,
    timeout: tuple[float, float],
    session: requests.Session | None,
) -> list[dict[str, Any]]:
    code = _normalise_fund_code(fund_code)
    client = session or make_pcf_session()
    payload = get_jsonp(
        client,
        QUERY_URL,
        {"isPagination": "false", "FUNDID2": code, "sqlId": sql_id},
        timeout,
    )
    rows = payload.get("result")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("ETF PCF detail response has no result object list")
    return rows


def fetch_etf_pcf_basic_info(
    fund_code: str,
    *,
    timeout: tuple[float, float] = (5.0, 30.0),
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """查询页面当前展示的 PCF 基本信息 JSONP。"""
    return pd.DataFrame.from_records(
        _fetch_detail_records(
            fund_code, HEADER_SQL_ID, timeout=timeout, session=session
        )
    )


def fetch_etf_pcf_component_info(
    fund_code: str,
    *,
    timeout: tuple[float, float] = (5.0, 30.0),
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """查询页面当前展示的 PCF 成分券 JSONP。"""
    return pd.DataFrame.from_records(
        _fetch_detail_records(
            fund_code, COMPONENT_SQL_ID, timeout=timeout, session=session
        )
    )


def _validated_root(content: bytes) -> ET.Element:
    if not content.strip():
        raise ValueError("PCF XML response is empty")
    upper_prefix = content[:4096].upper()
    if b"<!DOCTYPE" in upper_prefix or b"<!ENTITY" in upper_prefix:
        raise ValueError("PCF XML must not contain DTD or external entities")
    if b"<HTML" in upper_prefix:
        raise ValueError("PCF download returned HTML instead of XML")
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ValueError("PCF response is not valid XML") from exc
    if root.tag != XML_ROOT:
        raise ValueError(f"Unexpected PCF XML root: {root.tag!r}")
    return root


def download_latest_pcf_xml(
    fund_code: str,
    *,
    timeout: tuple[float, float] = (5.0, 30.0),
    session: requests.Session | None = None,
) -> PcfXmlDownload:
    """下载单只 ETF 最新 PCF；公开接口没有已验证的历史日期参数。"""
    code = _normalise_fund_code(fund_code)
    client = session or make_pcf_session()
    response = client.get(DOWNLOAD_URL, params={"fundCode": code}, timeout=timeout)
    response.raise_for_status()
    content = bytes(response.content)
    root = _validated_root(content)
    xml_code = (root.findtext("FundInstrumentID") or "").strip()
    if xml_code != code:
        raise ValueError(
            f"PCF XML fund code {xml_code!r} does not match requested code {code!r}"
        )
    return PcfXmlDownload(
        fund_code=code,
        request_url=str(getattr(response, "url", DOWNLOAD_URL)),
        http_status=int(response.status_code),
        content_type=str(response.headers.get("Content-Type", "")),
        content_disposition=str(response.headers.get("Content-Disposition", "")),
        content=content,
    )


def _required_text(parent: ET.Element, tag: str) -> str:
    value = parent.findtext(tag)
    if value is None or not value.strip():
        raise ValueError(f"PCF XML is missing required node {tag}")
    return value.strip()


def _optional_text(parent: ET.Element, tag: str) -> object:
    value = parent.findtext(tag)
    return value.strip() if value is not None and value.strip() else pd.NA


def _number(value: object, field: str, *, integer: bool = False) -> object:
    if value is pd.NA or value is None or str(value).strip() == "":
        return pd.NA
    text = str(value).strip().replace(",", "")
    try:
        number = pd.to_numeric(text, errors="raise")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"PCF XML field {field} is not numeric: {value!r}") from exc
    if integer:
        numeric_float = float(number)
        if not numeric_float.is_integer():
            raise ValueError(f"PCF XML field {field} must be an integer: {value!r}")
        return int(numeric_float)
    return float(number)


def parse_pcf_xml(
    content: bytes,
    *,
    raw_xml_path: str | Path | None = None,
    etf_class: str | None = None,
) -> ParsedPcf:
    """安全解析 PCF XML，并严格核对 RecordNumber 与成分节点数。"""
    root = _validated_root(content)
    fund_code = _normalise_fund_code(_required_text(root, "FundInstrumentID"))
    trading_day = pd.to_datetime(
        _required_text(root, "TradingDay"), format="%Y%m%d", errors="raise"
    )
    pre_trading_day = pd.to_datetime(
        _required_text(root, "PreTradingDay"), format="%Y%m%d", errors="raise"
    )
    record_number = _number(
        _required_text(root, "RecordNumber"), "RecordNumber", integer=True
    )
    header = pd.DataFrame(
        {
            "fund_code": pd.Series([fund_code], dtype="string"),
            "trading_day": [trading_day],
            "etf_class": pd.Series(
                [str(etf_class).strip() if etf_class else pd.NA], dtype="string"
            ),
            "pcf_class": pd.Series([standardize_pcf_class(etf_class)], dtype="string"),
            "pre_trading_day": [pre_trading_day],
            "creation_redemption_unit": pd.Series(
                [_number(_required_text(root, "CreationRedemptionUnit"), "CreationRedemptionUnit", integer=True)],
                dtype="Int64",
            ),
            "nav_per_cu": pd.Series(
                [_number(_required_text(root, "NAVperCU"), "NAVperCU")], dtype="Float64"
            ),
            "nav": pd.Series(
                [_number(_required_text(root, "NAV"), "NAV")], dtype="Float64"
            ),
            "pre_cash_component": pd.Series(
                [_number(_required_text(root, "PreCashComponent"), "PreCashComponent")],
                dtype="Float64",
            ),
            "estimated_cash_component": pd.Series(
                [_number(_required_text(root, "EstimatedCashComponent"), "EstimatedCashComponent")],
                dtype="Float64",
            ),
            "max_cash_ratio": pd.Series(
                [_number(_optional_text(root, "MaxCashRatio"), "MaxCashRatio")],
                dtype="Float64",
            ),
            "redemption_limit": pd.Series(
                [_number(_optional_text(root, "RedemptionLimit"), "RedemptionLimit")],
                dtype="Float64",
            ),
            "publish_iopv_flag": pd.Series(
                [_optional_text(root, "PublishIOPVFlag")], dtype="string"
            ),
            "creation_redemption_switch": pd.Series(
                [_optional_text(root, "CreationRedemptionSwitch")], dtype="string"
            ),
            "creation_redemption_mechanism": pd.Series(
                [_optional_text(root, "CreationRedemptionMechanism")], dtype="string"
            ),
            "record_number": pd.Series([record_number], dtype="Int64"),
            "raw_xml_path": pd.Series(
                [str(raw_xml_path) if raw_xml_path is not None else pd.NA], dtype="string"
            ),
        },
        columns=HEADER_COLUMNS,
    )

    component_nodes = root.findall("./ComponentList/Component")
    if record_number != len(component_nodes):
        raise ValueError(
            f"PCF RecordNumber={record_number} but XML contains "
            f"{len(component_nodes)} Component nodes"
        )
    rows: list[dict[str, object]] = []
    for node in component_nodes:
        rows.append(
            {
                "fund_code": fund_code,
                "trading_day": trading_day,
                "component_code": _required_text(node, "InstrumentID"),
                "component_name": _optional_text(node, "InstrumentName"),
                "quantity": _number(_required_text(node, "Quantity"), "Quantity"),
                "substitution_flag": _required_text(node, "SubstitutionFlag"),
                "creation_premium_rate": _number(
                    _optional_text(node, "CreationPremiumRate"), "CreationPremiumRate"
                ),
                "redemption_discount_rate": _number(
                    _optional_text(node, "RedemptionDiscountRate"), "RedemptionDiscountRate"
                ),
                "substitution_cash_amount": _number(
                    _optional_text(node, "SubstitutionCashAmount"), "SubstitutionCashAmount"
                ),
                "underlying_security_id": _optional_text(node, "UnderlyingSecurityID"),
            }
        )
    components = pd.DataFrame.from_records(rows, columns=COMPONENT_COLUMNS)
    if components.empty:
        components = pd.DataFrame(columns=COMPONENT_COLUMNS)
    else:
        for column in (
            "fund_code",
            "component_code",
            "component_name",
            "substitution_flag",
            "underlying_security_id",
        ):
            components[column] = components[column].astype("string")
        for column in (
            "quantity",
            "creation_premium_rate",
            "redemption_discount_rate",
            "substitution_cash_amount",
        ):
            components[column] = pd.to_numeric(components[column], errors="raise").astype(
                "Float64"
            )
        components["trading_day"] = pd.to_datetime(components["trading_day"])
        if components.duplicated(
            ["fund_code", "trading_day", "component_code"]
        ).any():
            raise ValueError("PCF XML contains duplicate component_code values")
    return ParsedPcf(header=header, components=components)
