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
from src.crawlers.reits_scale import OUTPUT_COLUMNS
from src.services import scale_service_common
from src.services.reits_scale_service import (
    DEFAULT_PARQUET_PATH,
    DEFAULT_STATE_PATH,
    backfill_reits_scale,
    update_reits_scale,
    validate_reits_scale,
)
from src.storage.parquet_store import read_parquet, save_parquet


def _sample(data_date: str, code: str = "508000") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime([data_date]),
            "fund_code": pd.Series([code], dtype="string"),
            "fund_name": pd.Series([f"测试REIT{code}"], dtype="string"),
            "shares_10k": [90451.51],
            "raw_record_json": pd.Series(["{}"], dtype="string"),
        },
        columns=OUTPUT_COLUMNS,
    )


def _empty() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.Series(dtype="datetime64[ns]"),
            "fund_code": pd.Series(dtype="string"),
            "fund_name": pd.Series(dtype="string"),
            "shares_10k": pd.Series(dtype="Float64"),
            "raw_record_json": pd.Series(dtype="string"),
        }
    )


def test_reits_validation_rejects_duplicate_key() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        validate_reits_scale(pd.concat([_sample("2026-08-14")] * 2))


def test_reits_backfill_skips_known_date_and_handles_empty_date(tmp_path: Path) -> None:
    path = tmp_path / "processed" / "reits.parquet"
    state_path = tmp_path / "state" / "reits.json"
    save_parquet(validate_reits_scale(_sample("2026-08-13")), path)
    calls: list[str] = []

    def fetcher(value: str) -> pd.DataFrame:
        calls.append(value)
        if value == "2026-08-14":
            return _sample(value)
        return _empty()

    result = backfill_reits_scale(
        "2026-08-13",
        "2026-08-15",
        path,
        state_path=state_path,
        fetcher=fetcher,
        request_interval=0,
    )
    restored = read_parquet(path)

    assert calls == ["2026-08-14", "2026-08-15"]
    assert result.skipped_dates == ("2026-08-13",)
    assert result.empty_dates == ("2026-08-15",)
    assert result.added_dates == ("2026-08-14",)
    assert len(restored) == 2
    assert restored["fund_code"].dtype.name == "string"
    assert not restored.duplicated(["date", "fund_code"]).any()
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["history_boundary"] == "partially_verified"


def test_reits_incremental_initializes_then_updates(tmp_path: Path) -> None:
    path = tmp_path / "processed" / "reits.parquet"
    state_path = tmp_path / "state" / "reits.json"

    initialized = update_reits_scale(
        path, state_path=state_path, fetcher=lambda: _sample("2026-08-13")
    )
    updated = update_reits_scale(
        path, state_path=state_path, fetcher=lambda: _sample("2026-08-14")
    )

    assert initialized.status == "initialized"
    assert updated.status == "updated"
    assert updated.new_records == 1
    assert len(read_parquet(path)) == 2


def test_reits_no_update_does_not_rewrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "processed" / "reits.parquet"
    state_path = tmp_path / "state" / "reits.json"
    save_parquet(validate_reits_scale(_sample("2026-08-14")), path)
    writes: list[Path] = []
    monkeypatch.setattr(
        scale_service_common,
        "save_parquet",
        lambda frame, target: writes.append(Path(target)),
    )

    result = update_reits_scale(
        path, state_path=state_path, fetcher=lambda: _sample("2026-08-14")
    )

    assert result.status == "no_update"
    assert not result.parquet_written
    assert writes == []


def test_reits_empty_remote_preserves_existing_parquet(tmp_path: Path) -> None:
    path = tmp_path / "processed" / "reits.parquet"
    state_path = tmp_path / "state" / "reits.json"
    save_parquet(validate_reits_scale(_sample("2026-08-14")), path)
    original_bytes = path.read_bytes()

    result = update_reits_scale(path, state_path=state_path, fetcher=_empty)

    assert result.status == "no_update"
    assert path.read_bytes() == original_bytes


def test_reits_default_paths_do_not_follow_cwd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(PROJECT_ROOT.parents[1])
    assert DEFAULT_PARQUET_PATH == PROCESSED_DATA_DIR / "reits_scale.parquet"
    assert DEFAULT_STATE_PATH == STATE_DIR / "reits_scale_update_state.json"
    assert DEFAULT_PARQUET_PATH.is_absolute()
    assert DEFAULT_STATE_PATH.is_absolute()
    monkeypatch.chdir(PROJECT_ROOT)
