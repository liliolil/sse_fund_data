"""项目目录与运行时文件路径。"""

from __future__ import annotations

from pathlib import Path


# 当前文件位于 <project>/src/config/paths.py，向上两级得到项目根目录。
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
HISTORY_DATA_DIR = DATA_DIR / "history"
STATE_DIR = PROJECT_ROOT / "state"
DOCS_DIR = PROJECT_ROOT / "docs"
TESTS_DIR = PROJECT_ROOT / "tests"
LOGS_DIR = PROJECT_ROOT / "logs"
DEFAULT_LOG_PATH = LOGS_DIR / "sse_fund_data.log"
