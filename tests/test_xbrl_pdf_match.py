from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.services import xbrl_pdf_match
from src.services.xbrl_pdf_match import (
    REPORT_TYPE_MAPPING,
    match_and_save_xbrl_pdf_links,
    match_candidates,
    normalize_title,
)
from src.storage.parquet_store import read_parquet


def _metadata(upload_id: int = 1) -> dict[str, object]:
    return {
        "uploadInfoId": upload_id,
        "fundCode": "510050",
        "reportTypeCode": "FB030020",
        "reportYear": "2026",
        "reportSendDate": "2026-07-21",
        "reportDesp": "第二季度报告",
    }


def _candidate(url_suffix: str = "A001", title: str | None = None) -> dict[str, object]:
    return {
        "announcementDate": "2026-07-21",
        "securityCode": "510050",
        "fundExpansionAbbr": "上证50ETF华夏",
        "announcementTitle": title or "上证50交易型开放式指数证券投资基金2026年第2季度报告",
        "bulletinType": "定期报告(基金)",
        "originalBulletinType": "季度报告",
        "pdfUrl": f"https://www.sse.com.cn/disclosure/fund/{url_suffix}.pdf",
    }


def test_report_type_mapping_is_centralized_and_complete() -> None:
    assert REPORT_TYPE_MAPPING["FB030010"].description == "第一季度报告"
    assert REPORT_TYPE_MAPPING["FB030020"].description == "第二季度报告"
    assert REPORT_TYPE_MAPPING["FB030030"].description == "第三季度报告"
    assert REPORT_TYPE_MAPPING["FB030040"].description == "第四季度报告"
    assert REPORT_TYPE_MAPPING["FB020010"].description == "中期报告"
    assert REPORT_TYPE_MAPPING["FB010010"].description == "年度报告"


def test_title_normalization_unifies_quarter_number_and_punctuation() -> None:
    assert normalize_title("2026年第二季度报告") == normalize_title(
        "2026 年第2季度报告！"
    )


def test_unique_candidate_matches() -> None:
    result = match_candidates(_metadata(), pd.DataFrame([_candidate()]))
    assert result["match_status"] == "matched"
    assert result["match_score"] == 100
    assert str(result["pdfUrl"]).endswith(".pdf")


def test_equal_top_candidates_are_ambiguous() -> None:
    candidates = pd.DataFrame([_candidate("A001"), _candidate("A002")])
    result = match_candidates(_metadata(), candidates)
    assert result["match_status"] == "ambiguous"
    assert pd.isna(result["pdfUrl"])


def test_no_candidates_is_not_found() -> None:
    result = match_candidates(_metadata(), pd.DataFrame())
    assert result["match_status"] == "not_found"
    assert result["match_score"] == 0


def test_save_uses_unique_upload_id_and_temporary_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "processed" / "xbrl_pdf_links.parquet"
    candidates = pd.DataFrame([_candidate()])
    monkeypatch.setattr(
        xbrl_pdf_match,
        "fetch_fund_announcements",
        lambda *args, **kwargs: candidates,
    )
    match_and_save_xbrl_pdf_links([_metadata(1)], output_path=output)
    match_and_save_xbrl_pdf_links([_metadata(1)], output_path=output)
    restored = read_parquet(output)

    assert len(restored) == 1
    assert restored["xbrl_upload_info_id"].is_unique
    assert restored.loc[0, "xbrl_upload_info_id"] == 1
    assert restored.loc[0, "source"] == "sse"
    assert restored.loc[0, "match_status"] == "matched"
    assert restored.loc[0, "pdf_url"].startswith("https://www.sse.com.cn/")
