from __future__ import annotations

import io
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.cli import (
    MIN_WATCH_INTERVAL,
    ModuleSpec,
    _run_watch,
    _watch_intervals,
    main,
)
from src.config.logging_config import LOGGER_NAMESPACE


class FakeClock:
    def __init__(self, *, stop_on_sleep: int) -> None:
        self.value = 0.0
        self.sleep_calls = 0
        self.stop_on_sleep = stop_on_sleep

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.sleep_calls += 1
        if self.sleep_calls >= self.stop_on_sleep:
            raise KeyboardInterrupt
        self.value += seconds

    def now(self) -> datetime:
        return datetime(2026, 8, 15, 9, 0, 0) + timedelta(seconds=self.value)


def _spec(tmp_path: Path, name: str, update) -> ModuleSpec:
    return ModuleSpec(
        name,
        name,
        update,
        (tmp_path / f"{name}.parquet",),
        ("date",),
    )


def _flush_logs() -> None:
    for handler in logging.getLogger(LOGGER_NAMESPACE).handlers:
        handler.flush()


def test_watch_runs_immediately_then_only_due_modules(tmp_path: Path) -> None:
    calls: list[tuple[str, float]] = []
    fake = FakeClock(stop_on_sleep=2)
    registry = {
        name: _spec(
            tmp_path,
            name,
            lambda name=name: (
                calls.append((name, fake.value))
                or SimpleNamespace(status="no_update")
            ),
        )
        for name in ("fund-announcements", "etf-scale")
    }

    code = _run_watch(
        registry=registry,
        module_names=None,
        base_interval=60,
        output=io.StringIO(),
        clock=fake.monotonic,
        sleeper=fake.sleep,
        wall_clock=fake.now,
    )

    assert code == 0
    assert calls == [
        ("etf-scale", 0.0),
        ("fund-announcements", 0.0),
        ("fund-announcements", 60.0),
    ]
    assert _watch_intervals(tuple(registry), 60) == {
        "fund-announcements": 60,
        "etf-scale": 180,
    }


def test_watch_failure_does_not_stop_and_logs_traceback(tmp_path: Path) -> None:
    calls: list[str] = []
    fake = FakeClock(stop_on_sleep=2)
    log_path = tmp_path / "watch.log"

    def fail() -> object:
        calls.append("failed")
        raise RuntimeError("temporary remote error")

    registry = {
        "fund-announcements": _spec(tmp_path, "fund-announcements", fail),
        "etf-scale": _spec(
            tmp_path,
            "etf-scale",
            lambda: calls.append("ok") or SimpleNamespace(status="no_update"),
        ),
    }
    output = io.StringIO()

    code = main(
        ["watch", "--interval", "60"],
        registry=registry,
        output=output,
        log_path=log_path,
        watch_clock=fake.monotonic,
        watch_sleeper=fake.sleep,
        watch_wall_clock=fake.now,
    )
    _flush_logs()
    log_text = log_path.read_text(encoding="utf-8")

    assert code == 0
    assert calls == ["ok", "failed", "failed"]
    assert output.getvalue().count("fund-announcements: failed") == 2
    assert "Traceback (most recent call last)" in log_text
    assert "watch started" in log_text
    assert "next check module=fund-announcements" in log_text
    assert "watch stopped reason=KeyboardInterrupt" in log_text


def test_watch_modules_filter_and_does_not_print_dataframe(tmp_path: Path) -> None:
    calls: list[str] = []
    fake = FakeClock(stop_on_sleep=1)
    large_frame = pd.DataFrame({"value": range(1000)})
    registry = {
        name: _spec(
            tmp_path,
            name,
            lambda name=name: calls.append(name)
            or SimpleNamespace(status="no_update", data=large_frame),
        )
        for name in ("fund-announcements", "etf-scale", "xbrl")
    }
    output = io.StringIO()

    code = main(
        ["watch", "--interval", "60", "--modules", "etf-scale", "xbrl"],
        registry=registry,
        output=output,
        watch_clock=fake.monotonic,
        watch_sleeper=fake.sleep,
        watch_wall_clock=fake.now,
    )

    assert code == 0
    assert calls == ["etf-scale", "xbrl"]
    assert "DataFrame" not in output.getvalue()
    assert "1000 rows" not in output.getvalue()
    assert "watch stopped" in output.getvalue()


def test_watch_interval_below_minimum_is_rejected(tmp_path: Path) -> None:
    registry = {"etf-scale": _spec(tmp_path, "etf-scale", lambda: None)}
    with pytest.raises(SystemExit) as exc_info:
        main(
            ["watch", "--interval", str(MIN_WATCH_INTERVAL - 1)],
            registry=registry,
            output=io.StringIO(),
        )
    assert exc_info.value.code == 2


def test_watch_default_log_is_cwd_independent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    fake = FakeClock(stop_on_sleep=1)
    outside = tmp_path / "outside"
    outside.mkdir()
    project_log = tmp_path / "project" / "logs" / "sse_fund_data.log"
    monkeypatch.chdir(outside)
    monkeypatch.setattr("src.cli.DEFAULT_LOG_PATH", project_log)
    registry = {
        "fund-announcements": _spec(
            tmp_path,
            "fund-announcements",
            lambda: SimpleNamespace(status="no_update"),
        )
    }

    code = main(
        ["watch", "--interval", "60"],
        registry=registry,
        watch_clock=fake.monotonic,
        watch_sleeper=fake.sleep,
        watch_wall_clock=fake.now,
    )
    capsys.readouterr()
    _flush_logs()

    assert code == 0
    assert project_log.is_file()
    assert not (outside / "logs" / "sse_fund_data.log").exists()
