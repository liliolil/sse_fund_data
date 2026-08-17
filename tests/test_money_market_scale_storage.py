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
from src.crawlers.money_market_scale import OUTPUT_COLUMNS
from src.services import scale_service_common
from src.services.money_market_scale_service import (
    DEFAULT_PARQUET_PATH,
    DEFAULT_STATE_PATH,
    backfill_money_market_scale,
    update_money_market_scale,
    validate_money_market_scale,
)
from src.storage.parquet_store import read_parquet, save_parquet


def _sample(data_date: str, code: str = "511600") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime([data_date]),
            "fund_code": pd.Series([code], dtype="string"),
            "fund_name": pd.Series(["测试货币ETF"], dtype="string"),
            "shares_10k": [82.82],
            "etf_type": pd.Series(["货币"], dtype="string"),
            "raw_record_json": pd.Series(["{}"], dtype="string"),
        },
        columns=OUTPUT_COLUMNS,
    )


def test_money_market_validation_rejects_duplicate_key() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        validate_money_market_scale(pd.concat([_sample("2026-08-13")] * 2))


def test_money_market_backfill_and_tmp_path_isolation(tmp_path: Path) -> None:
    path = tmp_path / "processed" / "money.parquet"
    state_path = tmp_path / "state" / "money.json"

    result = backfill_money_market_scale(
        "2026-08-13",
        "2026-08-14",
        path,
        state_path=state_path,
        fetcher=lambda value: _sample(value),
        request_interval=0,
    )
    restored = read_parquet(path)

    assert result.status == "backfilled"
    assert result.added_dates == ("2026-08-13", "2026-08-14")
    assert len(restored) == 2
    assert not restored.duplicated(["date", "fund_code"]).any()
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["latest_data_date"] == "2026-08-14"


def test_money_market_incremental_appends_new_date(tmp_path: Path) -> None:
    path = tmp_path / "processed" / "money.parquet"
    state_path = tmp_path / "state" / "money.json"
    update_money_market_scale(
        path, state_path=state_path, fetcher=lambda: _sample("2026-08-13")
    )

    result = update_money_market_scale(
        path, state_path=state_path, fetcher=lambda: _sample("2026-08-14")
    )

    assert result.status == "updated"
    assert result.new_records == 1
    assert result.remote_date == pd.Timestamp("2026-08-14")
    assert len(read_parquet(path)) == 2


def test_money_market_no_update_does_not_rewrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "processed" / "money.parquet"
    state_path = tmp_path / "state" / "money.json"
    save_parquet(validate_money_market_scale(_sample("2026-08-14")), path)
    writes: list[Path] = []
    monkeypatch.setattr(
        scale_service_common,
        "save_parquet",
        lambda frame, target: writes.append(Path(target)),
    )

    result = update_money_market_scale(
        path, state_path=state_path, fetcher=lambda: _sample("2026-08-14")
    )

    assert result.status == "no_update"
    assert not result.parquet_written
    assert writes == []


def test_money_market_default_paths_do_not_follow_cwd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(PROJECT_ROOT.parents[1])
    assert DEFAULT_PARQUET_PATH == PROCESSED_DATA_DIR / "money_market_scale.parquet"
    assert DEFAULT_STATE_PATH == STATE_DIR / "money_market_scale_update_state.json"
    assert DEFAULT_STATE_PATH.is_absolute()
    monkeypatch.chdir(PROJECT_ROOT)
