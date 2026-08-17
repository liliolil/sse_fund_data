# sse_fund_data

当前版本：**v1.0**

`sse_fund_data` 是一个上海证券交易所基金公开数据采集、增量更新与本地存储项目。项目优先使用上交所公开 HTTP 接口，以 crawler、service、Parquet、checkpoint 和统一 CLI 组成可维护的数据流程，不依赖 Selenium。

## 当前支持的数据

- ETF、LOF、交易型货币基金和公募 REITs 规模
- 基金成交概况（日、周、月、年）
- LOF 日净值和 REITs 评估净值
- ETF、LOF、REITs 实时行情快照
- 交易型货币基金每日申购/赎回限额
- ETF 与交易型货币基金最新 PCF，包括原始 XML、header 和成分券
- 上交所基金公告与 PDF 链接
- EID XBRL 元数据、增量检查、展示 HTML 和 XBRL/PDF 匹配能力
- `fund_master` 基金主数据
- 基金管理公司维表
- 基金—做市商关系

## v1.0 Scope

v1.0 包含公开接口采集、数据质量检查、Parquet 原子保存、适用模块的历史回填、增量更新、状态文件、统一 CLI、轮询式 watch 和轮转日志。

以下 P1/P2 方向不属于 v1.0 blocker：

- REITs 逐基金成交统计
- REITs 发售与扩募
- REITs 分红
- REITs 大宗交易
- 分级 LOF 历史资料
- 遗留封闭式基金历史资料

## 环境与安装

建议使用 **Python 3.13**；v1.0 验收环境为 Python 3.13.5。运行依赖只有 pandas、pyarrow、requests 和 urllib3。

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
```

开发和测试环境：

```bash
python -m pip install -r requirements-dev.txt
```

## 运行

命令均可从任意当前工作目录执行，只要调用的是项目根目录下的 `main.py`。所有默认运行路径由 `src/config/paths.py` 根据代码位置推导，不依赖 cwd。

```bash
python main.py status
python main.py update all
python main.py update etf-scale
python main.py watch
python main.py watch --interval 600
python main.py test
```

指定 watch 模块：

```bash
python main.py watch --modules fund-announcements etf-scale xbrl
```

支持历史回填的模块包括规模、成交概况、公告和基金净值。示例：

```bash
python main.py backfill etf-scale --start 2026-08-01 --end 2026-08-13
python main.py backfill fund-announcements --start 2026-08-01 --end 2026-08-13
python main.py backfill fund-nav --source lof --start 2026-08-01 --end 2026-08-13
python main.py backfill fund-nav --source reits --start 2024-06-30 --end 2025-12-31
```

REITs 净值回填只查询明确的评估日期，不会逐日扫描多年。对不支持回填的模块，CLI 会明确输出 `backfill not supported`。

## 实时更新语义

`watch` 是保守频率的轮询式增量更新，不是交易所 WebSocket，也不是毫秒级行情流。启动时会立即检查所选模块，之后按模块分级间隔运行；单模块异常不会终止整个 watch。

`fund_market_data` 保存运行时行情快照，历史能力为 `snapshot_from_now`。官方接口没有已验证的历史行情日期参数，因此不能恢复启动采集之前的行情。

## 历史能力限制

- PCF 仅有已验证的最新 XML 下载接口，没有已验证的历史 PCF URL。
- `fund_market_data` 没有已验证的历史查询接口，只能从现在开始积累快照。
- `money_fund_redemption_params` 没有已验证的日期参数，只能从现在开始积累本地快照历史。
- LOF NAV 和 REITs NAV 可以查询已验证历史日期，但最早历史边界为 `partially_verified`。
- 部分规模、成交和信息披露接口支持历史参数，但没有通过高频扫描穷举最早边界。
- XBRL 增量依赖日期窗口和远程总数对账；发现差异时标记 `needs_reconciliation`，不会自动进行数百页全量扫描。

## 数据目录

- `data/raw/`：官方原始 XML、HTML、JSON 等证据文件。
- `data/processed/`：标准化后的 Parquet 主表。
- `data/history/`：需要保留的历史快照。
- `state/`：增量 checkpoint、最近检查状态和模块配置。
- `logs/`：CLI/watch 日志及轮转文件。
- `docs/`：接口调研、覆盖审计和架构说明。

运行数据和日志默认由 `.gitignore` 排除；已有本地数据不会被安装或测试过程删除。

## 数据格式

结构化数据主要保存为 Parquet，原始证据按来源保存在 `data/raw/`。基金代码等标识字段保持字符串；日期和数值字段在 service 层完成标准化和质量检查。写入流程尽量使用临时文件加原子替换，避免异常时破坏已有数据。

## 项目结构

```text
sse_fund_data/
├─ main.py
├─ src/
│  ├─ config/       # 路径与日志配置
│  ├─ crawlers/     # 官方接口请求与原始字段映射
│  ├─ services/     # 校验、增量、回填和状态管理
│  ├─ storage/      # Parquet 基础读写
│  └─ utils/        # JSONP 等通用工具
├─ tests/
├─ data/
│  ├─ raw/
│  ├─ processed/
│  └─ history/
├─ state/
├─ logs/
├─ docs/
├─ requirements.txt
└─ requirements-dev.txt
```

详细分层和更新语义见 [docs/architecture.md](docs/architecture.md)。各数据源的真实接口证据与边界见 `docs/` 下的调研文档。

## 测试

```bash
pytest -v --basetemp .pytest_all_tmp
```

也可以使用：

```bash
python main.py test
```

v1.0 最终验收共 **175 项测试**。
