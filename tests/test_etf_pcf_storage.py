from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config.paths import PROCESSED_DATA_DIR, RAW_DATA_DIR, STATE_DIR
from src.crawlers.etf_pcf import PcfXmlDownload
from src.services.etf_pcf_service import (
    DEFAULT_COMPONENT_PATH,
    DEFAULT_HEADER_PATH,
    DEFAULT_STATE_PATH,
    DEFAULT_XML_DIR,
    update_etf_pcf,
    validate_pcf_headers,
    validate_pcf_components,
)
from src.storage.parquet_store import read_parquet


def make_xml(
    *, fund_code: str, trading_day: str, component_code: str
) -> bytes:
    return (
        "<SSEPortfolioCompositionFile>"
        f"<FundInstrumentID>{fund_code}</FundInstrumentID>"
        "<CreationRedemptionUnit>900000</CreationRedemptionUnit>"
        f"<TradingDay>{trading_day}</TradingDay>"
        "<PreTradingDay>20260813</PreTradingDay>"
        "<NAVperCU>2732243.64</NAVperCU><NAV>3.0358</NAV>"
        "<PreCashComponent>59.64</PreCashComponent>"
        "<EstimatedCashComponent>0.64</EstimatedCashComponent>"
        "<RecordNumber>1</RecordNumber><ComponentList><Component>"
        f"<InstrumentID>{component_code}</InstrumentID>"
        "<InstrumentName>测试成分</InstrumentName><Quantity>100</Quantity>"
        "<SubstitutionFlag>1</SubstitutionFlag>"
        "</Component></ComponentList></SSEPortfolioCompositionFile>"
    ).encode("utf-8")


def downloader_for(
    *, trading_day: str = "20260814", component_code: str = "600028"
):
    def download(code: str) -> PcfXmlDownload:
        content = make_xml(
            fund_code=code,
            trading_day=trading_day,
            component_code=component_code,
        )
        return PcfXmlDownload(
            fund_code=code,
            request_url=f"https://example.test/pcf?fundCode={code}",
            http_status=200,
            content_type="application/octet-stream;charset=UTF-8",
            content_disposition=f'attachment;filename="{code}.xml"',
            content=content,
        )

    return download


def test_update_saves_xml_and_parquet_in_tmp_path(tmp_path: Path) -> None:
    header_path = tmp_path / "processed" / "headers.parquet"
    component_path = tmp_path / "processed" / "components.parquet"
    xml_dir = tmp_path / "raw" / "xml"
    state_path = tmp_path / "state" / "pcf.json"

    result = update_etf_pcf(
        ["510050", "513500"],
        header_path=header_path,
        component_path=component_path,
        xml_dir=xml_dir,
        state_path=state_path,
        downloader=downloader_for(component_code="YUM"),
        request_interval=0,
    )

    assert result.status == "updated"
    assert result.parquet_written
    assert len(read_parquet(header_path)) == 2
    assert len(read_parquet(component_path)) == 2
    assert (xml_dir / "510050_20260814.xml").is_file()
    assert (xml_dir / "513500_20260814.xml").is_file()
    assert result.funds[0].non_six_digit_component_codes == 1
    assert state_path.is_file()


def test_second_run_is_no_update_and_does_not_rewrite_files(tmp_path: Path) -> None:
    header_path = tmp_path / "headers.parquet"
    component_path = tmp_path / "components.parquet"
    xml_dir = tmp_path / "xml"
    state_path = tmp_path / "pcf.json"
    arguments = dict(
        header_path=header_path,
        component_path=component_path,
        xml_dir=xml_dir,
        state_path=state_path,
        downloader=downloader_for(),
        request_interval=0,
    )
    update_etf_pcf(["510050"], **arguments)
    original_header = header_path.read_bytes()
    original_components = component_path.read_bytes()
    original_xml = (xml_dir / "510050_20260814.xml").read_bytes()

    result = update_etf_pcf(["510050"], **arguments)

    assert result.status == "no_update"
    assert not result.parquet_written
    assert not result.funds[0].xml_saved
    assert header_path.read_bytes() == original_header
    assert component_path.read_bytes() == original_components
    assert (xml_dir / "510050_20260814.xml").read_bytes() == original_xml


def test_same_day_revision_replaces_rows(tmp_path: Path) -> None:
    arguments = dict(
        header_path=tmp_path / "headers.parquet",
        component_path=tmp_path / "components.parquet",
        xml_dir=tmp_path / "xml",
        state_path=tmp_path / "state.json",
        request_interval=0,
    )
    update_etf_pcf(["510050"], downloader=downloader_for(), **arguments)
    revised = update_etf_pcf(
        ["510050"],
        downloader=downloader_for(component_code="SSXJ"),
        etf_class_by_fund_code={"510050": "05"},
        **arguments,
    )

    assert revised.status == "revised"
    assert revised.funds[0].status == "revised"
    assert revised.headers.loc[0, "pcf_class"] == "money_market"
    assert revised.components.loc[0, "component_code"] == "SSXJ"


def test_old_header_schema_is_aligned_with_nullable_new_fields() -> None:
    old = pd.DataFrame(
        {
            "fund_code": ["510050"],
            "trading_day": ["2026-08-14"],
            "pre_trading_day": ["2026-08-13"],
            "creation_redemption_unit": [900000],
            "nav_per_cu": [1.0],
            "nav": [1.0],
            "pre_cash_component": [0.0],
            "estimated_cash_component": [0.0],
            "record_number": [1],
            "raw_xml_path": ["old.xml"],
        }
    )

    upgraded = validate_pcf_headers(old)

    for column in (
        "etf_class",
        "pcf_class",
        "max_cash_ratio",
        "redemption_limit",
        "publish_iopv_flag",
        "creation_redemption_switch",
        "creation_redemption_mechanism",
    ):
        assert column in upgraded.columns
        assert pd.isna(upgraded.loc[0, column])


def test_old_state_shape_remains_compatible_with_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import src.cli as cli

    state_path = tmp_path / "state.json"
    state_path.write_text('{"fund_codes":["510050","511600"]}', encoding="utf-8")
    monkeypatch.setattr(cli, "ETF_PCF_STATE_PATH", state_path)

    assert cli._configured_pcf_codes() == ("510050", "511600")


def test_duplicate_fund_input_does_not_duplicate_parquet(tmp_path: Path) -> None:
    result = update_etf_pcf(
        ["510050", "510050"],
        header_path=tmp_path / "headers.parquet",
        component_path=tmp_path / "components.parquet",
        xml_dir=tmp_path / "xml",
        state_path=tmp_path / "state.json",
        downloader=downloader_for(),
        request_interval=0,
    )

    assert len(result.headers) == 1
    assert len(result.components) == 1
    assert not result.headers.duplicated(["fund_code", "trading_day"]).any()


def test_component_validator_rejects_duplicate_source_key() -> None:
    frame = pd.DataFrame(
        {
            "fund_code": ["510050", "510050"],
            "trading_day": pd.to_datetime(["2026-08-14", "2026-08-14"]),
            "component_code": ["600028", "600028"],
            "component_name": ["中国石化", "中国石化"],
            "quantity": [1, 1],
            "substitution_flag": ["1", "1"],
            "creation_premium_rate": [0.1, 0.1],
            "redemption_discount_rate": [0.0, 0.0],
            "substitution_cash_amount": [pd.NA, pd.NA],
            "underlying_security_id": ["101", "101"],
        }
    )

    with pytest.raises(ValueError, match="duplicate"):
        validate_pcf_components(frame)


def test_default_paths_are_project_based_when_cwd_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(PROJECT_ROOT.parents[1])
    assert DEFAULT_HEADER_PATH == PROCESSED_DATA_DIR / "etf_pcf_headers.parquet"
    assert DEFAULT_COMPONENT_PATH == PROCESSED_DATA_DIR / "etf_pcf_components.parquet"
    assert DEFAULT_XML_DIR == RAW_DATA_DIR / "etf_pcf" / "xml"
    assert DEFAULT_STATE_PATH == STATE_DIR / "etf_pcf_update_state.json"
    assert all(
        path.is_absolute()
        for path in (
            DEFAULT_HEADER_PATH,
            DEFAULT_COMPONENT_PATH,
            DEFAULT_XML_DIR,
            DEFAULT_STATE_PATH,
        )
    )
    monkeypatch.chdir(PROJECT_ROOT)
