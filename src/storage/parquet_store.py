"""轻量级 Parquet 文件读写工具。"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pandas as pd


def parquet_exists(path: str | Path) -> bool:
    """返回指定 Parquet 文件是否存在。"""
    return Path(path).is_file()


def read_parquet(path: str | Path) -> pd.DataFrame:
    """读取 Parquet；文件不存在时明确抛出异常。"""
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Parquet file does not exist: {source}")
    return pd.read_parquet(source)


def save_parquet(frame: pd.DataFrame, path: str | Path) -> None:
    """先写同目录临时文件，再原子替换目标文件。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{target.stem}.",
            suffix=".tmp.parquet",
            dir=target.parent,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        frame.to_parquet(temporary_path, index=False)
        os.replace(temporary_path, target)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
