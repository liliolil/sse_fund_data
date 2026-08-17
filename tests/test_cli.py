from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.cli import MODULES, ModuleSpec, main
from src.config.paths import PROJECT_ROOT as CONFIGURED_ROOT


def _frame(data_date: str = "2026-08-15", rows: int = 1) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime([data_date] * rows),
            "value": range(rows),
        }
    )


def _registry(
    tmp_path: Path,
    *,
    updates: dict[str, object] | None = None,
    backfills: dict[str, object] | None = None,
) -> dict[str, ModuleSpec]:
    updates = updates or {}
    backfills = backfills or {}
    registry: dict[str, ModuleSpec] = {}
    for name in ("alpha", "beta"):
        path = tmp_path / f"{name}.parquet"
        update_value = updates.get(name, SimpleNamespace(status="no_update"))
        backfill_value = backfills.get(name)

        def updater(value: object = update_value) -> object:
            if isinstance(value, Exception):
                raise value
            return value

        def backfiller(start: str, end: str, value: object = backfill_value) -> object:
            if isinstance(value, Exception):
                raise value
            return value

        registry[name] = ModuleSpec(
            name=name,
            label=name.title(),
            update=updater,
            parquet_paths=(path,),
            latest_columns=("date",),
            state_path=tmp_path / f"{name}.json",
            backfill=backfiller if name in backfills else None,
        )
    return registry


def test_status_reads_local_files_without_remote_and_survives_module_error(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path)
    _frame(rows=2).to_parquet(registry["alpha"].parquet_paths[0], index=False)
    registry["alpha"].state_path.write_text(
        json.dumps(
            {"status": "no_update", "last_check_time": "2026-08-15T01:02:03Z"}
        ),
        encoding="utf-8",
    )
    registry["beta"].parquet_paths[0].write_text("not parquet", encoding="utf-8")
    output = io.StringIO()

    code = main(["status"], registry=registry, output=output)
    text = output.getvalue()

    assert code == 0
    assert "alpha" in text and "no_update" in text and "2" in text
    assert "2026-08-15" in text
    assert "beta" in text and "error" in text


def test_unknown_module_has_nonzero_exit(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["update", "unknown"], registry=_registry(tmp_path), output=io.StringIO())
    assert exc_info.value.code == 2


def test_update_dispatch_and_dataframe_is_not_printed(tmp_path: Path) -> None:
    called: list[str] = []
    path = tmp_path / "alpha.parquet"
    _frame(rows=3).to_parquet(path, index=False)

    def update() -> object:
        called.append("alpha")
        return SimpleNamespace(status="updated", data=_frame(rows=1000))

    spec = ModuleSpec("alpha", "Alpha", update, (path,), ("date",))
    output = io.StringIO()

    code = main(["update", "alpha"], registry={"alpha": spec}, output=output)

    assert code == 0 and called == ["alpha"]
    assert "alpha: updated" in output.getvalue()
    assert "DataFrame" not in output.getvalue()
    assert "1000 rows" not in output.getvalue()


def test_backfill_dispatch_and_unsupported_backfill(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []
    path = tmp_path / "alpha.parquet"
    _frame().to_parquet(path, index=False)

    def backfill(start: str, end: str) -> object:
        calls.append((start, end))
        return SimpleNamespace(status="backfilled")

    supported = ModuleSpec(
        "alpha", "Alpha", lambda: None, (path,), ("date",), backfill=backfill
    )
    unsupported = ModuleSpec(
        "beta", "Beta", lambda: None, (tmp_path / "beta.parquet",), ("date",)
    )
    output = io.StringIO()
    registry = {"alpha": supported, "beta": unsupported}

    assert main(
        ["backfill", "alpha", "--start", "2026-08-01", "--end", "2026-08-15"],
        registry=registry,
        output=output,
    ) == 0
    assert calls == [("2026-08-01", "2026-08-15")]

    output = io.StringIO()
    assert main(
        ["backfill", "beta", "--start", "2026-08-01", "--end", "2026-08-15"],
        registry=registry,
        output=output,
    ) == 2
    assert "backfill not supported" in output.getvalue()


def test_backfill_date_validation(tmp_path: Path) -> None:
    registry = _registry(tmp_path, backfills={"alpha": SimpleNamespace(status="ok")})
    with pytest.raises(SystemExit) as invalid_format:
        main(
            ["backfill", "alpha", "--start", "20260801", "--end", "2026-08-15"],
            registry=registry,
            output=io.StringIO(),
        )
    assert invalid_format.value.code == 2

    output = io.StringIO()
    code = main(
        ["backfill", "alpha", "--start", "2026-08-16", "--end", "2026-08-15"],
        registry=registry,
        output=output,
    )
    assert code == 2
    assert "start date" in output.getvalue()


def test_update_all_continues_after_failure_and_returns_nonzero(tmp_path: Path) -> None:
    calls: list[str] = []

    def make_update(name: str, fail: bool = False):
        def update() -> object:
            calls.append(name)
            if fail:
                raise RuntimeError("temporary failure")
            return SimpleNamespace(status="no_update")

        return update

    registry = {
        name: ModuleSpec(
            name,
            name,
            make_update(name, fail=name == "beta"),
            (tmp_path / f"{name}.parquet",),
            ("date",),
        )
        for name in ("alpha", "beta", "gamma")
    }
    output = io.StringIO()

    code = main(["update", "all"], registry=registry, output=output)

    assert code == 1
    assert calls == ["alpha", "beta", "gamma"]
    assert "beta: failed" in output.getvalue()
    assert "summary: success=2 failed=1" in output.getvalue()


def test_test_command_invokes_exact_pytest_and_returns_exit_code(tmp_path: Path) -> None:
    calls: list[tuple[list[str], Path, bool]] = []

    def runner(command, *, cwd, check):
        calls.append((command, cwd, check))
        return subprocess.CompletedProcess(command, 7)

    output = io.StringIO()
    code = main(
        ["test"],
        registry=_registry(tmp_path),
        output=output,
        test_runner=runner,
    )

    assert code == 7
    assert calls == [
        (["pytest", "-v", "--basetemp", ".pytest_all_tmp"], CONFIGURED_ROOT, False)
    ]


def test_registry_paths_and_cli_are_cwd_independent(monkeypatch: pytest.MonkeyPatch) -> None:
    outside = CONFIGURED_ROOT.parents[1]
    monkeypatch.chdir(outside)
    assert all(
        path.is_absolute()
        for spec in MODULES.values()
        for path in spec.parquet_paths
    )
    output = io.StringIO()
    assert main(["status"], output=output) == 0
    assert "fund-master" in output.getvalue()
    monkeypatch.chdir(CONFIGURED_ROOT)
