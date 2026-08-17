from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config.paths import PROCESSED_DATA_DIR, STATE_DIR
from src.crawlers.fund_announcement import STANDARD_COLUMNS, build_announcement_key
from src.services.fund_announcement_service import (
    DEFAULT_PARQUET_PATH,
    DEFAULT_STATE_PATH,
    backfill_fund_announcements,
    merge_fund_announcements,
    update_fund_announcements,
    validate_fund_announcements,
)
from src.storage.parquet_store import read_parquet


def sample(
    suffix: str,
    *,
    route: str = "historical_search",
    source_id: str | None = None,
    date: str = "2026-08-15",
    fund_code: object = "510050",
) -> pd.DataFrame:
    url = (
        "https://www.sse.com.cn/disclosure/fund/announcement/c/new/"
        f"{date}/{suffix}.pdf"
    )
    return pd.DataFrame(
        {
            "announcement_date": pd.to_datetime([date]),
            "fund_code": pd.Series([fund_code], dtype="string"),
            "fund_name": pd.Series(["测试基金"], dtype="string"),
            "announcement_title": pd.Series([f"测试公告{suffix}"], dtype="string"),
            "announcement_type": pd.Series(["临时报告(基金)"], dtype="string"),
            "original_announcement_type": pd.Series([pd.NA], dtype="string"),
            "pdf_url": pd.Series([url], dtype="string"),
            "source": pd.Series(["sse"], dtype="string"),
            "source_announcement_id": pd.Series([source_id], dtype="string"),
            "source_route": pd.Series([route], dtype="string"),
            "announcement_key": pd.Series(
                [build_announcement_key(source_id, url)], dtype="string"
            ),
            "raw_record_json": pd.Series(
                [json.dumps({"suffix": suffix})], dtype="string"
            ),
        },
        columns=STANDARD_COLUMNS,
    )


def empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=STANDARD_COLUMNS)


def test_merge_deduplicates_cross_route_and_prefers_disclose_id() -> None:
    historical = sample("same")
    latest = sample("same", route="latest_json", source_id="DISCLOSE-1")

    result = merge_fund_announcements(historical, latest)

    assert len(result) == 1
    assert result.loc[0, "source_route"] == "latest_json"
    assert result.loc[0, "announcement_key"] == "sse:disclose_id:DISCLOSE-1"


def test_validation_keeps_missing_fund_code() -> None:
    result = validate_fund_announcements(sample("missing", fund_code=pd.NA))

    assert pd.isna(result.loc[0, "fund_code"])


def test_backfill_initializes_and_repeat_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "processed" / "announcements.parquet"
    state_path = tmp_path / "state" / "announcements.json"
    calls: list[tuple[str, str]] = []

    def fetcher(start: str, end: str) -> pd.DataFrame:
        calls.append((start, end))
        return sample("history", date=start)

    first = backfill_fund_announcements(
        "2026-08-14", "2026-08-15", path, state_path=state_path, fetcher=fetcher
    )
    original_bytes = path.read_bytes()
    second = backfill_fund_announcements(
        "2026-08-14", "2026-08-15", path, state_path=state_path, fetcher=fetcher
    )

    assert first.status == "initialized"
    assert first.new_records == 1
    assert second.status == "no_update"
    assert not second.parquet_written
    assert path.read_bytes() == original_bytes
    assert len(read_parquet(path)) == 1
    assert calls == [("2026-08-14", "2026-08-15")] * 2


def test_backfill_empty_result_does_not_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "announcements.parquet"
    state_path = tmp_path / "state.json"
    update_fund_announcements(
        path, state_path=state_path, fetcher=lambda: sample("existing")
    )
    original_bytes = path.read_bytes()

    result = backfill_fund_announcements(
        "2026-08-10",
        "2026-08-10",
        path,
        state_path=state_path,
        fetcher=lambda start, end: empty_frame(),
    )

    assert result.status == "no_update"
    assert not result.parquet_written
    assert result.empty_windows == (("2026-08-10", "2026-08-10"),)
    assert path.read_bytes() == original_bytes


def test_incremental_updated_then_no_update_without_rewrite(tmp_path: Path) -> None:
    path = tmp_path / "announcements.parquet"
    state_path = tmp_path / "state.json"
    first = update_fund_announcements(
        path, state_path=state_path, fetcher=lambda: sample("one", route="latest_json", source_id="ID1")
    )
    second = update_fund_announcements(
        path,
        state_path=state_path,
        fetcher=lambda: pd.concat(
            [
                sample("one", route="latest_json", source_id="ID1"),
                sample("two", route="latest_json", source_id="ID2"),
            ],
            ignore_index=True,
        ),
    )
    original_bytes = path.read_bytes()
    third = update_fund_announcements(
        path,
        state_path=state_path,
        fetcher=lambda: pd.concat(
            [
                sample("one", route="latest_json", source_id="ID1"),
                sample("two", route="latest_json", source_id="ID2"),
            ],
            ignore_index=True,
        ),
    )

    assert first.status == "initialized"
    assert second.status == "updated" and second.new_records == 1
    assert third.status == "no_update"
    assert not third.parquet_written
    assert path.read_bytes() == original_bytes
    assert not third.data.duplicated("announcement_key").any()


def test_state_and_default_paths_are_cwd_independent(
    tmp_path: Path, monkeypatch
) -> None:
    state_path = tmp_path / "state" / "announcement.json"
    update_fund_announcements(
        tmp_path / "data.parquet",
        state_path=state_path,
        fetcher=lambda: sample("state", route="latest_json", source_id="STATE1"),
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["status"] == "initialized"
    assert state["new_records"] == 1

    monkeypatch.chdir(PROJECT_ROOT.parents[1])
    assert DEFAULT_PARQUET_PATH == PROCESSED_DATA_DIR / "fund_announcements.parquet"
    assert DEFAULT_STATE_PATH == STATE_DIR / "fund_announcement_update_state.json"
    assert DEFAULT_PARQUET_PATH.is_absolute() and DEFAULT_STATE_PATH.is_absolute()
    monkeypatch.chdir(PROJECT_ROOT)
