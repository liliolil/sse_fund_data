from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


PROJECT_ROOT_FOR_IMPORT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT_FOR_IMPORT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT_FOR_IMPORT))

from src.config.paths import (
    DATA_DIR,
    DOCS_DIR,
    PROCESSED_DATA_DIR,
    PROJECT_ROOT,
    RAW_DATA_DIR,
    STATE_DIR,
    TESTS_DIR,
)
from src.services import etf_scale_service
from src.services.etf_scale_service import update_etf_scale
from src.services.xbrl_pdf_match import DEFAULT_LINKS_PATH
from src.services.xbrl_service import (
    DEFAULT_HTML_DIR,
    DEFAULT_METADATA_PATH,
    DEFAULT_STATE_PATH,
)


def _etf_sample() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-08-14"]),
            "fund_code": pd.Series(["510050"], dtype="string"),
            "fund_name": pd.Series(["测试基金"], dtype="string"),
            "shares_10k": [1.0],
        }
    )


def test_project_paths_are_absolute_and_derived_from_paths_module() -> None:
    expected_root = Path(__file__).resolve().parents[1]

    assert PROJECT_ROOT == expected_root
    assert PROJECT_ROOT.is_absolute()
    assert DATA_DIR == PROJECT_ROOT / "data"
    assert RAW_DATA_DIR == PROJECT_ROOT / "data" / "raw"
    assert PROCESSED_DATA_DIR == PROJECT_ROOT / "data" / "processed"
    assert STATE_DIR == PROJECT_ROOT / "state"
    assert DOCS_DIR == PROJECT_ROOT / "docs"
    assert TESTS_DIR == PROJECT_ROOT / "tests"


def test_runtime_defaults_do_not_follow_current_working_directory(
    monkeypatch,
) -> None:
    outside_project = PROJECT_ROOT.parents[1]
    monkeypatch.chdir(outside_project)
    saved_paths: list[Path] = []
    monkeypatch.setattr(etf_scale_service, "parquet_exists", lambda path: False)
    monkeypatch.setattr(
        etf_scale_service,
        "save_parquet",
        lambda frame, path: saved_paths.append(Path(path)),
    )

    result = update_etf_scale(fetcher=_etf_sample)

    assert Path.cwd() == outside_project
    assert result.path == PROJECT_ROOT / "data" / "processed" / "etf_scale.parquet"
    assert saved_paths == [result.path]
    assert result.path.is_relative_to(PROJECT_ROOT)
    assert DEFAULT_METADATA_PATH == PROCESSED_DATA_DIR / "xbrl_metadata.parquet"
    assert DEFAULT_HTML_DIR == RAW_DATA_DIR / "xbrl" / "html"
    assert DEFAULT_STATE_PATH == STATE_DIR / "xbrl_update_state.json"
    assert DEFAULT_LINKS_PATH == PROCESSED_DATA_DIR / "xbrl_pdf_links.parquet"
    # Windows 下避免 pytest 清理 tmp_path 时进程仍停留在待删除目录中。
    monkeypatch.chdir(PROJECT_ROOT)
