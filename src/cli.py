"""项目统一命令行入口的注册表、状态汇总和命令分派。"""

from __future__ import annotations

import argparse
import io
import json
import logging
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence, TextIO

import pandas as pd

from src.config.logging_config import configure_logging, get_logger
from src.config.paths import DEFAULT_LOG_PATH, PROJECT_ROOT
from src.services.etf_pcf_service import (
    DEFAULT_HEADER_PATH as ETF_PCF_HEADER_PATH,
    DEFAULT_STATE_PATH as ETF_PCF_STATE_PATH,
    update_etf_pcf,
)
from src.crawlers.etf_pcf import fetch_etf_pcf_list
from src.services.etf_scale_service import (
    DEFAULT_PARQUET_PATH as ETF_SCALE_PATH,
    backfill_etf_scale,
    update_etf_scale,
)
from src.services.fund_announcement_service import (
    DEFAULT_PARQUET_PATH as ANNOUNCEMENT_PATH,
    DEFAULT_STATE_PATH as ANNOUNCEMENT_STATE_PATH,
    backfill_fund_announcements,
    update_fund_announcements,
)
from src.services.fund_company_service import (
    DEFAULT_PARQUET_PATH as COMPANY_PATH,
    update_fund_companies,
)
from src.services.fund_market_maker_service import (
    DEFAULT_PARQUET_PATH as MARKET_MAKER_PATH,
    update_fund_market_makers,
)
from src.services.fund_master_service import (
    DEFAULT_PARQUET_PATH as FUND_MASTER_PATH,
    DEFAULT_STATE_PATH as FUND_MASTER_STATE_PATH,
    update_fund_master,
)
from src.services.fund_market_data_service import (
    DEFAULT_PARQUET_PATH as FUND_MARKET_DATA_PATH,
    DEFAULT_STATE_PATH as FUND_MARKET_DATA_STATE_PATH,
    update_fund_market_data,
)
from src.services.fund_nav_service import (
    DEFAULT_PARQUET_PATH as FUND_NAV_PATH,
    DEFAULT_STATE_PATH as FUND_NAV_STATE_PATH,
    backfill_fund_nav_cli,
    update_fund_nav,
)
from src.services.fund_turnover_service import (
    DEFAULT_PATHS as TURNOVER_PATHS,
    DEFAULT_STATE_PATH as TURNOVER_STATE_PATH,
    backfill_fund_turnover,
    update_fund_turnover,
)
from src.services.lof_scale_service import (
    DEFAULT_PARQUET_PATH as LOF_SCALE_PATH,
    DEFAULT_STATE_PATH as LOF_SCALE_STATE_PATH,
    backfill_lof_scale,
    update_lof_scale,
)
from src.services.money_market_scale_service import (
    DEFAULT_PARQUET_PATH as MONEY_SCALE_PATH,
    DEFAULT_STATE_PATH as MONEY_SCALE_STATE_PATH,
    backfill_money_market_scale,
    update_money_market_scale,
)
from src.services.money_fund_redemption_params_service import (
    DEFAULT_PARQUET_PATH as MONEY_REDEMPTION_PATH,
    DEFAULT_STATE_PATH as MONEY_REDEMPTION_STATE_PATH,
    update_money_fund_redemption_params,
)
from src.services.reits_scale_service import (
    DEFAULT_PARQUET_PATH as REITS_SCALE_PATH,
    DEFAULT_STATE_PATH as REITS_SCALE_STATE_PATH,
    backfill_reits_scale,
    update_reits_scale,
)
from src.services.xbrl_service import (
    DEFAULT_METADATA_PATH as XBRL_PATH,
    DEFAULT_STATE_PATH as XBRL_STATE_PATH,
    update_xbrl_metadata,
)


UpdateCallable = Callable[[], Any]
BackfillCallable = Callable[[str, str], Any]
SourceBackfillCallable = Callable[[str, str, str], Any]


@dataclass(frozen=True)
class ModuleSpec:
    name: str
    label: str
    update: UpdateCallable
    parquet_paths: tuple[Path, ...]
    latest_columns: tuple[str | None, ...]
    state_path: Path | None = None
    backfill: BackfillCallable | None = None
    source_backfill: SourceBackfillCallable | None = None

    def __post_init__(self) -> None:
        if len(self.parquet_paths) != len(self.latest_columns):
            raise ValueError(f"{self.name} path/date-column counts do not match")


@dataclass(frozen=True)
class AggregateResult:
    status: str
    results: tuple[Any, ...]
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class StatusRecord:
    module: str
    status: str
    rows: int | None
    latest_date: str
    state: str
    last_check_time: str


def _read_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"State file must contain an object: {path}")
    return payload


def _configured_pcf_codes() -> tuple[str, ...]:
    codes: list[str] = []
    if ETF_PCF_STATE_PATH.is_file():
        state = _read_json_object(ETF_PCF_STATE_PATH)
        legacy_codes = state.get("fund_codes", [])
        if isinstance(legacy_codes, list):
            codes.extend(str(code).strip() for code in legacy_codes if str(code).strip())
        funds = state.get("funds", [])
        if isinstance(funds, list):
            for item in funds:
                if isinstance(item, dict) and item.get("fund_code"):
                    codes.append(str(item["fund_code"]).strip())
    if not codes and ETF_PCF_HEADER_PATH.is_file():
        headers = pd.read_parquet(ETF_PCF_HEADER_PATH, columns=["fund_code"])
        codes.extend(headers["fund_code"].dropna().astype(str).str.strip())
    unique_codes = tuple(dict.fromkeys(code for code in codes if code))
    if not unique_codes:
        raise RuntimeError(
            "ETF PCF has no configured funds; initialize a safe watch list first"
        )
    return unique_codes


def _update_pcf() -> Any:
    codes = _configured_pcf_codes()
    # 仅查询 watchlist 中的代码，保存官方 ETF_CLASS；不扩展为全市场 XML 下载。
    classes: dict[str, str] = {}
    for code in codes:
        rows = fetch_etf_pcf_list(fund_code=code, request_interval=0)
        if not rows.empty and pd.notna(rows.loc[0, "etf_class"]):
            classes[code] = str(rows.loc[0, "etf_class"])
    return update_etf_pcf(codes, etf_class_by_fund_code=classes)


def _configured_xbrl_partition() -> tuple[str, str]:
    if not XBRL_STATE_PATH.is_file():
        raise RuntimeError(
            "XBRL state is missing; reportTypeCode/reportYear are not configured"
        )
    state = _read_json_object(XBRL_STATE_PATH)
    report_type = str(state.get("reportTypeCode") or "").strip()
    report_year = str(state.get("reportYear") or "").strip()
    if not report_type or not report_year:
        raise RuntimeError("XBRL state has no reportTypeCode/reportYear")
    return report_type, report_year


def _update_xbrl() -> Any:
    report_type, report_year = _configured_xbrl_partition()
    return update_xbrl_metadata(report_type, report_year)


TURNOVER_FREQUENCIES = ("daily", "weekly", "monthly", "yearly")


def _aggregate_status(results: Sequence[Any], errors: Sequence[str]) -> str:
    if errors:
        return "partial_failure"
    statuses = [str(getattr(result, "status", "completed")) for result in results]
    for preferred in ("updated", "backfilled", "initialized"):
        if preferred in statuses:
            return preferred
    return statuses[0] if statuses and len(set(statuses)) == 1 else "completed"


def _update_turnover_all_frequencies() -> AggregateResult:
    results: list[Any] = []
    errors: list[str] = []
    for frequency in TURNOVER_FREQUENCIES:
        try:
            results.append(update_fund_turnover(frequency))
        except Exception as exc:  # 单频率失败不阻断其他频率。
            errors.append(f"{frequency}: {type(exc).__name__}: {exc}")
    return AggregateResult(_aggregate_status(results, errors), tuple(results), tuple(errors))


def _backfill_turnover_all_frequencies(start: str, end: str) -> AggregateResult:
    results: list[Any] = []
    errors: list[str] = []
    for frequency in TURNOVER_FREQUENCIES:
        try:
            results.append(backfill_fund_turnover(frequency, start, end))
        except Exception as exc:
            errors.append(f"{frequency}: {type(exc).__name__}: {exc}")
    return AggregateResult(_aggregate_status(results, errors), tuple(results), tuple(errors))


MODULES: dict[str, ModuleSpec] = {
    "fund-master": ModuleSpec(
        "fund-master",
        "Fund master",
        update_fund_master,
        (FUND_MASTER_PATH,),
        ("observed_at",),
        FUND_MASTER_STATE_PATH,
    ),
    "fund-companies": ModuleSpec(
        "fund-companies",
        "Fund companies",
        update_fund_companies,
        (COMPANY_PATH,),
        ("observed_at",),
    ),
    "fund-market-makers": ModuleSpec(
        "fund-market-makers",
        "Fund market makers",
        update_fund_market_makers,
        (MARKET_MAKER_PATH,),
        ("observed_at",),
    ),
    "etf-scale": ModuleSpec(
        "etf-scale",
        "ETF scale",
        update_etf_scale,
        (ETF_SCALE_PATH,),
        ("date",),
        backfill=backfill_etf_scale,
    ),
    "lof-scale": ModuleSpec(
        "lof-scale",
        "LOF scale",
        update_lof_scale,
        (LOF_SCALE_PATH,),
        ("date",),
        LOF_SCALE_STATE_PATH,
        backfill_lof_scale,
    ),
    "money-market-scale": ModuleSpec(
        "money-market-scale",
        "Money market scale",
        update_money_market_scale,
        (MONEY_SCALE_PATH,),
        ("date",),
        MONEY_SCALE_STATE_PATH,
        backfill_money_market_scale,
    ),
    "reits-scale": ModuleSpec(
        "reits-scale",
        "REITs scale",
        update_reits_scale,
        (REITS_SCALE_PATH,),
        ("date",),
        REITS_SCALE_STATE_PATH,
        backfill_reits_scale,
    ),
    "fund-nav": ModuleSpec(
        "fund-nav",
        "Fund NAV",
        update_fund_nav,
        (FUND_NAV_PATH,),
        ("nav_date",),
        FUND_NAV_STATE_PATH,
        source_backfill=backfill_fund_nav_cli,
    ),
    "fund-market-data": ModuleSpec(
        "fund-market-data",
        "Fund market data",
        update_fund_market_data,
        (FUND_MARKET_DATA_PATH,),
        ("snapshot_time",),
        FUND_MARKET_DATA_STATE_PATH,
    ),
    "money-fund-redemption-params": ModuleSpec(
        "money-fund-redemption-params",
        "Money fund redemption parameters",
        update_money_fund_redemption_params,
        (MONEY_REDEMPTION_PATH,),
        ("trade_date",),
        MONEY_REDEMPTION_STATE_PATH,
    ),
    "fund-turnover": ModuleSpec(
        "fund-turnover",
        "Fund turnover",
        _update_turnover_all_frequencies,
        tuple(TURNOVER_PATHS[frequency] for frequency in TURNOVER_FREQUENCIES),
        ("period_key",) * 4,
        TURNOVER_STATE_PATH,
        _backfill_turnover_all_frequencies,
    ),
    "fund-announcements": ModuleSpec(
        "fund-announcements",
        "Fund announcements",
        update_fund_announcements,
        (ANNOUNCEMENT_PATH,),
        ("announcement_date",),
        ANNOUNCEMENT_STATE_PATH,
        backfill_fund_announcements,
    ),
    "etf-pcf": ModuleSpec(
        "etf-pcf",
        "ETF PCF",
        _update_pcf,
        (ETF_PCF_HEADER_PATH,),
        ("trading_day",),
        ETF_PCF_STATE_PATH,
    ),
    "xbrl": ModuleSpec(
        "xbrl",
        "XBRL metadata",
        _update_xbrl,
        (XBRL_PATH,),
        ("reportSendDate",),
        XBRL_STATE_PATH,
    ),
}

UPDATE_ALL_ORDER = (
    "fund-master",
    "fund-companies",
    "fund-market-makers",
    "etf-scale",
    "lof-scale",
    "money-market-scale",
    "reits-scale",
    "fund-nav",
    "fund-market-data",
    "money-fund-redemption-params",
    "fund-turnover",
    "fund-announcements",
    "etf-pcf",
    "xbrl",
)

DEFAULT_WATCH_INTERVAL = 600
MIN_WATCH_INTERVAL = 60
# 基准间隔的倍数：公告 10 分钟、规模/成交/PCF 30 分钟、主数据/XBRL 2 小时。
# fund-nav 默认每天检查一次；watch 启动时仍会立即检查。
WATCH_INTERVAL_MULTIPLIERS: dict[str, int] = {
    "fund-announcements": 1,
    "etf-scale": 3,
    "lof-scale": 3,
    "money-market-scale": 3,
    "reits-scale": 3,
    "fund-nav": 144,
    "fund-market-data": 3,
    "money-fund-redemption-params": 36,
    "fund-turnover": 3,
    "etf-pcf": 3,
    "fund-master": 12,
    "fund-companies": 12,
    "fund-market-makers": 12,
    "xbrl": 12,
}

# 行情快照独立保护：即使 watch --interval 60，也不能每分钟抓全市场。
WATCH_MIN_INTERVALS: dict[str, int] = {
    "fund-market-data": 300,
    "money-fund-redemption-params": 3600,
}


def _latest_value(series: pd.Series) -> str:
    values = series.dropna()
    if values.empty:
        return "-"
    text = values.astype(str).str.strip()
    text = text[~text.isin(["", "-"])]
    if text.empty:
        return "-"
    parsed = pd.to_datetime(text, errors="coerce")
    if parsed.notna().any():
        return parsed.max().date().isoformat()
    return str(text.max())


def _state_summary(state: dict[str, Any]) -> tuple[str | None, str]:
    if isinstance(state.get("frequencies"), dict):
        frequency_states = state["frequencies"]
        statuses = [
            f"{name}:{item.get('status', '-')}"
            for name, item in frequency_states.items()
            if isinstance(item, dict)
        ]
        times = [
            str(item.get("last_successful_check_time") or "")
            for item in frequency_states.values()
            if isinstance(item, dict)
        ]
        return ",".join(statuses) or None, max(times, default="") or "-"
    status = state.get("status") or state.get("overall_status")
    checked = state.get("last_check_time") or state.get("last_successful_check_time")
    return (str(status) if status is not None else None, str(checked or "-"))


def collect_module_status(spec: ModuleSpec) -> StatusRecord:
    rows = 0
    latest_parts: list[str] = []
    initialized_files = 0
    errors: list[str] = []
    for index, (path, column) in enumerate(zip(spec.parquet_paths, spec.latest_columns)):
        if not path.is_file():
            latest_parts.append("-")
            continue
        initialized_files += 1
        try:
            frame = pd.read_parquet(path)
            rows += len(frame)
            latest = "-" if column is None or column not in frame else _latest_value(frame[column])
            prefix = TURNOVER_FREQUENCIES[index] if len(spec.parquet_paths) > 1 else ""
            latest_parts.append(f"{prefix}={latest}" if prefix else latest)
        except Exception as exc:
            errors.append(f"{path.name}: {type(exc).__name__}: {exc}")
            latest_parts.append("error")

    state_label = "-" if spec.state_path is None else "missing"
    state_status: str | None = None
    last_check = "-"
    if spec.state_path is not None and spec.state_path.is_file():
        try:
            state_status, last_check = _state_summary(_read_json_object(spec.state_path))
            state_label = "ok"
        except Exception as exc:
            errors.append(f"state: {type(exc).__name__}: {exc}")
            state_label = "error"

    if errors:
        status = "error"
    elif initialized_files == 0:
        status = "not_initialized"
    elif initialized_files < len(spec.parquet_paths):
        status = "partial"
    else:
        status = state_status or "ready"
    return StatusRecord(
        module=spec.name,
        status=status,
        rows=None if errors and initialized_files == 0 else rows,
        latest_date=";".join(latest_parts) if latest_parts else "-",
        state=state_label,
        last_check_time=last_check,
    )


def collect_status(registry: Mapping[str, ModuleSpec] = MODULES) -> list[StatusRecord]:
    """只读取本地文件；单模块损坏不会阻断其他模块。"""
    return [collect_module_status(spec) for spec in registry.values()]


def print_status_table(records: Sequence[StatusRecord], output: TextIO) -> None:
    headers = ("module", "status", "rows", "latest_date", "state", "last_check")
    rows = [
        (
            item.module,
            item.status,
            "-" if item.rows is None else str(item.rows),
            item.latest_date,
            item.state,
            item.last_check_time,
        )
        for item in records
    ]
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows))
        for index in range(len(headers))
    ]
    print("  ".join(value.ljust(widths[index]) for index, value in enumerate(headers)), file=output)
    print("  ".join("-" * width for width in widths), file=output)
    for row in rows:
        print("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)), file=output)


def _result_status(result: Any) -> str:
    return str(getattr(result, "status", "completed"))


def _result_errors(result: Any) -> tuple[str, ...]:
    errors = getattr(result, "errors", ())
    return tuple(str(error) for error in errors)


def _print_result(spec: ModuleSpec, result: Any, output: TextIO) -> None:
    local = collect_module_status(spec)
    print(
        f"{spec.name}: {_result_status(result)} | rows={local.rows if local.rows is not None else '-'} "
        f"| latest={local.latest_date}",
        file=output,
    )
    for error in _result_errors(result):
        print(f"  error: {error}", file=output)


def _parse_iso_date(value: str) -> str:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from exc
    return parsed.date().isoformat()


def _parse_watch_interval(value: str) -> int:
    try:
        interval = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("interval must be an integer number of seconds") from exc
    if interval < MIN_WATCH_INTERVAL:
        raise argparse.ArgumentTypeError(
            f"interval must be at least {MIN_WATCH_INTERVAL} seconds"
        )
    return interval


def build_parser(registry: Mapping[str, ModuleSpec] = MODULES) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SSE fund data command line")
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="enable DEBUG logging on the terminal and in the log file",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="show local module status without network")

    update_parser = subparsers.add_parser("update", help="run incremental update")
    update_parser.add_argument("module", choices=[*registry.keys(), "all"])

    backfill_parser = subparsers.add_parser("backfill", help="run supported history backfill")
    backfill_parser.add_argument("module", choices=list(registry.keys()))
    backfill_parser.add_argument("--start", required=True, type=_parse_iso_date)
    backfill_parser.add_argument("--end", required=True, type=_parse_iso_date)
    backfill_parser.add_argument(
        "--source",
        choices=("lof", "reits"),
        help="source route for modules such as fund-nav",
    )

    subparsers.add_parser("test", help="run the complete pytest suite")

    watch_parser = subparsers.add_parser("watch", help="continuously run incremental updates")
    watch_parser.add_argument(
        "--interval",
        type=_parse_watch_interval,
        default=DEFAULT_WATCH_INTERVAL,
        help=f"base check interval in seconds (minimum {MIN_WATCH_INTERVAL})",
    )
    watch_parser.add_argument(
        "--modules",
        nargs="+",
        choices=list(registry.keys()),
        help="only watch the selected modules",
    )
    return parser


def _run_update(
    module: str,
    registry: Mapping[str, ModuleSpec],
    output: TextIO,
) -> int:
    cli_logger = get_logger("cli")
    if module != "all":
        spec = registry[module]
        module_logger = get_logger(module)
        started = time.perf_counter()
        module_logger.info("update start")
        try:
            result = spec.update()
            _print_result(spec, result, output)
            errors = _result_errors(result)
            duration = time.perf_counter() - started
            if errors:
                module_logger.error(
                    "update result status=%s duration=%.3fs errors=%s",
                    _result_status(result),
                    duration,
                    "; ".join(errors),
                )
                return 1
            module_logger.info(
                "update result status=%s duration=%.3fs",
                _result_status(result),
                duration,
            )
            return 0
        except Exception as exc:
            module_logger.exception(
                "update failed duration=%.3fs", time.perf_counter() - started
            )
            print(f"{module}: failed | {type(exc).__name__}: {exc}", file=output)
            return 1

    all_started = time.perf_counter()
    cli_logger.info("update all started")
    succeeded: list[str] = []
    failed: list[str] = []
    order = [name for name in UPDATE_ALL_ORDER if name in registry]
    order.extend(name for name in registry if name not in order)
    for name in order:
        spec = registry[name]
        module_logger = get_logger(name)
        started = time.perf_counter()
        module_logger.info("update start")
        try:
            result = spec.update()
            _print_result(spec, result, output)
            if _result_errors(result):
                failed.append(name)
                module_logger.error(
                    "update result status=%s duration=%.3fs errors=%s",
                    _result_status(result),
                    time.perf_counter() - started,
                    "; ".join(_result_errors(result)),
                )
            else:
                succeeded.append(name)
                module_logger.info(
                    "update result status=%s duration=%.3fs",
                    _result_status(result),
                    time.perf_counter() - started,
                )
        except Exception as exc:
            failed.append(name)
            module_logger.exception(
                "update failed duration=%.3fs", time.perf_counter() - started
            )
            print(f"{name}: failed | {type(exc).__name__}: {exc}", file=output)
    print(
        f"summary: success={len(succeeded)} failed={len(failed)}"
        + (f" | failed_modules={','.join(failed)}" if failed else ""),
        file=output,
    )
    cli_logger.info(
        "update all summary success_count=%d failed_count=%d total_duration=%.3fs",
        len(succeeded),
        len(failed),
        time.perf_counter() - all_started,
    )
    return 1 if failed else 0


def _run_backfill(
    module: str,
    start: str,
    end: str,
    registry: Mapping[str, ModuleSpec],
    output: TextIO,
    source: str | None = None,
) -> int:
    logger = get_logger(module)
    started = time.perf_counter()
    logger.info("backfill start start_date=%s end_date=%s", start, end)
    if start > end:
        logger.error("backfill rejected: start date later than end date")
        print("backfill: failed | start date must not be later than end date", file=output)
        return 2
    spec = registry[module]
    if spec.backfill is None and spec.source_backfill is None:
        logger.warning("backfill not supported")
        print(f"{module}: backfill not supported", file=output)
        return 2
    try:
        if spec.source_backfill is not None:
            if source is None:
                logger.warning("backfill rejected: source is required")
                print(f"{module}: backfill requires --source", file=output)
                return 2
            result = spec.source_backfill(source, start, end)
        else:
            if source is not None:
                logger.warning("backfill rejected: source is not supported")
                print(f"{module}: --source is not supported", file=output)
                return 2
            assert spec.backfill is not None
            result = spec.backfill(start, end)
        _print_result(spec, result, output)
        errors = _result_errors(result)
        level = logging.ERROR if errors else logging.INFO
        logger.log(
            level,
            "backfill result status=%s duration=%.3fs%s",
            _result_status(result),
            time.perf_counter() - started,
            f" errors={'; '.join(errors)}" if errors else "",
        )
        return 1 if errors else 0
    except Exception as exc:
        logger.exception("backfill failed duration=%.3fs", time.perf_counter() - started)
        print(f"{module}: failed | {type(exc).__name__}: {exc}", file=output)
        return 1


def _run_tests(
    output: TextIO,
    runner: Callable[..., subprocess.CompletedProcess[Any]] = subprocess.run,
) -> int:
    command = ["pytest", "-v", "--basetemp", ".pytest_all_tmp"]
    print("running: " + " ".join(command), file=output)
    logger = get_logger("cli")
    started = time.perf_counter()
    logger.info("test started command=%s", " ".join(command))
    completed = runner(command, cwd=PROJECT_ROOT, check=False)
    logger.info(
        "test finished exit_code=%d duration=%.3fs",
        completed.returncode,
        time.perf_counter() - started,
    )
    return int(completed.returncode)


def _watch_intervals(
    module_names: Sequence[str], base_interval: int
) -> dict[str, int]:
    return {
        name: max(
            base_interval * WATCH_INTERVAL_MULTIPLIERS.get(name, 1),
            WATCH_MIN_INTERVALS.get(name, 0),
        )
        for name in module_names
    }


def _emit_watch_result(buffer: io.StringIO, output: TextIO, now: datetime) -> None:
    prefix = f"[{now:%H:%M:%S}]"
    for line in buffer.getvalue().splitlines():
        if line.strip():
            print(f"{prefix} {line}", file=output, flush=True)


def _interrupt_watch(signum: int, frame: Any) -> None:
    """把 Windows Ctrl+Break 与 Ctrl+C 统一为安全退出路径。"""
    raise KeyboardInterrupt


def _run_watch(
    *,
    registry: Mapping[str, ModuleSpec],
    module_names: Sequence[str] | None,
    base_interval: int,
    output: TextIO,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
    wall_clock: Callable[[], datetime] = datetime.now,
) -> int:
    """单线程 watch 调度；首次复用 update all，之后仅运行到期模块。"""
    selected_names = tuple(dict.fromkeys(module_names or registry.keys()))
    selected_registry = {name: registry[name] for name in selected_names}
    intervals = _watch_intervals(selected_names, base_interval)
    logger = get_logger("watch")
    logger.info(
        "watch started modules=%s base_interval=%ds schedule=%s",
        ",".join(selected_names),
        base_interval,
        intervals,
    )
    print(
        f"[{wall_clock():%H:%M:%S}] watch started; Ctrl+C to stop",
        file=output,
        flush=True,
    )

    previous_sigbreak: Any = None
    if hasattr(signal, "SIGBREAK"):
        previous_sigbreak = signal.getsignal(signal.SIGBREAK)
        signal.signal(signal.SIGBREAK, _interrupt_watch)
    try:
        initial_output = io.StringIO()
        _run_update("all", selected_registry, initial_output)
        _emit_watch_result(initial_output, output, wall_clock())

        completed_at = clock()
        next_due = {
            name: completed_at + intervals[name] for name in selected_names
        }
        for name in selected_names:
            logger.info(
                "next check module=%s in=%ds at=%s",
                name,
                intervals[name],
                (wall_clock() + timedelta(seconds=intervals[name])).isoformat(),
            )

        while True:
            now = clock()
            due_names = [name for name in selected_names if next_due[name] <= now]
            if not due_names:
                earliest = min(next_due.values())
                sleeper(max(0.0, earliest - now))
                continue

            for name in due_names:
                result_output = io.StringIO()
                _run_update(name, selected_registry, result_output)
                _emit_watch_result(result_output, output, wall_clock())
                next_due[name] = clock() + intervals[name]
                logger.info(
                    "next check module=%s in=%ds at=%s",
                    name,
                    intervals[name],
                    (wall_clock() + timedelta(seconds=intervals[name])).isoformat(),
                )
    except KeyboardInterrupt:
        logger.info("watch stopped reason=KeyboardInterrupt")
        print(f"[{wall_clock():%H:%M:%S}] watch stopped", file=output, flush=True)
        return 0
    finally:
        if hasattr(signal, "SIGBREAK") and previous_sigbreak is not None:
            signal.signal(signal.SIGBREAK, previous_sigbreak)


def main(
    argv: Sequence[str] | None = None,
    *,
    registry: Mapping[str, ModuleSpec] = MODULES,
    output: TextIO | None = None,
    test_runner: Callable[..., subprocess.CompletedProcess[Any]] = subprocess.run,
    log_path: str | Path | None = None,
    watch_clock: Callable[[], float] = time.monotonic,
    watch_sleeper: Callable[[float], None] = time.sleep,
    watch_wall_clock: Callable[[], datetime] = datetime.now,
) -> int:
    stream = output or sys.stdout
    args = build_parser(registry).parse_args(argv)
    # 注入 log_path 供测试隔离；真实 CLI 始终使用项目根目录下的默认日志。
    logging_enabled = output is None or log_path is not None
    if logging_enabled:
        configure_logging(
            verbose=args.verbose,
            log_path=log_path or DEFAULT_LOG_PATH,
        )
    logger = get_logger("cli")
    logger.info("CLI started command=%s verbose=%s", args.command, args.verbose)
    logger.debug("CLI arguments=%s", vars(args))
    if args.command == "status":
        started = time.perf_counter()
        records = collect_status(registry)
        print_status_table(records, stream)
        logger.info(
            "status finished modules=%d errors=%d duration=%.3fs",
            len(records),
            sum(record.status == "error" for record in records),
            time.perf_counter() - started,
        )
        return 0
    if args.command == "update":
        return _run_update(args.module, registry, stream)
    if args.command == "backfill":
        return _run_backfill(
            args.module, args.start, args.end, registry, stream, args.source
        )
    if args.command == "test":
        return _run_tests(stream, test_runner)
    if args.command == "watch":
        return _run_watch(
            registry=registry,
            module_names=args.modules,
            base_interval=args.interval,
            output=stream,
            clock=watch_clock,
            sleeper=watch_sleeper,
            wall_clock=watch_wall_clock,
        )
    raise AssertionError(f"Unhandled command: {args.command}")
