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
from src.crawlers.money_fund_redemption_params import NUMERIC_COLUMNS, OUTPUT_COLUMNS
from src.services import money_fund_redemption_params_service as service
from src.services.money_fund_redemption_params_service import (
    DEFAULT_PARQUET_PATH,
    DEFAULT_STATE_PATH,
    PRIMARY_KEY,
    update_money_fund_redemption_params,
)
from src.storage.parquet_store import read_parquet


def _sample(
    *, code: str = "519800", trade_date: str = "2026-08-14", buy_limit: float = 20_000_000
) -> pd.DataFrame:
    data: dict[str, object] = {
        "market": pd.Series(["SSE"], dtype="string"),
        "fund_code": pd.Series([code], dtype="string"),
        "fund_name": pd.Series(["保证金A"], dtype="string"),
        "company_name": pd.Series(["测试基金"], dtype="string"),
        "file_date": pd.to_datetime([trade_date]),
        "trade_date": pd.to_datetime([trade_date]),
        "others": pd.Series(["20,000.00"], dtype="string"),
        "source_num": pd.Series(["1"], dtype="string"),
        "source": pd.Series(["sse"], dtype="string"),
        "source_route": pd.Series(
            ["money_fund_redemption_params"], dtype="string"
        ),
        "observed_at": pd.to_datetime(["2026-08-17T01:00:00Z"], utc=True),
        "raw_record_json": pd.Series(
            [json.dumps({"BUY_LIMIT": str(buy_limit)}, sort_keys=True)], dtype="string"
        ),
    }
    for column in NUMERIC_COLUMNS:
        data[column] = pd.Series(
            [buy_limit if column == "buy_limit" else 1.0], dtype="Float64"
        )
    return pd.DataFrame(data)[OUTPUT_COLUMNS]


def _empty() -> pd.DataFrame:
    return service._empty_frame()


def test_initial_write_and_state(tmp_path: Path) -> None:
    path = tmp_path / "processed" / "params.parquet"
    state_path = tmp_path / "state" / "params.json"
    result = update_money_fund_redemption_params(
        path, state_path=state_path, fetcher=_sample
    )
    restored = read_parquet(path)
    state = json.loads(state_path.read_text(encoding="utf-8"))

    assert result.status == "initialized" and result.new_records == 1
    assert len(restored) == 1 and not restored.duplicated(PRIMARY_KEY).any()
    assert state["latest_remote_trade_date"] == "2026-08-14"
    assert state["latest_local_trade_date"] == "2026-08-14"
    assert state["rows_remote"] == 1 and state["rows_local"] == 1
    assert state["history_capability"] == "snapshot_from_now"
    assert state["file_trade_date_mismatch_count"] == 0


def test_identical_snapshot_is_no_update_without_parquet_rewrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "params.parquet"
    state_path = tmp_path / "params.json"
    update_money_fund_redemption_params(path, state_path=state_path, fetcher=_sample)
    writes: list[Path] = []
    monkeypatch.setattr(
        service, "save_parquet", lambda frame, target: writes.append(Path(target))
    )

    result = update_money_fund_redemption_params(
        path, state_path=state_path, fetcher=_sample
    )

    assert result.status == "no_update" and not result.parquet_written
    assert writes == []


def test_same_day_revision_replaces_record_and_is_recorded(tmp_path: Path) -> None:
    path = tmp_path / "params.parquet"
    state_path = tmp_path / "params.json"
    update_money_fund_redemption_params(path, state_path=state_path, fetcher=_sample)

    result = update_money_fund_redemption_params(
        path,
        state_path=state_path,
        fetcher=lambda: _sample(buy_limit=30_000_000),
    )
    restored = read_parquet(path)
    state = json.loads(state_path.read_text(encoding="utf-8"))

    assert result.status == "revised"
    assert result.revision_detected and result.revision_count == 1
    assert len(restored) == 1 and restored.loc[0, "buy_limit"] == 30_000_000
    assert state["revision_detected"] is True
    assert state["revision_count"] == 1 and state["revision_count_total"] == 1


def test_empty_remote_preserves_existing_parquet(tmp_path: Path) -> None:
    path = tmp_path / "params.parquet"
    state_path = tmp_path / "params.json"
    update_money_fund_redemption_params(path, state_path=state_path, fetcher=_sample)
    original = path.read_bytes()

    result = update_money_fund_redemption_params(
        path, state_path=state_path, fetcher=_empty
    )

    assert result.status == "no_update" and not result.parquet_written
    assert path.read_bytes() == original


def test_cli_dispatch_backfill_unsupported_and_no_dataframe(tmp_path: Path) -> None:
    calls: list[str] = []
    path = tmp_path / "params.parquet"
    _sample().to_parquet(path, index=False)
    spec = ModuleSpec(
        "money-fund-redemption-params",
        "Money redemption params",
        lambda: calls.append("update")
        or SimpleNamespace(status="no_update", data=pd.DataFrame({"x": range(1000)})),
        (path,),
        ("trade_date",),
    )
    output = io.StringIO()
    assert main(
        ["update", "money-fund-redemption-params"],
        registry={"money-fund-redemption-params": spec},
        output=output,
    ) == 0
    assert calls == ["update"] and "DataFrame" not in output.getvalue()

    output = io.StringIO()
    assert main(
        [
            "backfill",
            "money-fund-redemption-params",
            "--start",
            "2026-08-01",
            "--end",
            "2026-08-02",
        ],
        registry={"money-fund-redemption-params": spec},
        output=output,
    ) == 2
    assert "backfill not supported" in output.getvalue()


def test_watch_floor_registration_and_cwd_independent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(PROJECT_ROOT.parents[1])
    name = "money-fund-redemption-params"
    assert name in MODULES
    assert WATCH_INTERVAL_MULTIPLIERS[name] == 36
    assert WATCH_MIN_INTERVALS[name] == 3600
    assert _watch_intervals([name], 60) == {name: 3600}
    assert _watch_intervals([name], 600) == {name: 21600}
    assert DEFAULT_PARQUET_PATH == (
        PROCESSED_DATA_DIR / "money_fund_redemption_params.parquet"
    )
    assert DEFAULT_STATE_PATH == (
        STATE_DIR / "money_fund_redemption_params_update_state.json"
    )
    assert DEFAULT_PARQUET_PATH.is_absolute() and DEFAULT_STATE_PATH.is_absolute()
    monkeypatch.chdir(PROJECT_ROOT)
