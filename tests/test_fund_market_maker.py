from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config.paths import HISTORY_DATA_DIR, PROCESSED_DATA_DIR
from src.crawlers import fund_market_maker
from src.crawlers.fund_market_maker import (
    RELATION_COLUMNS,
    RELATION_REFERER,
    fetch_fund_market_makers,
)
from src.services.fund_market_maker_service import (
    DEFAULT_PARQUET_PATH,
    DEFAULT_SNAPSHOT_DIR,
    update_fund_market_makers,
    validate_fund_market_makers,
)


def _relations() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "market": pd.Series(["SSE", "SSE"], dtype="string"),
            "fund_code": pd.Series(["510050", "510050"], dtype="string"),
            "fund_name": pd.Series(["上证50ETF华夏"] * 2, dtype="string"),
            "firm_name": pd.Series(["做市商甲", "做市商乙"], dtype="string"),
            "service_type": pd.Series(["主", "一般"], dtype="string"),
            "source": pd.Series(["sse_fund_market_maker"] * 2, dtype="string"),
            "raw_record_json": pd.Series(
                [json.dumps({"NUM": 1}), json.dumps({"NUM": 2})], dtype="string"
            ),
        },
        columns=RELATION_COLUMNS,
    )


class FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text
        self.encoding = None

    def raise_for_status(self) -> None:
        return None


class FakeRelationSession:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, *, params: dict[str, object], timeout: object) -> FakeResponse:
        self.calls.append(params.copy())
        page = int(params["pageHelp.pageNo"])
        row = {
            "SECURITY_CODE": "510050",
            "SEC_NAME_FULL": "上证50ETF华夏",
            "FIRM_NAME": f"做市商{page}",
            "SERVICE_TYPE": "主" if page == 1 else "一般",
        }
        payload = {
            "success": "true",
            "result": [row],
            "pageHelp": {"total": 2, "pageCount": 2, "pageNo": page},
        }
        callback = params["jsonCallBack"]
        return FakeResponse(f"{callback}({json.dumps(payload, ensure_ascii=False)});")


def test_market_maker_one_to_many_snapshot_and_no_update(tmp_path: Path) -> None:
    path = tmp_path / "market_makers.parquet"
    snapshots = tmp_path / "history"
    first = update_fund_market_makers(
        path,
        snapshot_dir=snapshots,
        fetcher=_relations,
        observed_at=pd.Timestamp("2026-08-15T00:00:00Z"),
    )
    before = path.read_bytes()
    second = update_fund_market_makers(
        path,
        snapshot_dir=snapshots,
        fetcher=_relations,
        observed_at=pd.Timestamp("2026-08-15T01:00:00Z"),
    )

    assert first.total == 2
    assert first.data["fund_code"].nunique() == 1
    assert set(first.data["service_type"]) == {"主", "一般"}
    assert "effective_date" not in first.data.columns
    assert second.status == "no_update" and not second.parquet_written
    assert path.read_bytes() == before
    assert len(list(snapshots.glob("*.parquet"))) == 1


def test_observed_at_cannot_be_disguised_as_effective_date() -> None:
    frame = _relations().assign(
        observed_at=pd.Timestamp("2026-08-15T00:00:00Z"),
        effective_date=pd.Timestamp("2026-08-15"),
    )
    with pytest.raises(ValueError, match="effective_date"):
        validate_fund_market_makers(frame)


def test_market_maker_crawler_paginates_and_uses_referer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeRelationSession()
    seen: list[str] = []

    def make_session(referer: str) -> FakeRelationSession:
        seen.append(referer)
        return session

    monkeypatch.setattr(fund_market_maker, "make_reference_session", make_session)
    result = fetch_fund_market_makers(page_size=1, request_interval=0)

    assert seen == [RELATION_REFERER]
    assert len(result) == 2
    assert [call["pageHelp.pageNo"] for call in session.calls] == [1, 2]
    assert set(result["service_type"]) == {"主", "一般"}


def test_market_maker_default_paths_are_absolute() -> None:
    assert DEFAULT_PARQUET_PATH == PROCESSED_DATA_DIR / "fund_market_makers.parquet"
    assert DEFAULT_SNAPSHOT_DIR == HISTORY_DATA_DIR / "fund_market_makers"
    assert DEFAULT_PARQUET_PATH.is_absolute() and DEFAULT_SNAPSHOT_DIR.is_absolute()
