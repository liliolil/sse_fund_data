from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config.paths import PROCESSED_DATA_DIR, STATE_DIR
from src.crawlers.fund_turnover import OUTPUT_COLUMNS
from src.services import fund_turnover_service
from src.services.fund_turnover_service import (
    DEFAULT_PATHS,
    DEFAULT_STATE_PATH,
    backfill_fund_turnover,
    generate_periods,
    update_fund_turnover,
    validate_fund_turnover,
)
from src.storage.parquet_store import read_parquet, save_parquet


def _sample(period: str, *, product_code: str = "05", frequency: str = "daily") -> pd.DataFrame:
    key = pd.Timestamp(period)
    row = {column: pd.NA for column in OUTPUT_COLUMNS}
    row.update(
        {
            "frequency": frequency,
            "period_key": key,
            "period_start": key,
            "period_end": key,
            "product_code": product_code,
            "list_count": 10,
            "trade_volume_100m_shares": 20.5,
            "trade_amount_100m_cny": 30.5,
            "market_value_100m_cny": 40.5,
            "negotiable_value_100m_cny": 39.5,
            "source_route": f"{frequency}_current",
            "support_status": "verified",
            "raw_record_json": "{}",
        }
    )
    return pd.DataFrame([row], columns=OUTPUT_COLUMNS)


def test_generate_periods_for_all_frequencies() -> None:
    assert [item.date().isoformat() for item in generate_periods("daily", "2026-08-01", "2026-08-03")] == [
        "2026-08-01",
        "2026-08-02",
        "2026-08-03",
    ]
    assert [item.date().isoformat() for item in generate_periods("weekly", "2026-08-01", "2026-08-13")] == [
        "2026-07-27",
        "2026-08-03",
        "2026-08-10",
    ]
    assert [item.strftime("%Y-%m") for item in generate_periods("monthly", "2026-01-15", "2026-03-31")] == [
        "2026-01",
        "2026-02",
        "2026-03",
    ]
    assert [item.strftime("%Y") for item in generate_periods("yearly", "2024-06-01", "2026-12-31")] == [
        "2024",
        "2025",
        "2026",
    ]


def test_validation_rejects_duplicate_primary_key() -> None:
    duplicate = pd.concat([_sample("2026-08-14"), _sample("2026-08-14")])
    with pytest.raises(ValueError, match="duplicate"):
        validate_fund_turnover(duplicate, "daily")


def test_backfill_skips_existing_adds_new_and_ignores_empty(tmp_path: Path) -> None:
    parquet_path = tmp_path / "processed" / "daily.parquet"
    state_path = tmp_path / "state" / "turnover.json"
    save_parquet(validate_fund_turnover(_sample("2026-08-11"), "daily"), parquet_path)
    calls: list[str] = []

    def fetcher(period: pd.Timestamp) -> pd.DataFrame:
        calls.append(period.date().isoformat())
        if period == pd.Timestamp("2026-08-12"):
            return pd.DataFrame(columns=OUTPUT_COLUMNS)
        return _sample(period.date().isoformat())

    result = backfill_fund_turnover(
        "daily",
        "2026-08-11",
        "2026-08-13",
        parquet_path,
        state_path=state_path,
        fetcher=fetcher,
        request_interval=0,
    )
    restored = read_parquet(parquet_path)

    assert result.status == "backfilled"
    assert calls == ["2026-08-12", "2026-08-13"]
    assert result.skipped_periods == ("2026-08-11",)
    assert result.empty_periods == ("2026-08-12",)
    assert result.added_periods == ("2026-08-13",)
    assert not restored.duplicated(["period_key", "product_code"]).any()
    assert restored["period_key"].tolist() == [
        pd.Timestamp("2026-08-11"),
        pd.Timestamp("2026-08-13"),
    ]
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["frequencies"]["daily"]["status"] == "backfilled"


def test_incremental_initializes_then_appends_new_period(tmp_path: Path) -> None:
    parquet_path = tmp_path / "processed" / "daily.parquet"
    state_path = tmp_path / "state" / "turnover.json"

    first = update_fund_turnover(
        "daily",
        parquet_path,
        state_path=state_path,
        fetcher=lambda: _sample("2026-08-13"),
    )
    second = update_fund_turnover(
        "daily",
        parquet_path,
        state_path=state_path,
        fetcher=lambda: _sample("2026-08-14"),
    )

    assert first.status == "initialized"
    assert second.status == "updated"
    assert len(read_parquet(parquet_path)) == 2
    assert second.latest_data_period == "2026-08-14"
    assert not second.data.duplicated(["period_key", "product_code"]).any()


def test_no_update_does_not_rewrite_parquet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parquet_path = tmp_path / "processed" / "daily.parquet"
    state_path = tmp_path / "state" / "turnover.json"
    save_parquet(validate_fund_turnover(_sample("2026-08-14"), "daily"), parquet_path)
    writes: list[Path] = []
    monkeypatch.setattr(
        fund_turnover_service,
        "save_parquet",
        lambda frame, path: writes.append(Path(path)),
    )

    result = update_fund_turnover(
        "daily",
        parquet_path,
        state_path=state_path,
        fetcher=lambda: _sample("2026-08-14"),
    )

    assert result.status == "no_update"
    assert not result.parquet_written
    assert writes == []
    assert state_path.is_file()


def test_empty_incremental_does_not_create_or_overwrite_parquet(tmp_path: Path) -> None:
    parquet_path = tmp_path / "processed" / "monthly.parquet"
    state_path = tmp_path / "state" / "turnover.json"

    result = update_fund_turnover(
        "monthly",
        parquet_path,
        state_path=state_path,
        fetcher=lambda: pd.DataFrame(columns=OUTPUT_COLUMNS),
        as_of_date="2026-08-15",
    )

    assert result.status == "no_update"
    assert not parquet_path.exists()
    assert result.data.empty


def test_default_paths_are_project_based_when_cwd_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outside_project = PROJECT_ROOT.parents[1]
    monkeypatch.chdir(outside_project)

    assert DEFAULT_PATHS["daily"] == PROCESSED_DATA_DIR / "fund_turnover_daily.parquet"
    assert DEFAULT_PATHS["weekly"].is_absolute()
    assert DEFAULT_STATE_PATH == STATE_DIR / "fund_turnover_update_state.json"
    assert DEFAULT_PATHS["daily"].is_relative_to(PROJECT_ROOT)
    monkeypatch.chdir(PROJECT_ROOT)
