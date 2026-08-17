from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.crawlers.xbrl import (
    HtmlDownloadResult,
    METADATA_COLUMNS,
    build_ao_data,
    download_xbrl_html,
    fetch_xbrl_metadata,
)
from src.services import xbrl_service
from src.storage.parquet_store import read_parquet


def _row(upload_id: int) -> dict[str, object]:
    return {
        "reportYear": "2026",
        "reportDesp": "第二季度报告",
        "uploadDate": "2026-07-20",
        "reportSendDate": "2026-07-21",
        "uploadInfoId": upload_id,
        "fundId": 7,
        "fundCode": "510050",
        "fundShortName": "华夏上证50ETF",
        "fundSign": "9010-1020",
        "organName": "华夏",
    }


class MetadataResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self.payload


class MetadataSession:
    def __init__(self, pages: list[dict[str, object]]) -> None:
        self.pages = iter(pages)
        self.offsets: list[int] = []

    def get(self, url: str, *, params: dict[str, str], timeout: object) -> MetadataResponse:
        import json

        ao_data = json.loads(params["aoData"])
        values = {item["name"]: item["value"] for item in ao_data}
        self.offsets.append(values["iDisplayStart"])
        return MetadataResponse(next(self.pages))


def test_ao_data_contains_filters_and_paging() -> None:
    values = {
        item["name"]: item["value"]
        for item in build_ao_data(
            "FB030020", "2026", "510050", display_start=20, display_length=20
        )
    }
    assert values["reportTypeCode"] == "FB030020"
    assert values["reportYear"] == "2026"
    assert values["fundCode"] == "510050"
    assert values["iDisplayStart"] == 20
    assert values["iDisplayLength"] == 20


def test_pagination_deduplicates_upload_id_and_has_fields() -> None:
    session = MetadataSession(
        [
            {"iTotalDisplayRecords": 3, "aaData": [_row(1), _row(2)]},
            {"iTotalDisplayRecords": 3, "aaData": [_row(2), _row(3)]},
        ]
    )
    frame = fetch_xbrl_metadata(
        "FB030020",
        2026,
        "510050",
        page_size=2,
        request_interval=0,
        session=session,
    )

    assert session.offsets == [0, 2]
    assert frame["uploadInfoId"].tolist() == [1, 2, 3]
    assert list(frame.columns) == METADATA_COLUMNS
    assert pd.api.types.is_string_dtype(frame["fundCode"].dtype)
    assert frame.attrs["api_total_display_records"] == 3
    assert frame.attrs["raw_rows_fetched"] == 4


class HtmlSession:
    def __init__(self) -> None:
        self.calls = 0

    def get(self, url: str, *, timeout: object, allow_redirects: bool) -> object:
        self.calls += 1
        return SimpleNamespace(
            status_code=200,
            content=b"<!doctype html><html><body>report</body></html>",
            url="http://eid.csrc.gov.cn/xbrl/REPORT/HTML/report.html",
        )


def test_html_uses_upload_id_filename_and_skips_valid_existing(tmp_path: Path) -> None:
    session = HtmlSession()
    first = download_xbrl_html(23167526, tmp_path, session=session)
    second = download_xbrl_html(23167526, tmp_path, session=session)

    assert first.file_path == tmp_path / "23167526.html"
    assert first.http_status == 200
    assert first.final_url == "http://eid.csrc.gov.cn/xbrl/REPORT/HTML/report.html"
    assert not first.skipped
    assert second.skipped
    assert session.calls == 1


def test_service_saves_metadata_parquet_in_temporary_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    metadata_path = tmp_path / "processed" / "xbrl_metadata.parquet"
    html_dir = tmp_path / "raw" / "html"
    metadata = pd.DataFrame([_row(23167526)])
    metadata["reportTypeCode"] = "FB030020"
    for column in METADATA_COLUMNS:
        if column not in metadata:
            metadata[column] = pd.NA

    def fake_download(upload_id: int, output_dir: str | Path) -> HtmlDownloadResult:
        html_path = Path(output_dir) / f"{upload_id}.html"
        html_path.parent.mkdir(parents=True, exist_ok=True)
        content = b"<!doctype html><html><body>report</body></html>"
        html_path.write_bytes(content)
        return HtmlDownloadResult(
            request_url=f"http://example.test/view?instanceid={upload_id}",
            final_url="http://example.test/final.html",
            http_status=200,
            file_path=html_path,
            size=len(content),
            skipped=False,
        )

    monkeypatch.setattr(xbrl_service, "fetch_xbrl_metadata", lambda *args, **kwargs: metadata)
    monkeypatch.setattr(xbrl_service, "download_xbrl_html", fake_download)
    result = xbrl_service.collect_xbrl(
        "FB030020",
        2026,
        "510050",
        metadata_path=metadata_path,
        html_dir=html_dir,
        request_interval=0,
    )
    restored = read_parquet(metadata_path)

    assert result["uploadInfoId"].tolist() == [23167526]
    assert restored["uploadInfoId"].is_unique
    assert pd.api.types.is_string_dtype(restored["fundCode"].dtype)
    assert restored.loc[0, "htmlHttpStatus"] == 200
    assert Path(restored.loc[0, "htmlPath"]).name == "23167526.html"


def test_metadata_only_collection_saves_all_rows_without_html_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    metadata_path = tmp_path / "xbrl_metadata.parquet"
    metadata = pd.DataFrame([_row(1), _row(2)])
    metadata["reportTypeCode"] = "FB030020"
    for column in METADATA_COLUMNS:
        if column not in metadata:
            metadata[column] = pd.NA
    metadata.attrs.update(
        api_total_records=2,
        api_total_display_records=2,
        raw_rows_fetched=2,
    )
    monkeypatch.setattr(xbrl_service, "fetch_xbrl_metadata", lambda *args, **kwargs: metadata)
    monkeypatch.setattr(
        xbrl_service,
        "download_xbrl_html",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not download")),
    )

    result = xbrl_service.collect_xbrl_metadata_only(
        "FB030020",
        2026,
        None,
        metadata_path=metadata_path,
        expected_report_desp="第二季度报告",
    )
    restored = read_parquet(metadata_path)

    assert len(result) == 2
    assert len(restored) == 2
    assert restored["uploadInfoId"].is_unique
    assert restored["htmlPath"].isna().all()


def test_metadata_only_rejects_incomplete_pagination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    metadata = pd.DataFrame([_row(1)])
    metadata["reportTypeCode"] = "FB030020"
    for column in METADATA_COLUMNS:
        if column not in metadata:
            metadata[column] = pd.NA
    metadata.attrs.update(
        api_total_records=2,
        api_total_display_records=2,
        raw_rows_fetched=1,
    )
    monkeypatch.setattr(xbrl_service, "fetch_xbrl_metadata", lambda *args, **kwargs: metadata)

    with pytest.raises(ValueError, match="Incomplete EID pagination"):
        xbrl_service.collect_xbrl_metadata_only(
            "FB030020", 2026, metadata_path=tmp_path / "metadata.parquet"
        )
