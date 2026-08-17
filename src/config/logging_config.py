"""项目统一日志配置。"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from src.config.paths import DEFAULT_LOG_PATH


LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
MAX_LOG_BYTES = 10 * 1024 * 1024
BACKUP_COUNT = 5
LOGGER_NAMESPACE = "sse_fund_data"


def configure_logging(
    *,
    verbose: bool = False,
    log_path: str | Path = DEFAULT_LOG_PATH,
) -> logging.Logger:
    """配置项目文件日志；verbose 时额外把 DEBUG 日志输出到终端。"""
    path = Path(log_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(LOGGER_NAMESPACE)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.propagate = False

    # main() 可在同一测试进程中多次调用，先关闭本模块创建的旧 handler。
    for handler in list(logger.handlers):
        if getattr(handler, "_sse_fund_data_handler", False):
            logger.removeHandler(handler)
            handler.close()

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    file_handler = RotatingFileHandler(
        path,
        maxBytes=MAX_LOG_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    file_handler.setFormatter(formatter)
    file_handler._sse_fund_data_handler = True  # type: ignore[attr-defined]
    logger.addHandler(file_handler)

    if verbose:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(formatter)
        console_handler._sse_fund_data_handler = True  # type: ignore[attr-defined]
        logger.addHandler(console_handler)

    return logger


def get_logger(module: str) -> logging.Logger:
    """返回统一命名空间下的模块 logger。"""
    return logging.getLogger(f"{LOGGER_NAMESPACE}.{module}")
