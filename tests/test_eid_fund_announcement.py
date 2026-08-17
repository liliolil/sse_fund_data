from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.crawlers.eid_fund_announcement import (
    ANNOUNCEMENT_COLUMNS,
    build_eid_announcement_ao_data,
    build_normal_eid_pdf_url,
    fetch_eid_fund_announcements,
)
from src.services.xbrl_pdf_match import (
    LINK_COLUMNS,
    match_eid_pdf_candidates,
    save_xbrl_pdf_link_results,
)
from src.storage.parquet_store import read_parquet, save_parquet


def _raw_candidate(pdf_id: int, **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "uploadInfoId": pdf_id,
        "uploadInfoDetailId": pdf_id + 1000,
        "fundCode": "000001",
        "fundShortName": "华夏成长混合",
        "reportCode": "FB030020",
        "reportDesp": "第二季度报告",
        "reportYear": "2026",
        "uploadDate": "2026-07-20",
        "reportSendDate": "2026-07-21",
        "reportName": "华夏成长证券投资基金2026年第二季度报告",
        "tableName": "PDF",
        "correctionsNum": 0,
        "operationUploadType": "9090-1010",
        "attachFileName": None,
        "attachFilePath": None,
    }
    row.update(overrides)
    return row


def _candidate(pdf_id: int = 1534170, **overrides: object) -> dict[str, object]:
    raw = _raw_candidate(pdf_id, **overrides)
    raw["pdf_upload_info_id"] = raw.pop("uploadInfoId")
    for column in ANNOUNCEMENT_COLUMNS:
        raw.setdefault(column, pd.NA)
    return raw


def _metadata(xbrl_id: int = 23167397) -> dict[str, object]:
    return {
        "uploadInfoId": xbrl_id,
        "fundCode": "000001",
        "reportTypeCode": "FB030020",
        "reportYear": "2026",
        "reportSendDate": "2026-07-21",
        "reportDesp": "第二季度报告",
    }


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self.payload


class FakeSession:
    def __init__(self, pages: list[dict[str, object]]) -> None:
        self.pages = iter(pages)
        self.offsets: list[int] = []
        self.filters: list[dict[str, object]] = []

    def get(self, url: str, *, params: dict[str, str], timeout: object) -> FakeResponse:
        ao_data = json.loads(params["aoData"])
        values = {item["name"]: item["value"] for item in ao_data}
        self.offsets.append(values["iDisplayStart"])
        self.filters.append(values)
        return FakeResponse(next(self.pages))


def test_ao_data_uses_pdf_report_parameter_names_and_dates() -> None:
    values = {
        item["name"]: item["value"]
        for item in build_eid_announcement_ao_data(
            "FB030020",
            "2026",
            "000001",
            display_start=20,
            display_length=20,
            start_date="2026-07-20",
            end_date="2026-07-22",
        )
    }

    assert values["reportType"] == "FB030020"
    assert "reportTypeCode" not in values
    assert values["reportYear"] == "2026"
    assert values["fundCode"] == "000001"
    assert values["startUploadDate"] == "2026-07-20"
    assert values["endUploadDate"] == "2026-07-22"
    assert values["iDisplayStart"] == 20


def test_eid_pdf_pagination_and_fund_code_string() -> None:
    session = FakeSession(
        [
            {
                "iTotalDisplayRecords": 3,
                "aaData": [_raw_candidate(101), _raw_candidate(102)],
            },
            {
                "iTotalDisplayRecords": 3,
                "aaData": [_raw_candidate(102), _raw_candidate(103)],
            },
        ]
    )
    frame = fetch_eid_fund_announcements(
        "FB030020",
        "2026",
        "000001",
        page_size=2,
        request_interval=0,
        session=session,
    )

    assert session.offsets == [0, 2]
    assert frame["pdf_upload_info_id"].astype(int).tolist() == [101, 102, 103]
    assert list(frame.columns) == ANNOUNCEMENT_COLUMNS
    assert frame["fundCode"].tolist() == ["000001", "000001", "000001"]
    assert pd.api.types.is_string_dtype(frame["fundCode"].dtype)
    assert frame.attrs["pages_requested"] == 2
    assert frame.attrs["raw_rows_fetched"] == 4


def test_xbrl_id_and_pdf_id_are_distinct_and_unique_candidate_matches() -> None:
    result = match_eid_pdf_candidates(
        _metadata(23167397), pd.DataFrame([_candidate(1534170)])
    )

    assert result["xbrl_upload_info_id"] == 23167397
    assert result["pdf_upload_info_id"] == 1534170
    assert result["xbrl_upload_info_id"] != result["pdf_upload_info_id"]
    assert result["match_status"] == "matched"
    assert result["match_score"] == 100
    assert result["source"] == "eid_pdf"
    assert result["pdf_url"].endswith("instanceid=1534170")


def test_equal_candidates_are_ambiguous() -> None:
    candidates = pd.DataFrame([_candidate(1), _candidate(2)])
    result = match_eid_pdf_candidates(_metadata(), candidates)

    assert result["match_status"] == "ambiguous"
    assert result["candidate_count"] == 2
    assert pd.isna(result["pdf_upload_info_id"])
    assert pd.isna(result["pdf_url"])


def test_empty_candidates_are_not_found() -> None:
    result = match_eid_pdf_candidates(_metadata(), pd.DataFrame())

    assert result["match_status"] == "not_found"
    assert result["source"] == "eid_pdf"
    assert result["match_score"] == 0


def test_special_record_requires_special_handling_without_guessed_url() -> None:
    special = _candidate(1534170, correctionsNum=1)
    result = match_eid_pdf_candidates(_metadata(), pd.DataFrame([special]))

    assert build_normal_eid_pdf_url(special) is None
    assert result["match_status"] == "requires_special_handling"
    assert result["pdf_upload_info_id"] == 1534170
    assert pd.isna(result["pdf_url"])


def test_multisource_save_migrates_and_preserves_existing_sse_evidence(
    tmp_path: Path,
) -> None:
    output = tmp_path / "processed" / "xbrl_pdf_links.parquet"
    legacy_sse = pd.DataFrame(
        [
            {
                "uploadInfoId": 23167397,
                "fundCode": "000001",
                "reportTypeCode": "FB030020",
                "reportYear": "2026",
                "reportSendDate": "2026-07-21",
                "announcementDate": pd.NA,
                "announcementTitle": pd.NA,
                "pdfUrl": pd.NA,
                "match_score": 0,
                "match_status": "not_found",
                "candidate_count": 0,
                "queryStartDate": "2026-07-19",
                "queryEndDate": "2026-07-23",
            }
        ]
    )
    save_parquet(legacy_sse, output)
    eid_result = pd.DataFrame(
        [match_eid_pdf_candidates(_metadata(), pd.DataFrame([_candidate()]))],
        columns=LINK_COLUMNS,
    )
    save_xbrl_pdf_link_results(eid_result, output)
    restored = read_parquet(output)

    assert set(restored["source"]) == {"sse", "eid_pdf"}
    assert len(restored) == 2
    assert not restored.duplicated(["xbrl_upload_info_id", "source"]).any()
    assert restored.loc[restored["source"] == "sse", "match_status"].item() == "not_found"
    assert restored.loc[restored["source"] == "eid_pdf", "match_status"].item() == "matched"
