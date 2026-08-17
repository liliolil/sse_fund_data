from __future__ import annotations

import io
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import SimpleNamespace

from src.cli import ModuleSpec, main
from src.config import logging_config
from src.config.paths import DEFAULT_LOG_PATH, LOGS_DIR, PROJECT_ROOT


def _spec(tmp_path: Path, update) -> ModuleSpec:
    return ModuleSpec(
        "sample",
        "Sample",
        update,
        (tmp_path / "sample.parquet",),
        ("date",),
    )


def _flush_handlers() -> None:
    for handler in logging.getLogger(logging_config.LOGGER_NAMESPACE).handlers:
        handler.flush()


def test_logging_creates_file_and_writes_info(tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / "test.log"
    logger = logging_config.configure_logging(log_path=log_path)
    logging.getLogger("sse_fund_data.sample").info("status=no_update")
    _flush_handlers()

    assert logger.level == logging.INFO
    assert log_path.is_file()
    assert "INFO sse_fund_data.sample status=no_update" in log_path.read_text(
        encoding="utf-8"
    )


def test_default_log_path_is_project_based_and_cwd_independent(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    assert LOGS_DIR == PROJECT_ROOT / "logs"
    assert DEFAULT_LOG_PATH == PROJECT_ROOT / "logs" / "sse_fund_data.log"
    assert DEFAULT_LOG_PATH.is_absolute()

    simulated_project_log = tmp_path / "project" / "logs" / "sse_fund_data.log"
    outside_cwd = tmp_path / "outside"
    outside_cwd.mkdir()
    monkeypatch.setattr("src.cli.DEFAULT_LOG_PATH", simulated_project_log)
    monkeypatch.chdir(outside_cwd)

    assert main(["status"], registry={"sample": _spec(tmp_path, lambda: None)}) == 0
    capsys.readouterr()
    _flush_handlers()
    assert simulated_project_log.is_file()
    assert not (outside_cwd / "logs" / "sse_fund_data.log").exists()


def test_error_traceback_and_update_all_failure_are_logged(tmp_path: Path) -> None:
    log_path = tmp_path / "failure.log"

    def fail() -> object:
        raise RuntimeError("network unavailable")

    registry = {
        "sample": _spec(tmp_path, fail),
        "ok": ModuleSpec(
            "ok",
            "Ok",
            lambda: SimpleNamespace(status="no_update"),
            (tmp_path / "ok.parquet",),
            ("date",),
        ),
    }
    output = io.StringIO()

    code = main(
        ["update", "all"], registry=registry, output=output, log_path=log_path
    )
    _flush_handlers()
    text = log_path.read_text(encoding="utf-8")

    assert code == 1
    assert "sample update failed" in text
    assert "Traceback (most recent call last)" in text
    assert "RuntimeError: network unavailable" in text
    assert "update all summary success_count=1 failed_count=1" in text


def test_verbose_enables_debug_and_rotation_configuration(tmp_path: Path) -> None:
    log_path = tmp_path / "verbose.log"
    output = io.StringIO()

    code = main(
        ["--verbose", "status"],
        registry={"sample": _spec(tmp_path, lambda: None)},
        output=output,
        log_path=log_path,
    )
    logger = logging.getLogger(logging_config.LOGGER_NAMESPACE)
    _flush_handlers()
    file_handlers = [
        handler for handler in logger.handlers if isinstance(handler, RotatingFileHandler)
    ]

    assert code == 0
    assert logger.level == logging.DEBUG
    assert "DEBUG sse_fund_data.cli CLI arguments=" in log_path.read_text(
        encoding="utf-8"
    )
    assert len(file_handlers) == 1
    assert file_handlers[0].maxBytes == logging_config.MAX_LOG_BYTES
    assert file_handlers[0].backupCount == logging_config.BACKUP_COUNT


def test_logging_does_not_change_success_exit_code(tmp_path: Path) -> None:
    log_path = tmp_path / "success.log"
    spec = _spec(tmp_path, lambda: SimpleNamespace(status="no_update"))

    assert main(
        ["update", "sample"],
        registry={"sample": spec},
        output=io.StringIO(),
        log_path=log_path,
    ) == 0
