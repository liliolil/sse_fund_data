from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.cli import (
    MODULES,
    WATCH_INTERVAL_MULTIPLIERS,
    WATCH_MIN_INTERVALS,
    ModuleSpec,
    _watch_intervals,
    main,
)
from src.config.paths import PROCESSED_DATA_DIR, STATE_DIR
from src.crawlers.fund_market_data import NUMERIC_COLUMNS, OUTPUT_COLUMNS
from src.services.fund_market_data_service import (
    DEFAULT_PARQUET_PATH,
    DEFAULT_STATE_PATH,
    PRIMARY_KEY,
    update_fund_market_data,
)
from src.storage.parquet_store import read_parquet


def _sample(route: str, code: str, snapshot: str) -> pd.DataFrame:
    route_type = {"etf": "ETF", "lof": "LOF", "reits": "REIT"}[route]
    data: dict[str, object] = {
        "market": pd.Series(["SSE"], dtype="string"),
        "fund_type": pd.Series([route_type], dtype="string"),
        "fund_code": pd.Series([code], dtype="string"),
        "fund_name": pd.Series([f"测试{route}"], dtype="string"),
        "snapshot_time": pd.to_datetime([snapshot], utc=True),
        "trade_date": pd.to_datetime(["2026-08-17"]),
        "trade_phase": pd.Series(["T111" if route == "etf" else pd.NA], dtype="string"),
        "source": pd.Series(["sse_yunhq"], dtype="string"),
        "source_route": pd.Series([route], dtype="string"),
        "observed_at": pd.to_datetime(["2026-08-17T01:30:02Z"], utc=True),
        "raw_record_json": pd.Series(["{}"], dtype="string"),
    }
    for column in NUMERIC_COLUMNS:
        data[column] = pd.Series([1.0], dtype="Float64")
    frame = pd.DataFrame(data)[OUTPUT_COLUMNS]
    frame.attrs["snapshot_time_source"] = "exchange_server"
    return frame


def test_one_round_has_unified_snapshot_and_writes_state(tmp_path: Path) -> None:
    path = tmp_path / "processed" / "market.parquet"
    state_path = tmp_path / "state" / "market.json"
    result = update_fund_market_data(
        path,
        state_path=state_path,
        fetchers={
            "etf": lambda: _sample("etf", "510050", "2026-08-17T01:30:00Z"),
            "lof": lambda: _sample("lof", "501018", "2026-08-17T01:30:01Z"),
            "reits": lambda: _sample("reits", "508000", "2026-08-17T01:30:02Z"),
        },
    )
    restored = read_parquet(path)
    state = json.loads(state_path.read_text(encoding="utf-8"))

    assert result.status == "recorded" and result.new_records == 3
    assert restored["snapshot_time"].nunique() == 1
    assert not restored.duplicated(PRIMARY_KEY).any()
    assert state["overall_status"] == "recorded"
    assert state["sources"]["etf"]["rows"] == 1
    assert state["sources"]["lof"]["rows"] == 1
    assert state["sources"]["reits"]["rows"] == 1
    assert state["history_capability"] == "snapshot_from_now"


def test_single_source_failure_still_saves_partial_success(tmp_path: Path) -> None:
    path = tmp_path / "market.parquet"
    state_path = tmp_path / "market.json"

    def fail():
        raise RuntimeError("temporary error")

    result = update_fund_market_data(
        path,
        state_path=state_path,
        fetchers={
            "etf": lambda: _sample("etf", "510050", "2026-08-17T01:30:00Z"),
            "lof": fail,
            "reits": lambda: _sample("reits", "508000", "2026-08-17T01:30:02Z"),
        },
    )

    assert result.status == "partial_success"
    assert result.parquet_written and result.new_records == 2
    assert result.source_statuses["lof"] == "failed"
    assert len(result.errors) == 1
    assert len(read_parquet(path)) == 2


def test_consecutive_same_server_second_creates_distinct_snapshots(tmp_path: Path) -> None:
    path = tmp_path / "market.parquet"
    state_path = tmp_path / "market.json"
    fetchers = {
        "etf": lambda: _sample("etf", "510050", "2026-08-17T01:30:00Z"),
        "lof": lambda: _sample("lof", "501018", "2026-08-17T01:30:00Z"),
        "reits": lambda: _sample("reits", "508000", "2026-08-17T01:30:00Z"),
    }
    update_fund_market_data(path, state_path=state_path, fetchers=fetchers)
    second = update_fund_market_data(path, state_path=state_path, fetchers=fetchers)

    restored = read_parquet(path)
    assert second.status == "recorded"
    assert len(restored) == 6
    assert restored["snapshot_time"].nunique() == 2
    assert not restored.duplicated(PRIMARY_KEY).any()


def test_cli_dispatch_backfill_unsupported_and_no_dataframe_output(tmp_path: Path) -> None:
    calls: list[str] = []
    path = tmp_path / "market.parquet"
    _sample("etf", "510050", "2026-08-17T01:30:00Z").to_parquet(path, index=False)
    spec = ModuleSpec(
        "fund-market-data",
        "Fund market data",
        lambda: calls.append("update")
        or SimpleNamespace(status="recorded", data=pd.DataFrame({"x": range(1000)})),
        (path,),
        ("snapshot_time",),
    )
    output = io.StringIO()
    assert main(
        ["update", "fund-market-data"],
        registry={"fund-market-data": spec},
        output=output,
    ) == 0
    assert calls == ["update"]
    assert "DataFrame" not in output.getvalue() and "1000 rows" not in output.getvalue()

    output = io.StringIO()
    assert main(
        [
            "backfill",
            "fund-market-data",
            "--start",
            "2026-08-01",
            "--end",
            "2026-08-02",
        ],
        registry={"fund-market-data": spec},
        output=output,
    ) == 2
    assert "backfill not supported" in output.getvalue()


def test_watch_floor_registration_and_default_paths_are_cwd_independent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(PROJECT_ROOT.parents[1])
    assert "fund-market-data" in MODULES
    assert WATCH_INTERVAL_MULTIPLIERS["fund-market-data"] == 3
    assert WATCH_MIN_INTERVALS["fund-market-data"] == 300
    assert _watch_intervals(["fund-market-data"], 60) == {"fund-market-data": 300}
    assert _watch_intervals(["fund-market-data"], 600) == {"fund-market-data": 1800}
    assert DEFAULT_PARQUET_PATH == PROCESSED_DATA_DIR / "fund_market_data.parquet"
    assert DEFAULT_STATE_PATH == STATE_DIR / "fund_market_data_update_state.json"
    assert DEFAULT_PARQUET_PATH.is_absolute() and DEFAULT_STATE_PATH.is_absolute()
    monkeypatch.chdir(PROJECT_ROOT)
