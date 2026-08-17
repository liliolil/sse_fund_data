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
from src.crawlers.lof_scale import OUTPUT_COLUMNS
from src.services import scale_service_common
from src.services.lof_scale_service import (
    DEFAULT_PARQUET_PATH,
    DEFAULT_STATE_PATH,
    backfill_lof_scale,
    update_lof_scale,
    validate_lof_scale,
)
from src.storage.parquet_store import read_parquet, save_parquet


def _sample(data_date: str, code: str = "501001") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime([data_date]),
            "fund_code": pd.Series([code], dtype="string"),
            "fund_name": pd.Series(["测试LOF"], dtype="string"),
            "shares_10k": [10.5],
            "product_type": pd.Series(["11"], dtype="string"),
            "raw_record_json": pd.Series(["{}"], dtype="string"),
        },
        columns=OUTPUT_COLUMNS,
    )


def test_lof_validation_rejects_duplicate_key() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        validate_lof_scale(pd.concat([_sample("2026-08-13")] * 2))


def test_lof_backfill_skips_existing_adds_new_and_keeps_weekend_empty(
    tmp_path: Path,
) -> None:
    path = tmp_path / "processed" / "lof.parquet"
    state_path = tmp_path / "state" / "lof.json"
    save_parquet(validate_lof_scale(_sample("2026-08-13")), path)
    calls: list[str] = []

    def fetcher(value: str) -> pd.DataFrame:
        calls.append(value)
        return _sample(value) if value == "2026-08-14" else pd.DataFrame(columns=OUTPUT_COLUMNS)

    result = backfill_lof_scale(
        "2026-08-13",
        "2026-08-15",
        path,
        state_path=state_path,
        fetcher=fetcher,
        request_interval=0,
    )
    restored = read_parquet(path)

    assert result.status == "backfilled"
    assert calls == ["2026-08-14", "2026-08-15"]
    assert result.skipped_dates == ("2026-08-13",)
    assert result.empty_dates == ("2026-08-15",)
    assert result.added_dates == ("2026-08-14",)
    assert restored["fund_code"].dtype == pd.StringDtype()
    assert not restored.duplicated(["date", "fund_code"]).any()
    assert json.loads(state_path.read_text(encoding="utf-8"))["status"] == "backfilled"


def test_lof_incremental_and_no_update_does_not_rewrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "processed" / "lof.parquet"
    state_path = tmp_path / "state" / "lof.json"
    first = update_lof_scale(
        path, state_path=state_path, fetcher=lambda: _sample("2026-08-13")
    )
    writes: list[Path] = []
    monkeypatch.setattr(
        scale_service_common,
        "save_parquet",
        lambda frame, target: writes.append(Path(target)),
    )
    second = update_lof_scale(
        path, state_path=state_path, fetcher=lambda: _sample("2026-08-13")
    )

    assert first.status == "initialized"
    assert second.status == "no_update"
    assert not second.parquet_written
    assert writes == []
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert "requested_start" not in state
    assert "requested_end" not in state


def test_lof_empty_incremental_preserves_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "processed" / "lof.parquet"
    state_path = tmp_path / "state" / "lof.json"
    save_parquet(validate_lof_scale(_sample("2026-08-13")), path)

    result = update_lof_scale(
        path,
        state_path=state_path,
        fetcher=lambda: pd.DataFrame(columns=OUTPUT_COLUMNS),
    )

    assert result.status == "no_update"
    assert len(read_parquet(path)) == 1


def test_lof_default_paths_do_not_follow_cwd(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(PROJECT_ROOT.parents[1])
    assert DEFAULT_PARQUET_PATH == PROCESSED_DATA_DIR / "lof_scale.parquet"
    assert DEFAULT_STATE_PATH == STATE_DIR / "lof_scale_update_state.json"
    assert DEFAULT_PARQUET_PATH.is_absolute()
    monkeypatch.chdir(PROJECT_ROOT)
