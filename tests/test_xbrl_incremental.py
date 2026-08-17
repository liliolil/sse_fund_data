from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.crawlers.xbrl import METADATA_COLUMNS, build_ao_data
from src.services import xbrl_service
from src.services.xbrl_service import validate_xbrl_metadata
from src.storage.parquet_store import read_parquet, save_parquet


def _metadata(*ids: int, fund_code: str = "510050") -> pd.DataFrame:
    rows = []
    for upload_id in ids:
        row = {
            "reportYear": "2026",
            "reportDesp": "第二季度报告",
            "uploadDate": "2026-08-13",
            "reportSendDate": "2026-08-14",
            "uploadInfoId": upload_id,
            "fundId": 7,
            "fundCode": fund_code,
            "fundShortName": "测试基金",
            "fundSign": "9010-1020",
            "organName": "测试机构",
            "reportTypeCode": "FB030020",
        }
        for column in METADATA_COLUMNS:
            row.setdefault(column, pd.NA)
        rows.append(row)
    frame = pd.DataFrame(rows, columns=METADATA_COLUMNS)
    frame.attrs["pages_requested"] = 1
    return frame


def _run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    local: pd.DataFrame,
    recent: pd.DataFrame,
    remote_total: int,
):
    metadata_path = tmp_path / "processed" / "xbrl_metadata.parquet"
    state_path = tmp_path / "state" / "xbrl_update_state.json"
    if not local.empty:
        save_parquet(validate_xbrl_metadata(local), metadata_path)
    captured: dict[str, object] = {}

    def fake_fetch(*args, **kwargs):
        captured.update(kwargs)
        return recent

    monkeypatch.setattr(xbrl_service, "fetch_xbrl_metadata", fake_fetch)
    monkeypatch.setattr(
        xbrl_service, "fetch_xbrl_remote_total", lambda *args, **kwargs: remote_total
    )
    result = xbrl_service.update_xbrl_metadata(
        "FB030020",
        "2026",
        lookback_days=7,
        metadata_path=metadata_path,
        state_path=state_path,
        as_of_date="2026-08-14",
        request_interval=0,
    )
    return result, metadata_path, state_path, captured


def test_ao_data_maps_report_send_date_to_verified_parameter_names() -> None:
    values = {
        item["name"]: item["value"]
        for item in build_ao_data(
            "FB030020",
            "2026",
            None,
            display_start=0,
            display_length=20,
            report_send_date_start="2026-08-08",
            report_send_date_end="2026-08-14",
        )
    }
    assert values["startUploadDate"] == "2026-08-08"
    assert values["endUploadDate"] == "2026-08-14"


def test_existing_ids_are_not_appended_and_partition_is_up_to_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, metadata_path, state_path, captured = _run(
        tmp_path, monkeypatch, _metadata(1, 2), _metadata(2), 2
    )

    assert result.status == "up_to_date"
    assert result.new_records == 0
    assert not result.parquet_written
    assert len(read_parquet(metadata_path)) == 2
    assert captured["report_send_date_start"] == "2026-08-08"
    assert captured["report_send_date_end"] == "2026-08-14"
    assert state_path.is_file()


def test_new_id_is_appended_while_same_fund_code_is_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, metadata_path, state_path, _ = _run(
        tmp_path, monkeypatch, _metadata(1), _metadata(1, 2), 2
    )
    restored = read_parquet(metadata_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))

    assert result.status == "updated"
    assert result.new_records == 1
    assert result.parquet_written
    assert restored["uploadInfoId"].astype(int).tolist() == [1, 2]
    assert restored["fundCode"].tolist() == ["510050", "510050"]
    assert state["status"] == "updated"
    assert state["local_total"] == 2
    assert state["new_records"] == 1
    assert state["lookback_start"] == "2026-08-08"
    assert state["lookback_end"] == "2026-08-14"


def test_remote_total_difference_needs_reconciliation_and_writes_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty_recent = pd.DataFrame(columns=METADATA_COLUMNS)
    empty_recent.attrs["pages_requested"] = 1
    result, _, state_path, _ = _run(
        tmp_path, monkeypatch, _metadata(1), empty_recent, 2
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))

    assert result.status == "needs_reconciliation"
    assert result.local_total == 1
    assert result.remote_total == 2
    assert result.new_records == 0
    assert state["status"] == "needs_reconciliation"
