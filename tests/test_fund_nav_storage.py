from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pandas as pd
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.cli import MODULES, WATCH_INTERVAL_MULTIPLIERS, main
from src.config.paths import PROCESSED_DATA_DIR, STATE_DIR
from src.crawlers.fund_nav import OUTPUT_COLUMNS
from src.services import fund_nav_service
from src.services.fund_nav_service import (
    DEFAULT_PARQUET_PATH,
    DEFAULT_STATE_PATH,
    backfill_fund_nav_cli,
    backfill_lof_nav,
    backfill_reits_nav,
    update_fund_nav,
    validate_fund_nav,
)
from src.storage.parquet_store import read_parquet, save_parquet


def _sample(route: str, data_date: str, code: str) -> pd.DataFrame:
    nav_type = "daily_nav" if route == "lof" else "appraisal_nav"
    return pd.DataFrame(
        {
            "market": pd.Series(["SSE"], dtype="string"),
            "fund_code": pd.Series([code], dtype="string"),
            "fund_name": pd.Series([f"测试{route}"], dtype="string"),
            "fund_full_name": pd.Series([f"测试{route}全称"], dtype="string"),
            "nav_date": pd.to_datetime([data_date]),
            "nav": pd.Series([1.2345], dtype="Float64"),
            "nav_type": pd.Series([nav_type], dtype="string"),
            "product_type": pd.Series(
                ["11" if route == "lof" else pd.NA], dtype="string"
            ),
            "source": pd.Series(["sse"], dtype="string"),
            "source_route": pd.Series([route], dtype="string"),
            "observed_at": pd.to_datetime(["2026-08-17T00:00:00Z"], utc=True),
            "raw_record_json": pd.Series(["{}"], dtype="string"),
        },
        columns=OUTPUT_COLUMNS,
    )


def _empty() -> pd.DataFrame:
    return fund_nav_service._empty_frame()


def test_incremental_initializes_both_sources_and_state_is_separate(tmp_path: Path) -> None:
    path = tmp_path / "processed" / "fund_nav.parquet"
    state_path = tmp_path / "state" / "fund_nav.json"
    result = update_fund_nav(
        path,
        state_path=state_path,
        fetchers={
            "lof": lambda: _sample("lof", "2026-08-13", "501018"),
            "reits": lambda: _sample("reits", "2025-12-31", "508000"),
        },
    )
    restored = read_parquet(path)
    state = json.loads(state_path.read_text(encoding="utf-8"))

    assert result.status == "initialized" and result.new_records == 2
    assert len(restored) == 2
    assert restored["fund_code"].dtype.name == "string"
    assert state["lof"]["latest_local_date"] == "2026-08-13"
    assert state["reits"]["latest_local_date"] == "2025-12-31"
    assert state["lof"]["status"] == "initialized"
    assert state["reits"]["status"] == "initialized"


def test_incremental_adds_new_source_date_and_keeps_same_code_different_nav_type(
    tmp_path: Path,
) -> None:
    path = tmp_path / "fund_nav.parquet"
    state_path = tmp_path / "fund_nav.json"
    existing = pd.concat(
        [
            _sample("lof", "2025-12-31", "501018"),
            _sample("reits", "2025-12-31", "501018"),
        ],
        ignore_index=True,
    )
    save_parquet(validate_fund_nav(existing), path)

    result = update_fund_nav(
        path,
        state_path=state_path,
        fetchers={
            "lof": lambda: _sample("lof", "2026-08-13", "501018"),
            "reits": lambda: _sample("reits", "2025-12-31", "501018"),
        },
    )

    assert result.status == "updated" and result.new_records == 1
    assert len(read_parquet(path)) == 3
    assert not result.data.duplicated(
        ["market", "fund_code", "nav_date", "nav_type"]
    ).any()


def test_no_update_and_empty_remote_do_not_rewrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "fund_nav.parquet"
    state_path = tmp_path / "fund_nav.json"
    local = validate_fund_nav(_sample("lof", "2026-08-13", "501018"))
    save_parquet(local, path)
    writes: list[Path] = []
    monkeypatch.setattr(
        fund_nav_service,
        "save_parquet",
        lambda frame, target: writes.append(Path(target)),
    )

    result = update_fund_nav(
        path,
        state_path=state_path,
        fetchers={"lof": lambda: local, "reits": _empty},
    )

    assert result.status == "no_update" and not result.parquet_written
    assert writes == []


def test_lof_backfill_skips_existing_and_preserves_empty_date(tmp_path: Path) -> None:
    path = tmp_path / "fund_nav.parquet"
    state_path = tmp_path / "fund_nav.json"
    save_parquet(validate_fund_nav(_sample("lof", "2026-08-13", "501018")), path)
    calls: list[str] = []

    def fetcher(value: str) -> pd.DataFrame:
        calls.append(value)
        return _empty()

    result = backfill_lof_nav(
        "2026-08-13",
        "2026-08-14",
        path,
        state_path=state_path,
        fetcher=fetcher,
        request_interval=0,
    )

    assert calls == ["2026-08-14"]
    assert result.skipped_dates == ("2026-08-13",)
    assert result.empty_dates == ("2026-08-14",)
    assert result.status == "no_update"


def test_reits_backfill_only_queries_explicit_known_dates(tmp_path: Path) -> None:
    path = tmp_path / "fund_nav.parquet"
    state_path = tmp_path / "fund_nav.json"
    calls: list[str] = []

    def fetcher(value: str) -> pd.DataFrame:
        calls.append(value)
        return _sample("reits", value, "508000")

    result = backfill_reits_nav(
        ["2024-06-30", "2024-12-31", "2025-12-31"],
        path,
        state_path=state_path,
        fetcher=fetcher,
        request_interval=0,
    )

    assert calls == ["2024-06-30", "2024-12-31", "2025-12-31"]
    assert result.added_dates == tuple(calls)
    assert len(read_parquet(path)) == 3
    with pytest.raises(ValueError, match="one explicit appraisal date"):
        backfill_fund_nav_cli("reits", "2024-01-01", "2025-12-31")


def test_cli_dispatch_watch_registration_and_default_paths_are_cwd_independent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(PROJECT_ROOT.parents[1])
    assert "fund-nav" in MODULES
    assert WATCH_INTERVAL_MULTIPLIERS["fund-nav"] == 144
    assert DEFAULT_PARQUET_PATH == PROCESSED_DATA_DIR / "fund_nav.parquet"
    assert DEFAULT_STATE_PATH == STATE_DIR / "fund_nav_update_state.json"
    assert DEFAULT_PARQUET_PATH.is_absolute() and DEFAULT_STATE_PATH.is_absolute()
    monkeypatch.chdir(PROJECT_ROOT)


def test_cli_source_backfill_dispatch(tmp_path: Path) -> None:
    calls: list[tuple[str, str, str]] = []
    spec = MODULES["fund-nav"]
    isolated = type(spec)(
        name="fund-nav",
        label="Fund NAV",
        update=lambda: None,
        parquet_paths=(tmp_path / "fund_nav.parquet",),
        latest_columns=("nav_date",),
        state_path=tmp_path / "fund_nav.json",
        source_backfill=lambda source, start, end: (
            calls.append((source, start, end))
            or type("Result", (), {"status": "backfilled"})()
        ),
    )
    output = io.StringIO()

    code = main(
        [
            "backfill",
            "fund-nav",
            "--source",
            "lof",
            "--start",
            "2026-08-13",
            "--end",
            "2026-08-14",
        ],
        registry={"fund-nav": isolated},
        output=output,
    )

    assert code == 0
    assert calls == [("lof", "2026-08-13", "2026-08-14")]
