from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.crawlers.etf_pcf import (
    COMPONENT_SQL_ID,
    HEADER_SQL_ID,
    LIST_SQL_ID,
    PcfXmlDownload,
    download_latest_pcf_xml,
    fetch_etf_pcf_basic_info,
    fetch_etf_pcf_component_info,
    fetch_etf_pcf_list,
    parse_pcf_xml,
)


def make_xml(
    *,
    fund_code: str = "510050",
    trading_day: str = "20260814",
    component_code: str = "600028",
    record_number: int = 1,
    include_optional: bool = True,
    quantity: str = "4100",
    include_header_optional: bool = True,
) -> bytes:
    optional = (
        "<InstrumentName>中国石化</InstrumentName>"
        "<CreationPremiumRate>0.34</CreationPremiumRate>"
        "<RedemptionDiscountRate>0</RedemptionDiscountRate>"
        "<SubstitutionCashAmount>12.50</SubstitutionCashAmount>"
        "<UnderlyingSecurityID>101</UnderlyingSecurityID>"
        if include_optional
        else ""
    )
    component = (
        "<Component><InstrumentID>"
        f"{component_code}</InstrumentID>{optional}<Quantity>{quantity}</Quantity>"
        "<SubstitutionFlag>1</SubstitutionFlag></Component>"
    )
    header_optional = (
        "<MaxCashRatio>0.5</MaxCashRatio>"
        "<RedemptionLimit>3000000000</RedemptionLimit>"
        "<PublishIOPVFlag>1</PublishIOPVFlag>"
        "<CreationRedemptionSwitch>1</CreationRedemptionSwitch>"
        "<CreationRedemptionMechanism>0</CreationRedemptionMechanism>"
        if include_header_optional
        else ""
    )
    return (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<SSEPortfolioCompositionFile>"
        f"<FundInstrumentID>{fund_code}</FundInstrumentID>"
        "<CreationRedemptionUnit>900000</CreationRedemptionUnit>"
        f"<TradingDay>{trading_day}</TradingDay>"
        "<PreTradingDay>20260813</PreTradingDay>"
        "<NAVperCU>2732243.64</NAVperCU><NAV>3.0358</NAV>"
        "<PreCashComponent>59.64</PreCashComponent>"
        "<EstimatedCashComponent>0.64</EstimatedCashComponent>"
        f"{header_optional}"
        f"<RecordNumber>{record_number}</RecordNumber>"
        f"<ComponentList>{component}</ComponentList>"
        "</SSEPortfolioCompositionFile>"
    ).encode("utf-8")


class JsonpResponse:
    def __init__(self, callback: str, payload: dict[str, Any]) -> None:
        self.text = f"{callback}({json.dumps(payload, ensure_ascii=False)});"

    def raise_for_status(self) -> None:
        return None


class JsonpSession:
    def __init__(self, pages: list[list[dict[str, Any]]]) -> None:
        self.pages = pages
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, *, params: dict[str, Any], timeout: object) -> JsonpResponse:
        self.calls.append(params.copy())
        callback = params["jsonCallBack"]
        if params["sqlId"] == LIST_SQL_ID:
            page = int(params["pageHelp.pageNo"])
            rows = self.pages[page - 1]
            total = sum(len(value) for value in self.pages)
            payload = {
                "actionErrors": [],
                "result": rows,
                "pageHelp": {
                    "data": rows,
                    "pageNo": page,
                    "pageCount": len(self.pages),
                    "total": total,
                },
            }
        else:
            payload = {"actionErrors": [], "result": [{"FUNDID2": "510050"}]}
        return JsonpResponse(callback, payload)


def _list_row(code: str, day: str = "20260814") -> dict[str, str]:
    return {
        "FUNDID2": code,
        "TRADING_DAY": day,
        "ETF_CLASS": "01",
        "ETF_VERSION": "XML",
        "ETF_FULLNAME": f"基金{code}",
        "FUND_COMP_NAME": "测试基金公司",
    }


def test_pcf_list_uses_verified_parameters_and_all_pages() -> None:
    session = JsonpSession([[_list_row("510050")], [_list_row("588200")]])

    frame = fetch_etf_pcf_list(
        etf_class="01", session=session, page_size=1, request_interval=0
    )

    assert frame["fund_code"].tolist() == ["510050", "588200"]
    assert [call["pageHelp.pageNo"] for call in session.calls] == [1, 2]
    assert session.calls[0]["sqlId"] == LIST_SQL_ID
    assert session.calls[0]["type"] == "inParams"
    assert session.calls[0]["ETF_CLASS"] == "01"


def test_money_market_pcf_list_uses_official_classes() -> None:
    session = JsonpSession([[_list_row("511600")]])

    fetch_etf_pcf_list(etf_class="05,07", session=session, request_interval=0)

    assert session.calls[0]["ETF_CLASS"] == "05,07"


def test_pcf_detail_queries_use_verified_sql_ids() -> None:
    session = JsonpSession([])

    assert not fetch_etf_pcf_basic_info("510050", session=session).empty
    assert not fetch_etf_pcf_component_info("510050", session=session).empty

    assert [call["sqlId"] for call in session.calls] == [HEADER_SQL_ID, COMPONENT_SQL_ID]
    assert all(call["FUNDID2"] == "510050" for call in session.calls)
    assert all(call["isPagination"] == "false" for call in session.calls)


def test_xml_root_is_validated_and_html_is_rejected() -> None:
    with pytest.raises(ValueError, match="root"):
        parse_pcf_xml(b"<WrongRoot />")
    with pytest.raises(ValueError, match="HTML"):
        parse_pcf_xml(b"<html><body>system error</body></html>")


def test_pcf_header_components_and_numeric_conversion() -> None:
    parsed = parse_pcf_xml(
        make_xml(), raw_xml_path="510050_20260814.xml", etf_class="01"
    )
    header = parsed.header.iloc[0]
    component = parsed.components.iloc[0]

    assert header["fund_code"] == "510050"
    assert header["trading_day"] == pd.Timestamp("2026-08-14")
    assert header["creation_redemption_unit"] == 900000
    assert header["nav_per_cu"] == 2732243.64
    assert header["record_number"] == 1
    assert header["etf_class"] == "01"
    assert header["pcf_class"] == "etf"
    assert header["max_cash_ratio"] == 0.5
    assert header["redemption_limit"] == 3000000000
    assert header["publish_iopv_flag"] == "1"
    assert header["creation_redemption_switch"] == "1"
    assert header["creation_redemption_mechanism"] == "0"
    assert component["component_code"] == "600028"
    assert component["quantity"] == 4100
    assert component["creation_premium_rate"] == 0.34
    assert component["substitution_cash_amount"] == 12.5


def test_missing_optional_component_fields_are_nullable() -> None:
    component = parse_pcf_xml(make_xml(include_optional=False)).components.iloc[0]

    assert pd.isna(component["component_name"])
    assert pd.isna(component["creation_premium_rate"])
    assert pd.isna(component["substitution_cash_amount"])


def test_cross_border_component_code_is_not_forced_to_six_digits() -> None:
    component = parse_pcf_xml(make_xml(component_code="YUM")).components.iloc[0]

    assert component["component_code"] == "YUM"


def test_money_market_ssxj_and_optional_header_nodes() -> None:
    parsed = parse_pcf_xml(
        make_xml(fund_code="511600", component_code="SSXJ"), etf_class="05"
    )

    assert parsed.header.loc[0, "pcf_class"] == "money_market"
    assert parsed.components.loc[0, "component_code"] == "SSXJ"

    missing = parse_pcf_xml(make_xml(include_header_optional=False)).header.iloc[0]
    assert pd.isna(missing["max_cash_ratio"])
    assert pd.isna(missing["redemption_limit"])
    assert pd.isna(missing["publish_iopv_flag"])


def test_invalid_numeric_value_has_clear_error() -> None:
    with pytest.raises(ValueError, match="Quantity.*numeric"):
        parse_pcf_xml(make_xml(quantity="not-a-number"))


def test_record_number_must_match_component_nodes() -> None:
    with pytest.raises(ValueError, match="RecordNumber=2.*1 Component"):
        parse_pcf_xml(make_xml(record_number=2))


class XmlResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.status_code = 200
        self.url = "https://query.sse.com.cn/download?fundCode=510050"
        self.headers = {
            "Content-Type": "application/octet-stream;charset=UTF-8",
            "Content-Disposition": 'attachment;filename="pcf.xml"',
        }

    def raise_for_status(self) -> None:
        return None


class XmlSession:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.params: dict[str, Any] | None = None

    def get(self, url: str, *, params: dict[str, Any], timeout: object) -> XmlResponse:
        self.params = params.copy()
        return XmlResponse(self.content)


def test_download_uses_only_verified_fund_code_and_validates_xml_code() -> None:
    session = XmlSession(make_xml())

    result = download_latest_pcf_xml("510050", session=session)

    assert session.params == {"fundCode": "510050"}
    assert result.http_status == 200
    assert result.content.startswith(b"<?xml")

    with pytest.raises(ValueError, match="does not match"):
        download_latest_pcf_xml("588200", session=XmlSession(make_xml()))
