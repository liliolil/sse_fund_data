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

from src.config.paths import HISTORY_DATA_DIR, PROCESSED_DATA_DIR, RAW_DATA_DIR, STATE_DIR
from src.crawlers import fund_master
from src.crawlers.fund_master import (
    CATEGORY_COLUMNS,
    PRODUCT_COLUMNS,
    REFERER,
    fetch_fund_categories,
    fetch_fund_products,
)
from src.services.fund_master_service import (
    DEFAULT_DETAIL_CACHE_DIR,
    DEFAULT_PARQUET_PATH,
    DEFAULT_SNAPSHOT_DIR,
    DEFAULT_STATE_PATH,
    MASTER_COLUMNS,
    build_category_mapping,
    stable_fund_id,
    update_fund_master,
)


class FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text
        self.encoding = None

    def raise_for_status(self) -> None:
        return None


class FakeSession:
    def __init__(
        self,
        *,
        pages: list[list[dict[str, Any]]] | None = None,
        categories: dict[str, list[dict[str, str]]] | None = None,
        system_error: bool = False,
    ) -> None:
        self.pages = pages or []
        self.categories = categories or {}
        self.system_error = system_error
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, *, params: dict[str, Any], timeout: object) -> FakeResponse:
        self.calls.append(params.copy())
        callback = params["jsonCallBack"]
        if self.system_error:
            return FakeResponse(
                f'{callback}({{"success":"false","error":"System Error"}});'
            )
        if params["sqlId"] == fund_master.CATEGORY_SQL_ID:
            rows = self.categories.get(params["CATEGORY_PARENT_CODE"], [])
            payload = {"success": "true", "result": rows}
        else:
            page_no = int(params["pageHelp.pageNo"])
            rows = self.pages[page_no - 1]
            total = sum(len(page) for page in self.pages)
            payload = {
                "success": "true",
                "result": rows,
                "pageHelp": {
                    "total": total,
                    "pageCount": len(self.pages),
                    "pageNo": page_no,
                },
            }
        return FakeResponse(f"{callback}({json.dumps(payload, ensure_ascii=False)});")


def _raw_product(code: str, category: str = "F111", name: str = "测试基金") -> dict[str, str]:
    return {
        "FUND_CODE": code,
        "FUND_ABBR": name,
        "FUND_EXPANSION_ABBR": f"{name}扩位",
        "CATEGORY": category,
        "COMPANY_CODE": "900030",
        "COMPANY_NAME": "测试基金管理有限公司",
        "INDEX_NAME": "测试指数",
        "LISTING_DATE": "2026-08-14",
        "SCALE": "1.0",
    }


def _categories() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"category_code": "F100", "parent_code": "F000", "category_name": "ETF"},
            {
                "category_code": "F110",
                "parent_code": "F100",
                "category_name": "股票ETF",
            },
            {
                "category_code": "F111",
                "parent_code": "F110",
                "category_name": "单市场股票（沪）ETF",
            },
        ],
        columns=CATEGORY_COLUMNS,
    )


def _products(*rows: tuple[str, str]) -> pd.DataFrame:
    records = []
    for code, name in rows:
        record = _raw_product(code, name=name)
        records.append(
            {
                "fund_code": code,
                "fund_name": name,
                "fund_expand_name": f"{name}扩位",
                "fund_type_code": "F111",
                "management_company_code": "900030",
                "management_company_name": "测试基金管理有限公司",
                "underlying_index_name": "测试指数",
                "list_date": pd.Timestamp("2026-08-14"),
                "source": "sse_unified_fund_list",
                "raw_record_json": json.dumps(record, ensure_ascii=False),
            }
        )
    frame = pd.DataFrame(records, columns=PRODUCT_COLUMNS)
    for column in set(PRODUCT_COLUMNS) - {"list_date"}:
        frame[column] = frame[column].astype("string")
    frame.attrs["api_total"] = len(frame)
    return frame


def _legacy(codes: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "fund_code": pd.Series(codes, dtype="string"),
            "underlying_index_code": pd.Series(["000001"] * len(codes), dtype="string"),
            "custodian": pd.Series(["测试托管人"] * len(codes), dtype="string"),
        }
    )


def _detail(code: str) -> dict[str, Any]:
    return {
        "fund_code": code,
        "fund_legal_name": f"基金{code}法定全称",
        "establish_date": "2026-01-01",
        "custodian": "测试托管人",
        "fund_manager_person": "测试经理",
        "detail_raw_record_json": "{}",
    }


def test_category_tree_recursion_and_mapping() -> None:
    session = FakeSession(
        categories={
            "F000": [
                {
                    "CATEGORY_CODE": "F100",
                    "CATEGORY_PARENT_CODE": "F000",
                    "CATEGORY_NAME": "ETF",
                }
            ],
            "F100": [
                {
                    "CATEGORY_CODE": "F111",
                    "CATEGORY_PARENT_CODE": "F100",
                    "CATEGORY_NAME": "单市场股票（沪）ETF",
                }
            ],
            "F111": [],
        }
    )

    categories = fetch_fund_categories(session=session, request_interval=0)
    mapping = build_category_mapping(categories)

    assert [call["CATEGORY_PARENT_CODE"] for call in session.calls] == [
        "F000",
        "F100",
        "F111",
    ]
    assert mapping["F111"] == ("单市场股票（沪）ETF", "ETF")


def test_unified_list_pagination_and_parameters() -> None:
    session = FakeSession(pages=[[_raw_product("510050")], [_raw_product("510300")]])

    frame = fetch_fund_products(session=session, page_size=1, request_interval=0)

    assert frame["fund_code"].tolist() == ["510050", "510300"]
    assert frame.attrs["api_total"] == 2
    assert [call["pageHelp.pageNo"] for call in session.calls] == [1, 2]
    assert all(call["CATEGORY"] == "F000" for call in session.calls)


def test_referer_and_http_200_business_error(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    session = FakeSession(pages=[[_raw_product("510050")]])

    def make_session(referer: str) -> FakeSession:
        seen.append(referer)
        return session

    monkeypatch.setattr(fund_master, "make_reference_session", make_session)
    fetch_fund_products(request_interval=0)
    assert seen == [REFERER]

    with pytest.raises(RuntimeError, match="business error"):
        fetch_fund_products(
            session=FakeSession(system_error=True), request_interval=0
        )


def test_stable_fund_id_and_incremental_classification(tmp_path: Path) -> None:
    path = tmp_path / "processed" / "fund_master.parquet"
    state = tmp_path / "state" / "fund_master.json"
    snapshots = tmp_path / "history"
    cache = tmp_path / "raw" / "details"
    calls: list[str] = []

    def detail_fetcher(code: str) -> dict[str, Any]:
        calls.append(code)
        return _detail(code)

    first_products = _products(
        ("510050", "基金A"), ("510300", "基金B"), ("513500", "基金C")
    )
    first = update_fund_master(
        path,
        state_path=state,
        snapshot_dir=snapshots,
        detail_cache_dir=cache,
        product_fetcher=lambda: first_products,
        category_fetcher=_categories,
        legacy_fetcher=lambda: _legacy(["510050", "510300", "513500"]),
        detail_fetcher=detail_fetcher,
        detail_request_interval=0,
        observed_at=pd.Timestamp("2026-08-15T01:00:00Z"),
    )
    second_products = _products(
        ("510050", "基金A已变更"), ("510300", "基金B"), ("588200", "基金D")
    )
    second = update_fund_master(
        path,
        state_path=state,
        snapshot_dir=snapshots,
        detail_cache_dir=cache,
        product_fetcher=lambda: second_products,
        category_fetcher=_categories,
        legacy_fetcher=lambda: _legacy(["510050", "510300", "588200"]),
        detail_fetcher=detail_fetcher,
        detail_request_interval=0,
        observed_at=pd.Timestamp("2026-08-15T02:00:00Z"),
    )
    before = path.read_bytes()
    third = update_fund_master(
        path,
        state_path=state,
        snapshot_dir=snapshots,
        detail_cache_dir=cache,
        product_fetcher=lambda: second_products,
        category_fetcher=_categories,
        legacy_fetcher=lambda: _legacy(["510050", "510300", "588200"]),
        detail_fetcher=detail_fetcher,
        detail_request_interval=0,
        observed_at=pd.Timestamp("2026-08-15T03:00:00Z"),
    )

    assert stable_fund_id("sse", "510050") == "SSE:510050"
    assert first.status == "initialized" and first.new_count == 3
    assert second.status == "updated"
    assert (second.new_count, second.changed_count, second.unchanged_count, second.missing_count) == (
        1,
        1,
        1,
        1,
    )
    assert second.local_total == 4  # 远端缺失项只保留并告警，不自动删除/退市。
    assert calls == ["510050", "510300", "513500", "588200"]
    assert third.status == "no_update" and not third.parquet_written
    assert path.read_bytes() == before
    assert len(list(snapshots.glob("*.parquet"))) == 1
    saved_state = json.loads(state.read_text(encoding="utf-8"))
    assert saved_state["missing_count"] == 1
    assert not third.data.duplicated(["market", "fund_code"]).any()


def test_existing_missing_detail_is_requested_once_and_cached(tmp_path: Path) -> None:
    path = tmp_path / "master.parquet"
    state = tmp_path / "state.json"
    snapshots = tmp_path / "snapshots"
    cache = tmp_path / "details"
    product = _products(("510050", "基金A"))
    calls: list[str] = []

    update_fund_master(
        path,
        state_path=state,
        snapshot_dir=snapshots,
        detail_cache_dir=cache,
        product_fetcher=lambda: product,
        category_fetcher=_categories,
        legacy_fetcher=lambda: _legacy(["510050"]),
        detail_fetcher=lambda code: {**_detail(code), "fund_legal_name": None},
        detail_request_interval=0,
    )
    cache_file = cache / "510050.json"
    cache_file.unlink()

    def refill(code: str) -> dict[str, Any]:
        calls.append(code)
        return _detail(code)

    result = update_fund_master(
        path,
        state_path=state,
        snapshot_dir=snapshots,
        detail_cache_dir=cache,
        product_fetcher=lambda: product,
        category_fetcher=_categories,
        legacy_fetcher=lambda: _legacy(["510050"]),
        detail_fetcher=refill,
        detail_request_interval=0,
    )
    assert calls == ["510050"]
    assert result.changed_count == 1
    assert cache_file.is_file()


def test_default_paths_are_cwd_independent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(PROJECT_ROOT.parents[1])
    assert DEFAULT_PARQUET_PATH == PROCESSED_DATA_DIR / "fund_master.parquet"
    assert DEFAULT_STATE_PATH == STATE_DIR / "fund_master_update_state.json"
    assert DEFAULT_SNAPSHOT_DIR == HISTORY_DATA_DIR / "fund_master_snapshots"
    assert DEFAULT_DETAIL_CACHE_DIR == RAW_DATA_DIR / "fund_master" / "details"
    assert all(
        path.is_absolute()
        for path in (
            DEFAULT_PARQUET_PATH,
            DEFAULT_STATE_PATH,
            DEFAULT_SNAPSHOT_DIR,
            DEFAULT_DETAIL_CACHE_DIR,
        )
    )
    monkeypatch.chdir(PROJECT_ROOT)
