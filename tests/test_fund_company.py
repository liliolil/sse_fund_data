from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config.paths import PROCESSED_DATA_DIR
from src.crawlers import fund_company
from src.crawlers.fund_company import OUTPUT_COLUMNS, REFERER, fetch_fund_companies
from src.services.fund_company_service import (
    DEFAULT_PARQUET_PATH,
    company_business_id,
    update_fund_companies,
)


def _companies() -> pd.DataFrame:
    rows = [
        {
            "company_code": "900030",
            "company_name": "华夏基金管理有限公司",
            "company_name_en": "China AMC",
            "president_name": "测试",
            "register_capital": "23800",
            "address": "北京",
            "zip_code": "100000",
            "telephone": "010-1",
            "fax": None,
            "homepage": "example.com",
            "contact_name": "联系人",
            "contact_phone": "010-2",
            "raw_record_json": json.dumps({"COMPANY_CODE": "900030"}),
        },
        {
            "company_code": "-",
            "company_name": "无代码资产管理有限公司",
            "company_name_en": None,
            "president_name": None,
            "register_capital": None,
            "address": None,
            "zip_code": None,
            "telephone": None,
            "fax": None,
            "homepage": None,
            "contact_name": None,
            "contact_phone": None,
            "raw_record_json": json.dumps({"COMPANY_CODE": "-"}),
        },
    ]
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


class FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text
        self.encoding = None

    def raise_for_status(self) -> None:
        return None


class FakeCompanySession:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, *, params: dict[str, object], timeout: object) -> FakeResponse:
        self.calls.append(params.copy())
        page = int(params["pageHelp.pageNo"])
        row = {
            "COMPANY_CODE": "900030" if page == 1 else "-",
            "FULL_NAME": "公司甲" if page == 1 else "公司乙",
        }
        payload = {
            "success": "true",
            "result": [row],
            "pageHelp": {"total": 2, "pageCount": 2, "pageNo": page},
        }
        callback = params["jsonCallBack"]
        return FakeResponse(f"{callback}({json.dumps(payload, ensure_ascii=False)});")


def test_invalid_company_code_is_retained_and_name_is_business_key(tmp_path: Path) -> None:
    path = tmp_path / "companies.parquet"
    first = update_fund_companies(path, fetcher=_companies)
    before = path.read_bytes()
    second = update_fund_companies(path, fetcher=_companies)

    assert first.invalid_code_count == 1
    invalid = first.data[first.data["company_code"] == "-"].iloc[0]
    assert invalid["company_id"] == company_business_id("-", invalid["company_name"])
    assert second.status == "no_update" and not second.parquet_written
    assert path.read_bytes() == before


def test_company_crawler_paginates_and_uses_referer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeCompanySession()
    seen: list[str] = []

    def make_session(referer: str) -> FakeCompanySession:
        seen.append(referer)
        return session

    monkeypatch.setattr(fund_company, "make_reference_session", make_session)
    result = fetch_fund_companies(page_size=1, request_interval=0)

    assert seen == [REFERER]
    assert len(result) == 2
    assert [call["pageHelp.pageNo"] for call in session.calls] == [1, 2]
    assert result.loc[1, "company_code"] == "-"
    assert company_business_id(pd.NA, "公司乙") == "SSE:NAME:公司乙"


def test_company_default_path_is_absolute() -> None:
    assert DEFAULT_PARQUET_PATH == PROCESSED_DATA_DIR / "fund_companies.parquet"
    assert DEFAULT_PARQUET_PATH.is_absolute()
